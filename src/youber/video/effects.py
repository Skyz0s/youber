"""Efectos de vídeo del motor de edición de BARF.

Funciones que devuelven cadenas de filtros de FFmpeg listas para usar en un
``filter_complex``: velocidad, volumen, recorte, escalado, FPS y efectos
visuales (blanco y negro, sepia, viñeta, negar).
"""

from __future__ import annotations

from collections.abc import Iterable


def speed_video_filter(speed: float) -> str:
    """Filtro de velocidad para el stream de vídeo (``setpts``).

    Acelerar 2× es ``setpts=PTS/2``; ralentizar a la mitad es
    ``setpts=PTS*2``.
    """
    return f"setpts=PTS/{speed:.6f}"


def speed_audio_filter(speed: float) -> str:
    """Cadena ``atempo`` para el stream de audio.

    ``atempo`` solo admite 0.5-2.0 por instancia; para velocidades fuera de
    rango se encadenan varias instancias.
    """
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def volume_filter(volume: float) -> str:
    """Filtro de volumen del clip."""
    return f"volume={volume:.6f}"


def crop_filter(crop: tuple[int, int, int, int]) -> str:
    """Filtro de recorte ``crop=width:height:x:y``."""
    x, y, width, height = crop
    return f"crop={width}:{height}:{x}:{y}"


def scale_filter(width: int, height: int) -> str:
    """Escala al tamaño objetivo conservando la proporción y rellena a negro.

    Combina ``scale`` (ajuste proporcional) + ``pad`` (relleno centrado)
    para que todos los clips acaben en la resolución del proyecto.
    """
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def fps_filter(fps: int) -> str:
    """Fija la tasa de fotogramas del stream."""
    return f"fps={fps}"


def normalize_audio_filter() -> str:
    """Normaliza el audio a 48 kHz estéreo (requisito de ``acrossfade``)."""
    return "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def clip_video_filters(
    crop: tuple[int, int, int, int] | None,
    speed: float,
    width: int,
    height: int,
    fps: int,
) -> list[str]:
    """Filtros de vídeo para un clip: recorte, escala, FPS y velocidad."""
    filters = []
    if crop is not None:
        filters.append(crop_filter(crop))
    filters.append(scale_filter(width, height))
    filters.append(fps_filter(fps))
    if speed != 1.0:
        filters.append(speed_video_filter(speed))
    return filters


def clip_audio_filters(volume: float, speed: float) -> list[str]:
    """Filtros de audio para un clip: volumen y velocidad."""
    filters = [volume_filter(volume)]
    if speed != 1.0:
        filters.append(speed_audio_filter(speed))
    filters.append(normalize_audio_filter())
    return filters


def grayscale_filter() -> str:
    """Convierte el vídeo a blanco y negro."""
    return "hue=s=0"


def sepia_filter() -> str:
    """Aplica un tinte sepia clásico (matriz de colorchannelmixer)."""
    return (
        "colorchannelmixer="
        ".393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"
    )


def vignette_filter() -> str:
    """Aplica una viñeta oscura en los bordes."""
    return "vignette"


def negate_filter() -> str:
    """Invierte los colores (negativo fotográfico)."""
    return "negate"


def chain_filters(filters: Iterable[str]) -> str:
    """Une varios filtros en una cadena separada por comas."""
    return ",".join(filter for filter in filters if filter)
