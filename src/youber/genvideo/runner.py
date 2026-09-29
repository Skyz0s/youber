"""Runner nocturno: guion → prompts por escena → clips generados y verificados.

Es la pieza que se deja trabajando de madrugada. Toma un guion
(:class:`~youber.script.models.Script`) o una lista de prompts, construye un
:class:`~youber.genvideo.models.ClipRequest` por plano, los encola y los
genera de uno en uno con el backend local. Después **verifica cada clip**
(duraciones, resolución y métricas de contenido) y, si sale plano u oscuro,
**reintenta con más steps** en lugar de dejarlo pasar. Al terminar escribe el
manifiesto (JSON) y un resumen (Markdown).

La cola es persistida: si el runner se corta a mitad de la noche, al volver a
arrancarlo continúa exactamente donde iba (:class:`~youber.genvideo.queue.JobQueue`).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import datetime, timedelta
from datetime import time as dt_time
from pathlib import Path

from loguru import logger

from youber.genvideo import power
from youber.genvideo.client import ComfyUIClient, GenerationClient, StubClient, outputs_from
from youber.genvideo.graph import build_graph
from youber.genvideo.models import (
    BatchReport,
    ClipRequest,
    GenConfig,
    JobStatus,
    Resolution,
    clip_id,
)
from youber.genvideo.queue import JobQueue, default_dir
from youber.genvideo.verify import MIN_DETAIL, verify_clip
from youber.script.generator import DEFAULT_DURATION
from youber.script.models import Script
from youber.visuals.models import VisualStyle
from youber.visuals.prompts import build_shot_plan

#: Reintentos por clip antes de descartarlo (el 2.º intento sube los steps).
DEFAULT_MAX_ATTEMPTS = 2

#: Tope de steps al reintentar un clip que sale plano.
DEFAULT_RETRY_STEPS = 16

#: Fallos seguidos que abortan el lote (señal de que el backend se ha caído).
MAX_CONSECUTIVE_FAILURES = 3

#: Margen sobre la estimación para decidir si un clip cabe antes del cierre.
WINDOW_MARGIN = 0.15


def _today_at(reference: datetime, moment: dt_time) -> datetime:
    """La hora ``moment`` del día de ``reference`` (sin microsegundos)."""
    return reference.replace(
        hour=moment.hour, minute=moment.minute, second=0, microsecond=0
    )


def resolve_window(
    start: dt_time | None,
    end: dt_time | None,
    *,
    now: datetime | None = None,
    allow_wait: bool = False,
) -> tuple[datetime | None, datetime | None]:
    """Convierte una ventana horaria (p. ej. ``22:00``-``07:00``) en instantes.

    Soporta ventanas que **cruzan la medianoche**: si la hora de cierre ya ha
    pasado hoy, se entiende que es la de mañana. Si la hora de inicio ya pasó,
    el lote empieza ahora (estamos dentro de la ventana).

    Args:
        start: Hora de inicio (``None`` para empezar ya).
        end: Hora de cierre (``None`` para no cerrar).
        now: Momento de referencia (por defecto, ahora).
        allow_wait: Si es ``True`` y la hora de inicio aún no ha llegado, el
            lote espera a que llegue en vez de arrancar de inmediato.

    Returns:
        ``(inicio, fin)`` en horas absolutas; cualquiera puede ser ``None``.
    """
    reference = now or datetime.now()
    end_at = _today_at(reference, end) if end is not None else None
    if end_at is not None and end_at <= reference:
        end_at += timedelta(days=1)
    if start is None:
        return None, end_at
    start_at = _today_at(reference, start)
    if start_at <= reference:
        start_at = reference
    elif not allow_wait:
        start_at = reference
    if end_at is not None and start_at >= end_at:
        start_at = reference
    return start_at, end_at


def slugify(text: str, *, limit: int = 40) -> str:
    """Nombre de fichero seguro a partir de un texto."""
    safe = [char if char.isalnum() else "-" for char in text.lower()]
    return "-".join(part for part in "".join(safe).split("-") if part)[:limit] or "clip"


def requests_from_script(
    script: Script,
    *,
    config: GenConfig | None = None,
    preset: Resolution = Resolution.HD,
    shots: int | None = None,
    seed_base: int = 42,
    style: VisualStyle = VisualStyle.CINEMATIC,
    mood: str | None = None,
    tone: str | None = None,
    keywords: Sequence[str] = (),
    motion_offset: int = 0,
) -> list[ClipRequest]:
    """Un :class:`ClipRequest` por plano del plan visual del guion.

    Reutiliza :func:`youber.visuals.prompts.build_shot_plan`: el papel de la
    escena (gancho, desarrollo, clímax...) elige el encuadre, y el mood, el
    tono y las palabras clave completan el prompt. Así la generación de vídeo
    habla el mismo lenguaje visual que el resto del framework.

    Args:
        script: Guion de ``youber.script``.
        config: Configuración de generación (si falta, la del preset).
        preset: Preset medido (``720p`` o ``480p``).
        shots: Número de planos (por defecto, el que sugiera la duración).
        seed_base: Semilla del primer plano; los demás suman su índice.
        style: Estilo visual de los planos.
        mood: Mood de la música (si falta, el del guion).
        tone: Tono narrativo del brief.
        keywords: Palabras clave para enriquecer los prompts.
        motion_offset: Desplazamiento del ciclo de movimientos.

    Returns:
        Los clips a generar, en orden de montaje.
    """
    settings = config or GenConfig.for_resolution(preset)
    plan = build_shot_plan(
        script.topic,
        script.scenes,
        duration=script.total_duration,
        style=style,
        mood=mood or (script.music_mood.value if script.music_mood else None),
        tone=tone,
        keywords=keywords,
        shots=shots,
        fps=int(settings.fps),
        motion_offset=motion_offset,
    )
    requests: list[ClipRequest] = []
    for shot in plan.shots:
        scene = (
            script.scenes[shot.scene_index]
            if shot.scene_index is not None and shot.scene_index < len(script.scenes)
            else None
        )
        role = scene.type.value if scene is not None else "plano"
        title = scene.title if scene is not None else shot.beat
        requests.append(
            ClipRequest(
                id=clip_id(shot.prompt, seed_base + shot.index, width=settings.width, steps=settings.steps),
                label=f"{shot.index + 1:02d} {role} {slugify(title, limit=24)}",
                scene_index=shot.scene_index,
                scene_type=role,
                prompt=shot.prompt,
                seed=seed_base + shot.index,
                duration_hint=shot.duration,
                config=settings.model_copy(deep=True),
            )
        )
    return requests


def requests_from_prompts(
    prompts: Sequence[str],
    *,
    config: GenConfig | None = None,
    preset: Resolution = Resolution.HD,
    seed_base: int = 42,
    labels: Sequence[str] = (),
) -> list[ClipRequest]:
    """Un clip por prompt (el camino corto, sin guion de por medio)."""
    settings = config or GenConfig.for_resolution(preset)
    requests: list[ClipRequest] = []
    for index, prompt in enumerate(prompts):
        label = labels[index] if index < len(labels) else f"clip {index + 1:02d}"
        requests.append(
            ClipRequest(
                id=clip_id(prompt, seed_base + index, width=settings.width, steps=settings.steps),
                label=label,
                prompt=prompt,
                seed=seed_base + index,
                config=settings.model_copy(deep=True),
            )
        )
    return requests


def script_from_topic(topic: str, *, duration: float = DEFAULT_DURATION) -> Script:
    """Guion mínimo para un tema suelto (sin canal de referencia)."""
    from youber.script.generator import generate_script

    return generate_script({}, topic=topic, duration=duration)


def write_report(report: BatchReport, directory: str | Path) -> tuple[Path, Path]:
    """Escribe el manifiesto (JSON) y el resumen (Markdown) de un lote.

    Returns:
        Las rutas del JSON y del Markdown.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / f"lote-{report.id}.json"
    markdown_path = target / f"lote-{report.id}.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path


class NightlyRunner:
    """Genera un lote de clips: cola, verificación y parada por ventana.

    Attributes:
        client: Backend de generación (ComfyUI o stub).
        config: Configuración de referencia del lote.
        queue: Cola persistida.
        output_dir: Carpeta donde se dejan los clips.
        deadline: Instante en el que el lote deja de generar.
    """

    def __init__(
        self,
        *,
        client: GenerationClient,
        config: GenConfig | None = None,
        queue: JobQueue | None = None,
        output_dir: str | Path | None = None,
        verify: bool = True,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_steps: int = DEFAULT_RETRY_STEPS,
        min_detail: float = MIN_DETAIL,
        deadline: datetime | None = None,
        window_start: datetime | None = None,
        max_clips: int | None = None,
        max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
        keep_awake: bool = True,
    ) -> None:
        self.client = client
        self.config = config or GenConfig()
        self.queue = queue or JobQueue()
        self.output_dir = Path(output_dir) if output_dir else default_dir() / "clips"
        self.verify = verify
        self.max_attempts = max_attempts
        self.retry_steps = retry_steps
        self.min_detail = min_detail
        self.deadline = deadline
        self.window_start = window_start
        self.max_clips = max_clips
        self.max_consecutive_failures = max_consecutive_failures
        self.keep_awake = keep_awake
        self._ordinal = 0

    async def run(self, requests: Sequence[ClipRequest] | None = None) -> BatchReport:
        """Genera los clips pendientes hasta agotar la cola o cerrar la ventana.

        Args:
            requests: Clips nuevos que añadir a la cola (si los hay).

        Returns:
            El informe del lote.
        """
        report = BatchReport(
            id=datetime.now().strftime("%Y%m%d-%H%M%S"),
            config=self.config,
            window_start=self.window_start,
            window_end=self.deadline,
        )
        if requests:
            self.queue.extend(list(requests))
        self.queue.recover()
        context = power.keep_awake() if self.keep_awake else nullcontext(False)
        with context as despierto:
            if despierto:
                logger.info("Suspensión del equipo desactivada mientras dure el lote")
            await self._drain(report)
        report.finished_at = datetime.now()
        logger.info(
            f"Lote {report.id}: {len(report.done)}/{report.total} buenos · "
            f"{report.metrage:.1f} s · parada: {report.stopped_reason}"
        )
        return report

    async def _drain(self, report: BatchReport) -> None:
        """Genera clips hasta agotar la cola o cerrar la ventana."""
        consecutive_failures = 0
        while True:
            reason = self._stop_reason(report)
            if reason:
                report.stopped_reason = reason
                break
            request = self.queue.pending()[0]
            self._ordinal += 1
            await self._generate(request, self._ordinal)
            report.clips.append(request.model_copy(deep=True))
            if request.status == JobStatus.FAILED:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
            if consecutive_failures >= self.max_consecutive_failures:
                report.stopped_reason = (
                    f"{consecutive_failures} fallos seguidos: se aborta el lote"
                )
                break

    # -- decisiones del bucle ---------------------------------------------

    def _stop_reason(self, report: BatchReport) -> str | None:
        """Motivo por el que el lote no debe seguir (o ``None`` si sigue)."""
        if self.deadline is not None and datetime.now() >= self.deadline:
            return f"cerrada la ventana ({self.deadline:%H:%M})"
        if self.max_clips is not None and len(report.clips) >= self.max_clips:
            return f"alcanzado el máximo de {self.max_clips} intentos"
        pending = self.queue.pending()
        if not pending:
            return "cola vacía"
        if self.deadline is not None:
            remaining = (self.deadline - datetime.now()).total_seconds()
            needed = pending[0].config.estimated_seconds * (1.0 + WINDOW_MARGIN)
            if remaining < needed:
                return (
                    f"no cabe otro clip antes del cierre "
                    f"(quedan {remaining / 60:.0f} min y el clip tarda "
                    f"~{needed / 60:.0f} min)"
                )
        return None

    # -- generación de un clip --------------------------------------------

    async def _generate(self, request: ClipRequest, ordinal: int) -> None:
        """Genera, descarga y verifica un clip (actualizando la cola)."""
        config = request.config
        stem = f"{ordinal:03d}-{slugify(request.label or request.id)}-{request.id}"
        request.status = JobStatus.RUNNING
        request.attempts += 1
        self.queue.update(request)
        started = time.monotonic()
        logger.info(f"[{ordinal:03d}] Generando «{request.label}» · {config.describe()}")
        try:
            graph = build_graph(request, filename_prefix=f"genvideo/{request.id}/{stem}")
            prompt_id = await self.client.queue_prompt(graph)
            request.prompt_id = prompt_id
            entry = await self.client.wait(prompt_id, timeout=config.timeout_seconds)
            outputs = outputs_from(entry) or await self.client.outputs(prompt_id)
            videos = [item for item in outputs if item.is_video] or outputs
            if not videos:
                raise RuntimeError("el backend no devolvió ningún fichero")
            dest = self.output_dir / f"{stem}{videos[0].suffix or '.mp4'}"
            await self.client.download(videos[0], dest)
            request.seconds = time.monotonic() - started
            request.output = str(dest)
            if self.verify:
                request.quality = await verify_clip(
                    dest,
                    width=config.width,
                    height=config.height,
                    fps=config.fps,
                    frames=config.frames,
                    min_detail=self.min_detail,
                )
                if not request.quality.ok:
                    self._handle_bad_quality(request, ordinal)
                    return
            request.status = JobStatus.DONE
            request.error = None
            logger.info(
                f"[{ordinal:03d}] OK · {request.seconds / 60:.1f} min · {dest.name}"
            )
        except Exception as exc:  # noqa: BLE001 - un clip malo no debe tumbar el lote
            request.status = JobStatus.FAILED
            request.error = str(exc)[:500]
            request.seconds = request.seconds or (time.monotonic() - started)
            logger.error(f"[{ordinal:03d}] Falló «{request.label}»: {request.error}")
        self.queue.update(request)

    def _handle_bad_quality(self, request: ClipRequest, ordinal: int) -> None:
        """Decide si un clip que no pasa la verificación se reintenta o se tira."""
        reasons = "; ".join(request.quality.reasons if request.quality else [])
        request.error = f"verificación: {reasons}"
        can_retry = (
            request.attempts < self.max_attempts
            and request.config.steps < self.retry_steps
        )
        if can_retry:
            request.config.steps = min(self.retry_steps, request.config.steps * 2)
            request.status = JobStatus.PENDING
            request.prompt_id = None
            logger.warning(
                f"[{ordinal:03d}] Clip plano/oscuro ({reasons}) → "
                f"reintento con {request.config.steps} steps"
            )
        else:
            request.status = JobStatus.FAILED
            logger.error(f"[{ordinal:03d}] Clip descartado: {reasons}")


async def run_nightly(
    *,
    script: Script | None = None,
    prompts: Sequence[str] = (),
    topic: str | None = None,
    preset: Resolution = Resolution.HD,
    config: GenConfig | None = None,
    start: dt_time | None = None,
    end: dt_time | None = None,
    allow_wait: bool = False,
    max_clips: int | None = None,
    shots: int | None = None,
    output_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    state_path: str | Path | None = None,
    verify: bool = True,
    keep_awake: bool = True,
    stub: bool = False,
    stub_flat: bool = False,
    now: datetime | None = None,
) -> BatchReport:
    """Prepara y lanza un lote nocturno completo.

    Es el atajo que usa la CLI (y el scheduler): resuelve la configuración y la
    ventana, construye los clips desde el guion o los prompts, crea el cliente
    y ejecuta :class:`NightlyRunner`, dejando el informe escrito si se pide.

    Args:
        script: Guion del que sacar los clips.
        prompts: Prompts sueltos (si no hay guion).
        topic: Tema suelto: se genera un guion mínimo con él.
        preset: Preset medido.
        config: Configuración explícita (gana sobre el preset).
        start: Hora de inicio de la ventana.
        end: Hora de cierre de la ventana.
        allow_wait: Esperar a la hora de inicio si aún no ha llegado.
        max_clips: Máximo de clips a intentar en el lote.
        shots: Número de planos a generar.
        output_dir: Carpeta de los clips.
        report_dir: Carpeta del manifiesto y el resumen.
        state_path: Fichero de cola (por defecto, el del usuario).
        verify: Si se verifica cada clip.
        keep_awake: Desactivar la suspensión del equipo mientras dure el lote.
        stub: Usar el backend de pruebas (MP4 sintético, sin GPU).
        stub_flat: Con ``stub``, generar clips planos (para probar la verificación).
        now: Momento de referencia (para tests).

    Returns:
        El informe del lote.
    """
    settings = config or GenConfig.for_resolution(preset)
    if script is None and topic:
        script = script_from_topic(topic)
    if script is not None:
        requests = requests_from_script(script, config=settings, preset=preset, shots=shots)
    elif prompts:
        requests = requests_from_prompts(prompts, config=settings, preset=preset)
    else:
        requests = []

    window_start, deadline = resolve_window(start, end, now=now, allow_wait=allow_wait)
    if window_start is not None and allow_wait:
        wait_seconds = (window_start - datetime.now()).total_seconds()
        if wait_seconds > 0:
            logger.info(
                f"Esperando a la ventana de generación ({window_start:%H:%M}) · "
                f"{wait_seconds / 60:.0f} min"
            )
            await asyncio.sleep(wait_seconds)
    client: GenerationClient = (
        StubClient(
            flat=stub_flat,
            seconds=settings.clip_seconds,
            width=settings.width,
            height=settings.height,
            fps=settings.fps,
        )
        if stub
        else ComfyUIClient(settings.server_url)
    )
    queue = JobQueue(state_path) if state_path else JobQueue()
    runner = NightlyRunner(
        client=client,
        config=settings,
        queue=queue,
        output_dir=output_dir,
        verify=verify,
        keep_awake=keep_awake,
        deadline=deadline,
        window_start=window_start,
        max_clips=max_clips,
    )
    try:
        report = await runner.run(requests)
    finally:
        await client.aclose()
    if report_dir is not None:
        write_report(report, report_dir)
    return report
