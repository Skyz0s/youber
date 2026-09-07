# src/youber/montage/adapter.py
"""Adaptador para OpenMontage - Orquestador de producción de video.

Contrato del driver de OpenMontage
----------------------------------
OpenMontage (https://github.com/calesthio/OpenMontage) es un sistema de
producción *agent-driven*: la inteligencia la pone un agente que lee los
manifiestos de pipeline y maneja las herramientas. No expone (todavía) un CLI
headless estable tipo ``montage.py``.

Para integrarlo desde ``youber``, el adapter busca un **driver** en la raíz
del clon con esta interfaz mínima::

    python montage.py --prompt <texto> --output-dir <dir> \
        [--pipeline <name>] [--playbook <name>] [--budget-usd <n>] \
        [--output <fichero.mp4>]

El driver escribe el vídeo producido en ``--output`` (si se da) o en
``--output-dir`` y termina con código 0. Si el driver no existe, ``produce()``
devuelve un ``ProductionResult(success=False)`` con instrucciones claras en
lugar de fallar en silencio o inventar un vídeo.

Localización del clon (por orden):
  1. Parámetro ``openmontage_dir`` del constructor.
  2. Variable de entorno ``OPENMONTAGE_DIR``.
  3. ``<project_dir>/OpenMontage`` (convenio histórico).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from loguru import logger

from youber.montage.models import ProductionPlan, ProductionResult

DEFAULT_PIPELINE = "documentary"

# Plantillas por tipo de pipeline (el topic se inyecta).
_PROMPT_TEMPLATES: dict[str, str] = {
    "documentary": (
        "Make a 75-second documentary montage about {topic}. "
        "Use real footage only, no narration, elegiac tone, with music."
    ),
    "explainer": "Make a 60-second animated explainer about {topic}.",
    "tutorial": "Make a tutorial video about {topic}.",
    "hybrid": (
        "Make a video montage about {topic}, mixing real footage and "
        "generated visuals, with music."
    ),
}

# Marcadores que identifican un checkout real de OpenMontage.
_CLONE_MARKERS = ("config.yaml", "setup.py", "render_demo.py")


class OpenMontageError(RuntimeError):
    """OpenMontage no está disponible o la producción falló."""


class OpenMontageAdapter:
    """Adaptador para controlar OpenMontage desde Youber."""

    def __init__(
        self,
        project_dir: Path | None = None,
        openmontage_dir: Path | None = None,
        timeout: float = 1800.0,
    ) -> None:
        self.project_dir = Path(project_dir) if project_dir else Path.cwd()
        self.timeout = timeout
        self.openmontage_dir = self._resolve_openmontage_dir(openmontage_dir)
        self.driver = self._default_driver()

    # ------------------------------------------------------------------
    # Resolución del clon
    # ------------------------------------------------------------------
    def _resolve_openmontage_dir(self, explicit: Path | None) -> Path | None:
        """Resuelve el checkout de OpenMontage (arg > env > convenio)."""
        if explicit is not None:
            candidate = Path(explicit)
            return candidate if self._looks_like_clone(candidate) else None
        env_dir = os.environ.get("OPENMONTAGE_DIR")
        if env_dir:
            candidate = Path(env_dir)
            if self._looks_like_clone(candidate):
                return candidate
        candidate = self.project_dir / "OpenMontage"
        return candidate if self._looks_like_clone(candidate) else None

    @staticmethod
    def _looks_like_clone(directory: Path) -> bool:
        """Un checkout real tiene config.yaml/setup.py/render_demo.py."""
        return directory.is_dir() and any(
            (directory / marker).exists() for marker in _CLONE_MARKERS
        )

    def _default_driver(self) -> Path | None:
        if self.openmontage_dir is None:
            return None
        driver = self.openmontage_dir / "montage.py"
        return driver if driver.is_file() else None

    def _python_bin(self) -> str:
        """Python del venv del clon (si existe) o el intérprete actual."""
        if self.openmontage_dir is None:
            return sys.executable
        venv = self.openmontage_dir / ".venv"
        for candidate in (venv / "Scripts" / "python.exe", venv / "bin" / "python"):
            if candidate.is_file():
                return str(candidate)
        return sys.executable

    # ------------------------------------------------------------------
    # Estado / diagnóstico
    # ------------------------------------------------------------------
    def available(self) -> bool:
        """True si hay clon de OpenMontage y driver ``montage.py``."""
        return self.openmontage_dir is not None and self.driver is not None

    def describe(self) -> str:
        """Texto de diagnóstico para errores accionables."""
        if self.openmontage_dir is None:
            return (
                "OpenMontage no encontrado: define la variable OPENMONTAGE_DIR "
                f"apuntando a un checkout del clon, o colócalo en "
                f"{self.project_dir / 'OpenMontage'}. Ver docs/MONTAGE.md."
            )
        return (
            f"OpenMontage encontrado en {self.openmontage_dir}, pero falta el "
            f"driver {self.driver or '(montage.py)'}. OpenMontage no expone aún un "
            "CLI headless estable: crea un driver montage.py con la interfaz "
            "--prompt/--output-dir (ver docs/MONTAGE.md)."
        )

    # ------------------------------------------------------------------
    # Producción
    # ------------------------------------------------------------------
    async def produce(self, plan: ProductionPlan) -> ProductionResult:
        """Produce un video usando OpenMontage a partir de un ProductionPlan.

        Args:
            plan: Plan de producción (patrón, pipeline, audio, salida).

        Returns:
            ProductionResult: resultado con ruta, duración y resolución reales
            (ffprobe) cuando la producción tiene éxito.
        """
        if not self.available():
            logger.warning("🎬 Producción no disponible: {}", self.describe())
            return ProductionResult(success=False, error=self.describe())

        topic = plan.pattern.title or plan.pattern.path
        output_dir = (
            plan.output_path.parent
            if plan.output_path is not None
            else self.project_dir / "output"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("🎬 Produciendo con OpenMontage: {} (pipeline={})", topic, plan.pipeline)
        try:
            video_path = await self.produce_video(
                topic=topic,
                pipeline=plan.pipeline,
                output_dir=output_dir,
                playbook=plan.playbook,
                budget_usd=plan.budget_usd,
                output_file=plan.output_path,
            )
        except OpenMontageError as exc:
            logger.error("❌ Producción falló: {}", exc)
            return ProductionResult(success=False, error=str(exc))

        duration, resolution = self._probe_video(video_path) or (0.0, (0, 0))
        logger.success(
            "✅ Video producido: {} | {:.1f}s | {}x{}",
            video_path,
            duration,
            resolution[0],
            resolution[1],
        )
        return ProductionResult(
            success=True,
            output_path=video_path,
            duration=duration,
            resolution=resolution,
        )

    async def produce_video(
        self,
        topic: str,
        pipeline: str = DEFAULT_PIPELINE,
        output_dir: Path | None = None,
        **kwargs,
    ) -> Path:
        """Produce un video y devuelve la ruta del archivo generado.

        Args:
            topic: Tema del video.
            pipeline: Pipeline de OpenMontage (documentary, explainer, ...).
            output_dir: Directorio de salida.
            **kwargs: ``playbook``, ``budget_usd``, ``output_file``.

        Returns:
            Path: ruta del video generado.

        Raises:
            OpenMontageError: si OpenMontage no está disponible o falla.
        """
        out_dir = output_dir or self.project_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt = self._build_prompt(topic, pipeline)
        logger.info("📋 Pipeline: {} | Prompt: {}", pipeline, prompt)
        # Solo reenviamos los kwargs que entiende _run_montage.
        allowed = {"playbook", "budget_usd", "output_file"}
        driver_kwargs = {key: value for key, value in kwargs.items() if key in allowed}
        return await self._run_montage(
            prompt,
            out_dir,
            pipeline=pipeline,
            **driver_kwargs,
        )

    def _build_prompt(self, topic: str, pipeline: str, **_kwargs) -> str:
        """Construye el prompt para OpenMontage."""
        template = _PROMPT_TEMPLATES.get(pipeline, _PROMPT_TEMPLATES[DEFAULT_PIPELINE])
        return template.format(topic=topic)

    async def _run_montage(
        self,
        prompt: str,
        output_dir: Path,
        *,
        pipeline: str = DEFAULT_PIPELINE,
        playbook: str | None = None,
        budget_usd: float | None = None,
        output_file: Path | None = None,
    ) -> Path:
        """Ejecuta el driver de OpenMontage vía subprocess.

        Contrato del driver (``montage.py`` en la raíz del clon): recibe
        ``--prompt/--output-dir [--pipeline] [--playbook] [--budget-usd]
        [--output]``, escribe el vídeo y termina con código 0.
        """
        if not self.available():
            raise OpenMontageError(self.describe())

        driver = self.driver or Path("montage.py")
        cmd: list[str] = [
            self._python_bin(),
            str(driver),
            "--prompt",
            prompt,
            "--output-dir",
            str(output_dir),
            "--pipeline",
            pipeline,
        ]
        if playbook:
            cmd += ["--playbook", playbook]
        if budget_usd is not None:
            cmd += ["--budget-usd", f"{budget_usd:.2f}"]
        if output_file is not None:
            cmd += ["--output", str(output_file)]

        env = dict(os.environ)
        if self.openmontage_dir is not None:
            env["OPENMONTAGE_DIR"] = str(self.openmontage_dir)

        logger.debug("Ejecutando: {}", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(self.openmontage_dir or self.project_dir),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except TimeoutError:
            proc.kill()
            raise OpenMontageError(
                f"OpenMontage agotó el tiempo ({self.timeout:.0f}s) ejecutando: "
                f"{' '.join(cmd)}"
            ) from None

        if proc.returncode != 0:
            detail_bytes = stderr or stdout or b""
            detail = detail_bytes.decode(errors="replace").strip()[-500:]
            raise OpenMontageError(
                f"OpenMontage falló (exit {proc.returncode}) ejecutando "
                f"{Path(driver).name}: {detail or 'sin salida'}"
            )

        return self._locate_output(output_dir, output_file, cmd)

    def _locate_output(
        self, output_dir: Path, output_file: Path | None, cmd: list[str]
    ) -> Path:
        """Localiza el vídeo producido (--output o el mp4 más reciente)."""
        if output_file is not None:
            if output_file.is_file():
                return output_file
            raise OpenMontageError(
                f"OpenMontage no escribió el archivo esperado: {output_file}"
            )
        candidates = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if candidates:
            return candidates[-1]
        raise OpenMontageError(
            "OpenMontage terminó OK pero no escribió ningún .mp4 en "
            f"{output_dir}. Comando: {' '.join(cmd)}"
        )

    # ------------------------------------------------------------------
    # ffprobe
    # ------------------------------------------------------------------
    @staticmethod
    def _probe_video(path: Path) -> tuple[float, tuple[int, int]] | None:
        """Devuelve (duración, resolución) del vídeo vía ffprobe o None."""
        ffprobe = shutil.which("ffprobe")
        if ffprobe is None or not path.is_file():
            return None
        cmd = [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        width, height = stream.get("width"), stream.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            return None
        try:
            duration = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        return duration, (width, height)
