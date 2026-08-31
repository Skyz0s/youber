"""Línea de tiempo del motor de edición de vídeo de BARF.

Expande un :class:`~youber.video.models.Project` en segmentos ordenados con
duraciones calculadas (teniendo en cuenta ``start``, ``duration`` y
``speed``) y valida las transiciones entre clips.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from youber.audio._ffmpeg import probe_duration, run_command
from youber.video.models import Project, Transition, TransitionType


class TimelineSegment(BaseModel):
    """Un segmento de la línea de tiempo (un clip ya expandido)."""

    index: int
    file_path: Path
    source_start: float
    source_duration: float  # duración en tiempo de fuente (antes de speed)
    output_duration: float  # duración en el resultado (después de speed)
    speed: float = 1.0
    volume: float = 1.0
    crop: tuple[int, int, int, int] | None = None
    has_audio: bool = True


class Timeline(BaseModel):
    """Línea de tiempo completa: segmentos + transiciones + metadatos."""

    segments: list[TimelineSegment] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    total_duration: float = 0.0
    resolution: tuple[int, int] = (1920, 1080)
    fps: int = 30

    @classmethod
    async def build(cls, project: Project) -> Timeline:
        """Construye la línea de tiempo a partir del proyecto.

        Para clips sin ``duration`` explícita se consulta la duración real
        del fichero con ``ffprobe`` (operación asíncrona).
        """
        segments: list[TimelineSegment] = []
        for index, clip in enumerate(project.clips):
            if clip.duration is not None:
                output_duration = clip.duration
                source_duration = output_duration * clip.speed
            else:
                full = await probe_duration(clip.file_path)
                source_duration = max(0.0, full - clip.start)
                output_duration = source_duration / clip.speed
            segments.append(
                TimelineSegment(
                    index=index,
                    file_path=clip.file_path,
                    source_start=clip.start,
                    source_duration=source_duration,
                    output_duration=output_duration,
                    speed=clip.speed,
                    volume=clip.volume,
                    crop=clip.crop,
                    has_audio=await _has_audio_stream(clip.file_path),
                )
            )

        transitions = _validated_transitions(project)
        total = _total_duration(segments, transitions)
        return cls(
            segments=segments,
            transitions=transitions,
            total_duration=total,
            resolution=project.resolution,
            fps=project.fps,
        )


def _validated_transitions(project: Project) -> list[Transition]:
    """Devuelve las transiciones ordenadas y con índices válidos.

    Descarta transiciones con ``clip_index`` fuera de rango y ordena por
    índice; las de tipo ``NONE`` se conservan (el renderer las trata como
    concatenación directa).
    """
    valid = [
        transition
        for transition in project.transitions
        if 1 <= transition.clip_index < max(1, len(project.clips))
    ]
    return sorted(valid, key=lambda transition: transition.clip_index)


def _total_duration(segments: list[TimelineSegment], transitions: list[Transition]) -> float:
    """Duración total: suma de clips menos los solapamientos de transiciones."""
    total = sum(segment.output_duration for segment in segments)
    for transition in transitions:
        if transition.type != TransitionType.NONE:
            total -= transition.duration
    return max(0.0, total)


async def _has_audio_stream(path: Path) -> bool:
    """Comprueba con ffprobe si el fichero tiene pista de audio."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        result = await run_command(cmd)
    except RuntimeError:
        return False
    return bool((result.stdout or "").strip())


def segment_for_transition(timeline: Timeline, clip_index: int) -> tuple[int, int]:
    """Devuelve ``(origen, destino)`` para una transición que termina en ``clip_index``."""
    return (clip_index - 1, clip_index)
