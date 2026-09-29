"""Arrancar y parar ComfyUI cuando el lote lo necesita.

El motor de generación no tiene por qué estar levantado todo el día: tenerlo
abierto mantiene los modelos cargados en la GPU (≈2,8 GB de los 8 GB de una
3050) aunque no esté haciendo nada. :class:`ComfyUIService` lo levanta cuando
empieza un lote, espera a que su API responda y lo **para al terminar** si fue
él quien lo arrancó (nunca cierra una instancia que ya estaba en marcha).

Todo es opcional: si no hay ComfyUI instalado donde se espera, el servicio
avisa y falla con un mensaje claro, sin tocar nada del sistema.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx
from loguru import logger

from youber.genvideo.client import ComfyUIError
from youber.genvideo.models import DEFAULT_SERVER_URL
from youber.genvideo.queue import default_dir

#: Variable de entorno con la carpeta de ComfyUI.
ENV_DIR = "YOUBER_COMFYUI_DIR"

#: Cuánto se espera a que ComfyUI levante (segundos): cargar 10 GB de pesos
#: desde disco tarda, sobre todo la primera vez.
DEFAULT_STARTUP_TIMEOUT = 300.0

#: Cada cuánto se pregunta si ya responde.
DEFAULT_POLL_INTERVAL = 2.0

#: Argumentos con los que se levanta (solo escucha en local).
DEFAULT_ARGS: tuple[str, ...] = ("main.py", "--listen", "127.0.0.1")


def default_directory() -> Path:
    """Carpeta de ComfyUI: ``YOUBER_COMFYUI_DIR`` o ``~/ai/ComfyUI``."""
    configured = os.environ.get(ENV_DIR)
    return Path(configured) if configured else Path.home() / "ai" / "ComfyUI"


def default_python(directory: Path) -> Path:
    """Intérprete del venv de ComfyUI (Windows o POSIX)."""
    scripts = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return directory / ".venv" / scripts / executable


class ComfyUIService:
    """Controla el proceso de ComfyUI (arrancar, esperar, parar).

    Attributes:
        server_url: URL base del servidor (de ahí sale el puerto).
        directory: Carpeta de ComfyUI (donde está ``main.py``).
        python: Intérprete del venv de ComfyUI.
        log_path: Fichero donde se deja la salida del proceso.
    """

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER_URL,
        *,
        directory: str | Path | None = None,
        python: str | Path | None = None,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        log_path: str | Path | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.directory = Path(directory) if directory else default_directory()
        self.python = Path(python) if python else default_python(self.directory)
        self.startup_timeout = startup_timeout
        self.poll_interval = poll_interval
        self.log_path = (
            Path(log_path) if log_path else default_dir() / "comfyui.log"
        )
        self.port = self._port_from_url()
        self.process: subprocess.Popen[bytes] | None = None

    def _port_from_url(self) -> int:
        """Puerto del servidor, sacado de su URL (por defecto 8188)."""
        tail = self.server_url.rsplit(":", 1)[-1]
        return int(tail) if tail.isdigit() else 8188

    @property
    def args(self) -> list[str]:
        """Argumentos con los que se levanta el proceso."""
        return [*DEFAULT_ARGS, "--port", str(self.port)]

    async def is_up(self) -> bool:
        """``True`` si el API de ComfyUI responde."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{self.server_url}/system_stats")
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def spawn(self) -> subprocess.Popen[bytes]:
        """Levanta ComfyUI desprendido, con su salida en :attr:`log_path`.

        El proceso sigue vivo aunque el runner termine o el gateway se
        reinicie: es un hijo propio, no una dependencia del proceso actual.
        """
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, "ab")  # noqa: SIM115 - lo cierra el hijo
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        logger.info(f"Levantando ComfyUI: {self.python} {' '.join(self.args)}")
        return subprocess.Popen(  # noqa: S603 - ruta y args son nuestros
            [str(self.python), *self.args],
            cwd=str(self.directory),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def kill(self, process: subprocess.Popen[bytes] | None = None) -> None:
        """Para el proceso de ComfyUI (el que arrancamos nosotros)."""
        target = process or self.process
        if target is None:
            return
        try:
            target.kill()
        except OSError as exc:  # pragma: no cover - carrera con el cierre
            logger.warning(f"No se pudo parar ComfyUI ({target.pid}): {exc}")
            return
        logger.info(f"ComfyUI parado (pid {target.pid})")

    async def ensure_running(self) -> bool:
        """Deja ComfyUI listo para trabajar.

        Returns:
            ``True`` si lo ha arrancado este método (y por tanto se puede
            parar al terminar), ``False`` si ya estaba levantado.

        Raises:
            ComfyUIError: si no hay instalación donde se espera, el proceso
                muere al arrancar o no responde dentro del tiempo dado.
        """
        if await self.is_up():
            logger.info(f"ComfyUI ya estaba levantado en {self.server_url}")
            return False
        if not self.python.exists():
            raise ComfyUIError(
                f"No encuentro el intérprete de ComfyUI: {self.python}. "
                f"Indica la carpeta con {ENV_DIR} o el parámetro comfyui_dir."
            )
        self.process = self.spawn()
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if await self.is_up():
                logger.info(f"ComfyUI listo en {self.server_url} (pid {self.process.pid})")
                return True
            if self.process.poll() is not None:
                raise ComfyUIError(
                    f"ComfyUI terminó al arrancar (revisa {self.log_path})"
                )
            await asyncio.sleep(self.poll_interval)
        self.kill()
        raise ComfyUIError(
            f"ComfyUI no respondió en {self.startup_timeout:g} s "
            f"(revisa {self.log_path})"
        )

    async def stop(self, process: subprocess.Popen[bytes] | None = None) -> bool:
        """Para ComfyUI si lo arrancamos nosotros.

        Returns:
            ``True`` si se ha parado algo.
        """
        target = process or self.process
        if target is None:
            return False
        self.kill(target)
        self.process = None
        return True
