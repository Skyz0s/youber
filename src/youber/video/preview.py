"""Versiones ligeras (preview) de un vídeo renderizado.

Un montaje en 1080p pesa demasiado para compartirlo por mensajería, así que
se suele recodificar "a lo bruto": escala pequeña y **audio mono con bitrate
muy bajo** (p. ej. 48 kbps). Eso destroza la pista de música del vídeo
(artefactos metálicos, siseo, filtro paso-bajo agresivo).

Este módulo recodifica a propósito, pero con unos mínimos sensatos:

- vídeo escalado por altura (``scale=-2:height``), sin deformar,
- audio **estéreo** con bitrate suficiente (128 kbps por defecto),
- ``+faststart`` para que se pueda ver mientras se descarga.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import ensure_ffmpeg, run_command

#: Altura por defecto del preview (px). El ancho se calcula manteniendo
#: la relación de aspecto.
DEFAULT_PREVIEW_HEIGHT = 480

#: Calidad de vídeo por defecto (CRF de libx264; más alto = menos peso).
DEFAULT_PREVIEW_CRF = 33

#: Bitrate de audio por defecto del preview (estéreo).
#: 128 kbps estéreo es prácticamente transparente para música; por debajo de
#: ~96 kbps empiezan a aparecer artefactos audibles.
DEFAULT_PREVIEW_AUDIO_BITRATE = "128k"

#: Preset de libx264 para el preview.
DEFAULT_PREVIEW_PRESET = "medium"


def preview_path(source: str | Path) -> Path:
    """Ruta por defecto del preview de un vídeo (``<nombre>_preview.mp4``)."""
    src = Path(source)
    return src.with_name(f"{src.stem}_preview.mp4")


async def make_preview(
    source: str | Path,
    output: str | Path | None = None,
    *,
    height: int = DEFAULT_PREVIEW_HEIGHT,
    video_crf: int = DEFAULT_PREVIEW_CRF,
    audio_bitrate: str = DEFAULT_PREVIEW_AUDIO_BITRATE,
    preset: str = DEFAULT_PREVIEW_PRESET,
) -> str:
    """Genera una versión ligera de ``source`` para compartir por mensajería.

    Args:
        source: Vídeo de entrada (el render completo).
        output: Fichero de salida. Por defecto, ``<nombre>_preview.mp4``
            junto al original.
        height: Altura del preview en píxeles (el ancho se ajusta solo).
        video_crf: Calidad de vídeo (CRF; más alto = fichero más pequeño).
        audio_bitrate: Bitrate de audio estéreo (p. ej. ``"128k"``). Es el
            parámetro que decide si la música suena bien: no lo bajes de
            ``96k``.
        preset: Preset de ``libx264`` (``ultrafast``...``veryslow``).

    Returns:
        La ruta del preview generado.

    Raises:
        FileNotFoundError: si el vídeo de origen no existe.
        ValueError: si ``height`` o ``video_crf`` no son válidos.
        RuntimeError: si FFmpeg no está instalado o el comando falla.
    """
    if height <= 0:
        raise ValueError("La altura del preview debe ser mayor que 0")
    if video_crf < 0:
        raise ValueError("El CRF del preview no puede ser negativo")
    ensure_ffmpeg()
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(f"No existe el vídeo de origen: {src}")
    target = Path(output) if output is not None else preview_path(src)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        f"scale=-2:{height}",
        "-c:v",
        "libx264",
        "-crf",
        str(video_crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(target),
    ]
    logger.debug(f"make_preview: {' '.join(cmd)}")
    await run_command(cmd)
    logger.info(f"Preview generado → {target} ({height}p, audio {audio_bitrate})")
    return str(target)
