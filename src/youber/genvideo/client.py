"""Cliente del backend de generación (ComfyUI por API HTTP) y backend de pruebas.

:class:`ComfyUIClient` es el backend de referencia: habla con un ComfyUI local
por su API (``/prompt``, ``/history``, ``/view``, ``/system_stats``, ``/queue``,
``/interrupt``) usando ``httpx`` asíncrono. :class:`StubClient` implementa la misma interfaz
(:class:`GenerationClient`) escribiendo un MP4 sintético con FFmpeg: sirve para
probar el runner completo en CI o en una máquina sin GPU.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx
from loguru import logger

from youber.genvideo.models import DEFAULT_SERVER_URL

#: Extensiones que se consideran vídeo (ComfyUI devuelve ``.mp4`` con SaveVideo).
VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mkv", ".mov", ".gif"})

#: Intervalo de sondeo del historial (segundos).
DEFAULT_POLL_INTERVAL = 3.0

#: Timeout de cada petición a la API de ComfyUI (segundos). Generoso a
#: propósito: mientras genera, el servidor puede tardar minutos en contestar
#: (presión de memoria, VAE troceado) y un timeout corto daba por muertos
#: trabajos que seguían vivos en la GPU (lote del 29-09-2026).
DEFAULT_HTTP_TIMEOUT = 300.0

#: Parones de red **seguidos** sondeando un trabajo antes de comprobar con
#: ``/system_stats`` si el motor sigue en pie.
DEFAULT_MAX_STALLS = 5


class ComfyUIError(RuntimeError):
    """Error al hablar con el backend ComfyUI."""


def describe_error(exc: BaseException) -> str:
    """Mensaje legible de una excepción, con su tipo si no trae texto.

    Los timeouts de ``httpx``/``httpcore`` se stringifican **vacíos**: sin
    esto, un fallo de red queda registrado como un error en blanco (así se
    perdieron tres clips en el lote del 29-09-2026).
    """
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


@dataclass(frozen=True)
class ComfyOutput:
    """Fichero generado por ComfyUI (lo que hay que descargar con ``/view``)."""

    filename: str
    subfolder: str = ""
    kind: str = "output"
    node_id: str = ""

    @property
    def suffix(self) -> str:
        """Extensión del fichero, en minúsculas."""
        return Path(self.filename).suffix.lower()

    @property
    def is_video(self) -> bool:
        """Si el fichero parece un vídeo (y no una imagen o un JSON)."""
        return self.suffix in VIDEO_SUFFIXES


@runtime_checkable
class GenerationClient(Protocol):
    """Interfaz mínima de un backend de generación.

    La implementan :class:`ComfyUIClient` (real) y :class:`StubClient`
    (pruebas), de forma que el runner no sabe con cuál está hablando.
    """

    async def is_up(self) -> bool:
        """Si el backend responde."""
        ...

    async def queue_prompt(self, graph: dict[str, Any]) -> str:
        """Encola un grafo y devuelve su identificador."""
        ...

    async def wait(
        self, prompt_id: str, *, timeout: float, poll_interval: float | None = None
    ) -> dict[str, Any]:
        """Espera a que el trabajo termine y devuelve su entrada del historial."""
        ...

    async def outputs(self, prompt_id: str) -> list[ComfyOutput]:
        """Ficheros generados por un trabajo."""
        ...

    async def download(self, output: ComfyOutput, dest: str | Path) -> Path:
        """Descarga un fichero generado a ``dest``."""
        ...

    async def aclose(self) -> None:
        """Cierra los recursos del cliente."""
        ...

    async def cancel(self, prompt_id: str) -> bool:
        """Suelta un trabajo que ya no interesa y devuelve si hizo algo."""
        ...


def outputs_from(entry: dict[str, Any]) -> list[ComfyOutput]:
    """Extrae los ficheros de salida de una entrada del historial de ComfyUI.

    El historial devuelve, por nodo de salida, listas de ficheros
    (``images``, ``video``, ``gifs``...). Aquí se recogen todos los que tengan
    ``filename``, sea cual sea la clave.
    """
    collected: list[ComfyOutput] = []
    for node_id, node_outputs in (entry.get("outputs") or {}).items():
        if not isinstance(node_outputs, dict):
            continue
        for value in node_outputs.values():
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, dict) and item.get("filename"):
                    collected.append(
                        ComfyOutput(
                            filename=str(item["filename"]),
                            subfolder=str(item.get("subfolder") or ""),
                            kind=str(item.get("type") or "output"),
                            node_id=str(node_id),
                        )
                    )
    return collected


def _error_detail(entry: dict[str, Any]) -> str:
    """Mensaje del primer error de ejecución del historial (o el estado crudo)."""
    status = entry.get("status") or {}
    for message in status.get("messages") or []:
        if isinstance(message, list) and message and message[0] == "execution_error":
            return json.dumps(message[1], ensure_ascii=False)[:500]
    return json.dumps(status, ensure_ascii=False)[:500]


class ComfyUIClient:
    """Backend ComfyUI por su API HTTP.

    Attributes:
        server_url: URL base del servidor (sin barra final).
        client_id: Identificador de cliente que se manda en ``/prompt``.
        poll_interval: Cada cuánto se pregunta por el historial.
        timeout: Timeout de cada petición HTTP (segundos).
        max_stalls: Parones de red seguidos antes de comprobar si el motor vive.
        owns_queue: Si la cola de ComfyUI es nuestra (se puede vaciar al soltar
            un trabajo); ``False`` cuando es un ComfyUI compartido.
    """

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER_URL,
        *,
        client: httpx.AsyncClient | None = None,
        client_id: str | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
        max_stalls: int = DEFAULT_MAX_STALLS,
        owns_queue: bool = True,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.client_id = client_id or uuid.uuid4().hex
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.max_stalls = max_stalls
        self.owns_queue = owns_queue
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> ComfyUIClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        """Cliente HTTP (se crea en diferido)."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._client

    async def aclose(self) -> None:
        """Cierra el cliente HTTP si lo creó este objeto."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def is_up(self) -> bool:
        """``True`` si el servidor de ComfyUI responde."""
        try:
            response = await self.client.get(f"{self.server_url}/system_stats", timeout=5.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def available_options(self, node: str, field: str) -> list[str]:
        """Opciones del desplegable de un nodo (p. ej. qué modelos ve ComfyUI).

        Sirve para comprobar de verdad que los pesos están donde tienen que
        estar, en vez de descubrirlo cuando el trabajo ya está encolado.
        """
        try:
            response = await self.client.get(
                f"{self.server_url}/object_info/{node}", timeout=15.0
            )
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"No se pudo consultar {node} en ComfyUI: {exc}") from exc
        if response.status_code != 200:
            raise ComfyUIError(f"ComfyUI respondió {response.status_code} a /object_info/{node}")
        info = response.json().get(node) or {}
        required = (info.get("input") or {}).get("required") or {}
        spec = required.get(field)
        if isinstance(spec, list) and spec and isinstance(spec[0], list):
            return [str(item) for item in spec[0]]
        return []

    async def queue_prompt(self, graph: dict[str, Any]) -> str:
        """Encola un grafo y devuelve el ``prompt_id``.

        Raises:
            ComfyUIError: si el servidor rechaza el trabajo (grafo inválido,
                modelos que no ve, etc.).
        """
        payload = {"prompt": graph, "client_id": self.client_id}
        response = await self.client.post(f"{self.server_url}/prompt", json=payload)
        if response.status_code >= 400:
            raise ComfyUIError(
                f"ComfyUI rechazó el trabajo ({response.status_code}): {response.text[:600]}"
            )
        data = response.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"ComfyUI no devolvió prompt_id: {json.dumps(data)[:300]}")
        return str(prompt_id)

    async def history(self, prompt_id: str) -> dict[str, Any]:
        """Entrada del historial de un trabajo (``{}`` si aún no está)."""
        response = await self.client.get(f"{self.server_url}/history/{prompt_id}")
        if response.status_code != 200:
            raise ComfyUIError(
                f"ComfyUI respondió {response.status_code} a /history/{prompt_id}"
            )
        return response.json().get(prompt_id) or {}

    async def wait(
        self, prompt_id: str, *, timeout: float, poll_interval: float | None = None
    ) -> dict[str, Any]:
        """Espera a que el trabajo termine.

        Args:
            prompt_id: Trabajo encolado.
            timeout: Segundos máximos de espera.
            poll_interval: Sondeo (por defecto, el del cliente).

        Returns:
            La entrada del historial, ya completada.

        Un parón de red **no** da el trabajo por perdido: mientras ComfyUI
        genera puede tardar minutos en contestar a ``/history``, y rendirse ahí
        mataba clips que seguían vivos. Los parones se cuentan; solo si se
        encadenan :attr:`max_stalls` y el motor ya no responde a
        ``/system_stats`` se corta con un mensaje que lo dice.

        Raises:
            ComfyUIError: si el trabajo falla, si el motor deja de responder o
                si se agota el tiempo.
        """
        interval = poll_interval or self.poll_interval
        deadline = time.monotonic() + timeout
        stalls = 0
        while True:
            try:
                entry = await self.history(prompt_id)
            except httpx.TransportError as exc:
                stalls += 1
                logger.warning(
                    f"ComfyUI no contestó al preguntar por {prompt_id} "
                    f"({stalls}/{self.max_stalls} parones seguidos de "
                    f"{type(exc).__name__}); el trabajo sigue en la GPU"
                )
                if stalls >= self.max_stalls and not await self.is_up():
                    raise ComfyUIError(
                        f"ComfyUI dejó de responder mientras generaba {prompt_id} "
                        f"({stalls} parones seguidos de {self.timeout:g} s y "
                        f"/system_stats tampoco contesta)"
                    ) from exc
                entry = {}
            else:
                stalls = 0
                if entry:
                    status = entry.get("status") or {}
                    if status.get("completed") or status.get("status_str") == "success":
                        return entry
                    if status.get("status_str") == "error":
                        raise ComfyUIError(
                            f"ComfyUI falló al generar {prompt_id}: {_error_detail(entry)}"
                        )
            if time.monotonic() >= deadline:
                raise ComfyUIError(
                    f"Timeout de {timeout:g} s esperando a ComfyUI ({prompt_id})"
                    + (f"; {stalls} parones de red" if stalls else "")
                )
            await asyncio.sleep(interval)

    async def outputs(self, prompt_id: str) -> list[ComfyOutput]:
        """Ficheros generados por un trabajo ya terminado."""
        return outputs_from(await self.history(prompt_id))

    async def download(self, output: ComfyOutput, dest: str | Path) -> Path:
        """Descarga un fichero generado (``/view``) a ``dest``."""
        params = {
            "filename": output.filename,
            "subfolder": output.subfolder,
            "type": output.kind,
        }
        response = await self.client.get(f"{self.server_url}/view", params=params)
        if response.status_code != 200:
            raise ComfyUIError(
                f"No se pudo descargar {output.filename} ({response.status_code})"
            )
        target = Path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target

    async def queue_state(self) -> tuple[list[str], list[str]]:
        """``(en ejecución, en cola)``: ids de los trabajos que ve ComfyUI."""
        response = await self.client.get(f"{self.server_url}/queue")
        if response.status_code != 200:
            raise ComfyUIError(
                f"ComfyUI respondió {response.status_code} a /queue"
            )
        data = response.json() or {}
        running = _queue_ids(data.get("queue_running"))
        pending = _queue_ids(data.get("queue_pending"))
        return running, pending

    async def interrupt(self) -> None:
        """Interrumpe el trabajo que ComfyUI esté ejecutando ahora mismo."""
        response = await self.client.post(f"{self.server_url}/interrupt")
        if response.status_code >= 400:
            raise ComfyUIError(
                f"ComfyUI respondió {response.status_code} a /interrupt"
            )
        logger.warning("ComfyUI: trabajo en ejecución interrumpido")

    async def clear_queue(self) -> None:
        """Vacía los trabajos en cola (los que aún no han empezado)."""
        response = await self.client.post(
            f"{self.server_url}/queue", json={"clear": True}
        )
        if response.status_code >= 400:
            raise ComfyUIError(
                f"ComfyUI respondió {response.status_code} al vaciar la cola"
            )
        logger.warning("ComfyUI: cola de trabajos vaciada")

    async def cancel(self, prompt_id: str, *, clear_pending: bool | None = None) -> bool:
        """Suelta un trabajo que ya no nos interesa.

        Si ``prompt_id`` sigue **en ejecución** se interrumpe; si la cola es
        nuestra (:attr:`owns_queue`) se vacía lo que quede pendiente. Es
        *best-effort*: si ComfyUI no contesta, se avisa y se sigue, porque la
        limpieza nunca debe tumbar el lote.

        Returns:
            ``True`` si se hizo algo.
        """
        clear = self.owns_queue if clear_pending is None else clear_pending
        try:
            running, _ = await self.queue_state()
        except (httpx.HTTPError, ComfyUIError) as exc:
            logger.warning(
                f"No pude consultar la cola de ComfyUI para soltar {prompt_id}: "
                f"{describe_error(exc)}"
            )
            return False
        released = False
        try:
            if prompt_id in running:
                await self.interrupt()
                released = True
            if clear:
                await self.clear_queue()
                released = True
        except (httpx.HTTPError, ComfyUIError) as exc:
            logger.warning(
                f"No pude soltar el trabajo {prompt_id} en ComfyUI: {describe_error(exc)}"
            )
            return released
        return released


def _queue_ids(entries: object) -> list[str]:
    """Ids de los trabajos de ``/queue`` (cada entrada es ``[n, id, grafo...]``)."""
    ids: list[str] = []
    if not isinstance(entries, list):
        return ids
    for item in entries:
        if isinstance(item, list) and len(item) > 1 and item[1]:
            ids.append(str(item[1]))
    return ids


class StubClient:
    """Backend de pruebas: escribe un MP4 sintético sin GPU ni ComfyUI.

    Con ``flat=True`` genera a propósito un clip **plano y oscuro**: es la
    forma de comprobar que la verificación lo caza y que el runner reintenta
    con más steps en vez de dar por bueno un clip inservible.
    """

    name = "stub"

    def __init__(
        self,
        *,
        flat: bool = False,
        seconds: float = 5.0,
        width: int = 1280,
        height: int = 704,
        fps: float = 24.0,
        delay: float = 0.0,
    ) -> None:
        self.flat = flat
        self.seconds = seconds
        self.width = width
        self.height = height
        self.fps = fps
        self.delay = delay
        #: Grafos encolados (para poder inspeccionarlos en los tests).
        self.queued: list[dict[str, Any]] = []
        self._graphs: dict[str, dict[str, Any]] = {}
        self._counter = 0

    async def is_up(self) -> bool:
        """El stub siempre está listo."""
        return True

    async def queue_prompt(self, graph: dict[str, Any]) -> str:
        """«Encola» un grafo (guarda el prompt) y devuelve un id ficticio."""
        self.queued.append(graph)
        self._counter += 1
        prompt_id = f"stub-{self._counter:04d}"
        self._graphs[prompt_id] = graph
        return prompt_id

    def clip_length(self, output: ComfyOutput) -> tuple[int, float]:
        """Frames y fps del clip de esa salida, leídos de su grafo.

        Así el stub genera clips con la duración que se pidió de verdad (la de
        cada plano del guion, por ejemplo) y la verificación mide lo correcto.
        """
        frames = max(1, int(round(self.seconds * self.fps)))
        fps = self.fps
        graph = self._graphs.get(Path(output.filename).stem)
        for node in (graph or {}).values():
            inputs = node.get("inputs") or {}
            if "length" in inputs:
                frames = int(inputs["length"])
            if node.get("class_type") == "CreateVideo":
                fps = float(inputs.get("fps", fps))
        return frames, fps

    async def wait(
        self, prompt_id: str, *, timeout: float, poll_interval: float | None = None
    ) -> dict[str, Any]:
        """Simula el trabajo (con retardo opcional) y la entrada del historial."""
        if self.delay:
            await asyncio.sleep(self.delay)
        return {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {
                "12": {
                    "images": [
                        {"filename": f"{prompt_id}.mp4", "subfolder": "genvideo", "type": "output"}
                    ]
                }
            },
        }

    async def outputs(self, prompt_id: str) -> list[ComfyOutput]:
        """El fichero ficticio que devolvería ComfyUI."""
        return [ComfyOutput(filename=f"{prompt_id}.mp4", subfolder="genvideo", node_id="12")]

    async def download(self, output: ComfyOutput, dest: str | Path) -> Path:
        """Escribe el MP4 sintético con FFmpeg (plano y oscuro si ``flat``)."""
        target = Path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        frames, fps = self.clip_length(output)
        size = f"{self.width}x{self.height}"
        source = (
            f"color=c=black:s={size}:r={fps:g}"
            if self.flat
            else f"testsrc2=s={size}:r={fps:g}"
        )
        command = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-t",
            f"{frames / fps:.4f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
        result = await asyncio.to_thread(subprocess.run, command, capture_output=True)
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")[-500:]
            raise RuntimeError(f"El stub no pudo crear el clip de prueba: {stderr}")
        logger.debug(f"Stub: clip de prueba en {target}")
        return target

    async def cancel(self, prompt_id: str) -> bool:
        """El stub no tiene trabajos huérfanos: no hay nada que soltar."""
        return False

    async def aclose(self) -> None:
        """Nada que cerrar."""
        return None
