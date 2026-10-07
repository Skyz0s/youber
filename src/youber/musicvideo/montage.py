"""Montaje guiado por el guion: de los huecos de :mod:`youber.musicvideo.shots`
a un vídeo montado.

El hueco manda: cada plano se recorta a **su** ventana y nada se recicla si no es
un motivo. Dos lecciones del primer videoclip van metidas en el diseño:

1. los cortes se cuentan en **frames exactos** (nada de ``-t 4.70385``: el
   redondeo a frames se acumulaba y el último corte se iba 250 ms del pulso);
2. los huecos que reutilizan un plano (``repeat_of``) **copian la fuente** del
   hueco original, así que el número de clips que hay que generar es
   :func:`youber.musicvideo.shots.distinct_count`.

El resultado son :class:`ShotSegment` (clip, frame de entrada, frames) y los
comandos de FFmpeg: recorte por segmento y concatenación con el audio.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import ensure_ffmpeg, run_command
from youber.musicvideo.models import MusicVideoError
from youber.musicvideo.shots import ShotSlot

#: Fotogramas por segundo del montaje (los clips del piloto son 24).
DEFAULT_FPS = 24

#: Calidad del recorte: CRF bajo para no añadir una generación visible.
DEFAULT_CRF = 18


@dataclass(frozen=True)
class ShotSegment:
    """Un tramo del montaje: de qué clip sale, desde qué frame y cuántos frames.

    Attributes:
        index: Posición en el montaje (0-based).
        slot_index: Hueco del que sale el clip (el propio, o el del motivo).
        clip: Fichero de vídeo de origen.
        source_frame: Frame del clip por el que empieza el tramo.
        frames: Frames que dura el tramo (siempre entero: sin deriva).
        start: Segundo de la canción en el que entra el tramo.
    """

    index: int
    slot_index: int
    clip: Path
    source_frame: int
    frames: int
    start: float

    @property
    def duration(self) -> float:
        """Duración del tramo (segundos), derivada de los frames."""
        return self.frames / DEFAULT_FPS

    @property
    def end(self) -> float:
        """Segundo de la canción en el que sale el tramo."""
        return self.start + self.duration


def resolve_origins(slots: Sequence[ShotSlot]) -> dict[int, int]:
    """Hueco del que sale el clip de cada hueco, con la **cadena** resuelta.

    El motivo puede encadenarse (el segundo estribillo reutiliza un plano del
    primero que, a su vez, reutiliza el de una línea repetida), así que se sigue
    el rastro hasta el hueco que **genera**.

    Returns:
        Un diccionario ``hueco -> hueco que genera su clip``.
    """
    by_index = {slot.index: slot for slot in slots}
    resolved: dict[int, int] = {}
    for slot in slots:
        origin = slot.index
        guard = 0
        while guard < len(slots):
            target = by_index[origin].repeat_of
            if target is None or target not in by_index or target == origin:
                break
            origin = target
            guard += 1
        resolved[slot.index] = origin
    return resolved


def boundary_frames(slots: Sequence[ShotSlot], *, fps: int = DEFAULT_FPS) -> list[int]:
    """Fronteras del montaje en frames (``len(slots) + 1`` valores).

    Cada frontera se redondea **absoluta** a un frame, así el error no se acumula:
    un corte puede caer medio frame antes o después del pulso, nunca 250 ms.

    Raises:
        MusicVideoError: si no hay huecos.
    """
    if not slots:
        raise MusicVideoError("Sin huecos no hay montaje")
    marks = [round(slot.start * fps) for slot in slots]
    marks.append(round(slots[-1].end * fps))
    return marks


def slot_segments(
    slots: Sequence[ShotSlot],
    clips: Mapping[int, Path],
    *,
    fps: int = DEFAULT_FPS,
    entry_frames: Mapping[int, int] | None = None,
) -> list[ShotSegment]:
    """Convierte los huecos en segmentos de montaje frame-exactos.

    Args:
        slots: Huecos de :func:`youber.musicvideo.shots.build_shot_slots`.
        clips: Clip (ruta) por **hueco que genera** (``repeat_of is None``). Los
            huecos de motivo reutilizan el clip del hueco original.
        fps: Fotogramas por segundo del montaje.
        entry_frames: Frame de entrada por clip (para que una fuente larga no
            entre siempre por el mismo sitio), opcional.

    Returns:
        Los segmentos en orden de montaje.

    Raises:
        MusicVideoError: si falta el clip de algún hueco que hay que generar.
    """
    marks = boundary_frames(slots, fps=fps)
    origins = resolve_origins(slots)
    segments: list[ShotSegment] = []
    for index, slot in enumerate(slots):
        origin = origins[slot.index]
        clip = clips.get(origin)
        if clip is None:
            raise MusicVideoError(
                f"Falta el clip del hueco {origin} (lo usa el hueco {slot.index})"
            )
        entry = 0
        if entry_frames is not None:
            entry = max(0, int(entry_frames.get(origin, 0)))
        segments.append(
            ShotSegment(
                index=index,
                slot_index=origin,
                clip=Path(clip),
                source_frame=entry,
                frames=max(1, marks[index + 1] - marks[index]),
                start=round(marks[index] / fps, 3),
            )
        )
    return segments


def total_frames(segments: Sequence[ShotSegment]) -> int:
    """Frames totales del montaje (lo que durará el vídeo, sin sorpresas)."""
    return sum(segment.frames for segment in segments)


def trim_command(
    segment: ShotSegment,
    output: str | Path,
    *,
    fps: int = DEFAULT_FPS,
    crf: int = DEFAULT_CRF,
    preset: str = "veryfast",
) -> list[str]:
    """Comando FFmpeg que recorta el tramo a un fichero intermedio.

    Se recorta con ``-frames:v`` (frames exactos), no con ``-t`` (segundos): es
    lo que evita la deriva que tenía el primer montaje.
    """
    return [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(segment.clip),
        "-ss",
        f"{segment.source_frame / fps:.6f}",
        "-frames:v",
        str(segment.frames),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-fps_mode",
        "cfr",
        str(output),
    ]


def concat_file_text(segments: Sequence[Path]) -> str:
    """Contenido del fichero de concatenación (un ``file`` por tramo)."""
    return "\n".join(f"file '{segment.as_posix()}'" for segment in segments) + "\n"


def mux_command(list_file: Path, audio: str | Path, output: str | Path, *, fps: int = DEFAULT_FPS) -> list[str]:
    """Comando FFmpeg que concatena los tramos y les pone la canción."""
    return [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output),
    ]


async def render_montage(
    segments: Sequence[ShotSegment],
    audio: str | Path,
    output: str | Path,
    *,
    work_dir: str | Path,
    fps: int = DEFAULT_FPS,
    crf: int = DEFAULT_CRF,
    preset: str = "veryfast",
) -> Path:
    """Monta los segmentos y les pone la canción (un solo pase de vídeo final).

    Los tramos se recortan a ``work_dir`` y se concatenan sin recodificar
    (``-c:v copy``): la pérdida de calidad es **una** generación, la del recorte.

    Args:
        segments: Segmentos de :func:`slot_segments`.
        audio: Canción.
        output: Vídeo de salida.
        work_dir: Carpeta de trabajo para los tramos recortados.
        fps: Fotogramas por segundo.
        crf: Calidad del recorte.
        preset: Ajuste de x264 para el recorte.

    Returns:
        La ruta del vídeo montado.
    """
    ensure_ffmpeg()
    if not segments:
        raise MusicVideoError("Sin segmentos no hay nada que montar")
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for segment in segments:
        part = work / f"seg{segment.index:03d}.mp4"
        part.unlink(missing_ok=True)
        await run_command(trim_command(segment, part, fps=fps, crf=crf, preset=preset))
        parts.append(part)
    list_file = work / "concat.txt"
    list_file.write_text(concat_file_text(parts), encoding="utf-8")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    await run_command(mux_command(list_file, audio, target, fps=fps))
    logger.info(
        f"Montaje: {len(segments)} planos, {total_frames(segments)} frames ({total_frames(segments) / fps:.1f} s)"
    )
    return target
