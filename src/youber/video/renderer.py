"""Renderizado de proyectos de vídeo con FFmpeg (motor de BARF).

Construye el comando completo de FFmpeg a partir de un
:class:`~youber.video.models.Project` y su :class:`~youber.video.timeline.Timeline`:

- cada clip se recorta (``trim``), escala y normaliza (FPS, formato),
- los clips se encadenan con transiciones (``xfade``/``acrossfade`` o ``concat``),
- se dibujan los textos e imágenes superpuestas,
- opcionalmente se mezcla la música del catálogo (``amix`` con fades).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import run_command
from youber.video.effects import chain_filters, clip_audio_filters, clip_video_filters
from youber.video.models import Project
from youber.video.overlays import image_overlay_filter, text_overlay_filter
from youber.video.timeline import Timeline
from youber.video.transitions import audio_transition_chain, video_transition_chain

VIDEO_CODECS = {"mp4": "libx264", "mkv": "libx264"}
AUDIO_CODECS = {"mp4": "aac", "mkv": "aac"}


def _validate_output(output_path: str, output_format: str) -> Path:
    target = Path(output_path)
    if output_format not in VIDEO_CODECS:
        raise ValueError(f"Formato de salida no soportado: {output_format!r} (usa mp4 o mkv)")
    if target.suffix.lower() not in {".mp4", ".mkv"}:
        raise ValueError(f"Extensión de salida no soportada: {target.suffix or '(sin extensión)'}")
    return target


async def render_project(
    project: Project,
    output_path: str,
    music_path: str | None = None,
) -> str:
    """Renderiza el proyecto a un fichero de vídeo con FFmpeg.

    Args:
        project: Proyecto a renderizar (clips, transiciones, overlays...).
        output_path: Ruta del vídeo de salida (``.mp4`` o ``.mkv``).
        music_path: Ruta a un fichero de música (opcional; si el proyecto
            tiene ``music_track_id`` y no se pasa ruta, se ignora la música).

    Returns:
        La ruta del vídeo renderizado.

    Raises:
        ValueError: si el proyecto no tiene clips o el formato no es válido.
        RuntimeError: si FFmpeg falla.
    """
    output = _validate_output(output_path, project.output_format)
    timeline = await Timeline.build(project)
    if not timeline.segments:
        raise ValueError("El proyecto no tiene clips para renderizar")

    width, height = timeline.resolution
    fps = timeline.fps

    # -- Entradas -----------------------------------------------------------
    # Los clips se buclean (-stream_loop -1) para que un clip corto de stock
    # rellene toda la duración de su escena; el trim posterior corta el tramo
    # exacto. La música también se buclea (ya lo hacía).
    inputs: list[str] = []
    for segment in timeline.segments:
        inputs += ["-stream_loop", "-1", "-i", str(segment.file_path)]
    for overlay in project.image_overlays:
        inputs += ["-i", str(overlay.image_path)]

    music_input_index: int | None = None
    if music_path:
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        music_input_index = len(timeline.segments) + len(project.image_overlays)

    # -- Filtros por clip ---------------------------------------------------
    parts: list[str] = []
    for index, segment in enumerate(timeline.segments):
        video_filters = clip_video_filters(
            segment.crop, segment.speed, width, height, fps
        )
        video_chain = chain_filters(
            [
                f"trim=start={segment.source_start:.3f}:duration={segment.source_duration:.3f}",
                "setpts=PTS-STARTPTS",
                *video_filters,
                "format=yuv420p",
                "settb=AVTB",
            ]
        )
        parts.append(f"[{index}:v]{video_chain}[v{index}]")

        if segment.has_audio:
            audio_chain = chain_filters(
                [
                    f"atrim=start={segment.source_start:.3f}:duration={segment.source_duration:.3f}",
                    "asetpts=PTS-STARTPTS",
                    *clip_audio_filters(segment.volume, segment.speed),
                ]
            )
            parts.append(f"[{index}:a]{audio_chain}[a{index}]")
        else:
            # Clip sin audio: generamos silencio con anullsrc.
            parts.append(
                f"anullsrc=r=48000:cl=stereo,"
                f"atrim=0:{segment.output_duration:.3f},asetpts=PTS-STARTPTS[a{index}]"
            )

    # -- Transiciones -------------------------------------------------------
    video_chain, video_label = video_transition_chain(timeline)
    audio_chain, audio_label = audio_transition_chain(timeline)
    if video_chain:
        parts.append(video_chain)
    if audio_chain:
        parts.append(audio_chain)

    # -- Overlays de texto e imágenes ---------------------------------------
    for index, text_overlay in enumerate(project.text_overlays):
        next_label = f"vt{index}"
        parts.append(
            f"[{video_label}]{text_overlay_filter(text_overlay, timeline.total_duration)}[{next_label}]"
        )
        video_label = next_label

    for index, image_overlay in enumerate(project.image_overlays):
        next_label = f"vi{index}"
        parts.append(
            image_overlay_filter(
                image_overlay,
                video_label,
                next_label,
                timeline.total_duration,
                len(timeline.segments) + index,
            )
        )
        video_label = next_label

    # -- Música de fondo ----------------------------------------------------
    if music_input_index is not None:
        total = timeline.total_duration
        fade_out_start = max(0.0, total - 2.0)
        parts.append(
            f"[{music_input_index}:a]"
            f"volume={project.music_volume:.3f},"
            f"afade=t=in:st=0:d=2,"
            f"afade=t=out:st={fade_out_start:.3f}:d=2,"
            f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS[mbg]"
        )
        parts.append(
            f"[{audio_label}][mbg]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        audio_label = "aout"

    # -- Comando final ------------------------------------------------------
    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(parts),
        "-map",
        f"[{video_label}]",
        "-map",
        f"[{audio_label}]",
        "-c:v",
        VIDEO_CODECS[project.output_format],
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        AUDIO_CODECS[project.output_format],
        "-shortest",
        str(output),
    ]
    logger.debug(f"render_project: {' '.join(cmd)}")
    await run_command(cmd)
    logger.info(f"Vídeo renderizado → {output}")
    return str(output)
