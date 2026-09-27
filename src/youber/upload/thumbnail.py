"""Miniaturas (thumbnails) para YouTube.

La miniatura es lo que decide el clic, así que no se coge un fotograma
cualquiera: se **mide** el audio del vídeo (energía RMS por ventana, igual
que en :mod:`youber.visuals.short`) y se elige el instante con más energía
(el estribillo), evitando los fundidos de entrada y salida. Opcionalmente se
rotula el título encima con el mismo lenguaje visual de los subtítulos
(blanco con contorno negro).

Todo se genera en local con FFmpeg (1280×720, JPEG); la subida a YouTube la
hace :meth:`youber.upload.youtube.YouTubeUploader.set_thumbnail`.

Solo se sube contenido propio: la miniatura se construye a partir de tu
propio vídeo.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from youber.audio._ffmpeg import (
    decode_mono_pcm,
    ensure_ffmpeg,
    probe_duration,
    run_command,
)
from youber.visuals.short import ANALYSIS_SAMPLE_RATE, ANALYSIS_WINDOW, window_energies

#: Resolución de la miniatura (la que recomienda YouTube: 16:9, 1280×720).
THUMB_WIDTH = 1280
THUMB_HEIGHT = 720

#: Calidad JPEG del fotograma (``-q:v``; 2 = muy alta).
THUMB_QUALITY = 2

#: Fracción inicial/final del vídeo que se descarta al buscar el fotograma
#: (los fundidos de entrada/salida suelen estar ahí y no representan el vídeo).
EDGE_MARGIN = 0.1

#: Ancho máximo (en caracteres) de cada línea del título rotulado.
DEFAULT_TEXT_WIDTH = 22

#: Tamaño de fuente por defecto del título, relativo a la altura de la miniatura.
FONT_SIZE_RATIO = 0.085


class ThumbnailResult(BaseModel):
    """Resultado de generar una miniatura.

    Attributes:
        path: Ruta del JPEG generado.
        timestamp: Segundo del vídeo del que se extrajo el fotograma.
        text: Título rotulado (vacío si la miniatura va limpia).
        resolution: ``(ancho, alto)`` de la miniatura.
    """

    path: Path
    timestamp: float
    text: str = ""
    resolution: tuple[int, int] = (THUMB_WIDTH, THUMB_HEIGHT)


# ---------------------------------------------------------------------------
# Selección del fotograma (puro, testeable sin FFmpeg)
# ---------------------------------------------------------------------------


def pick_thumbnail_time(
    energies: Sequence[float],
    duration: float,
    *,
    window: float = ANALYSIS_WINDOW,
    margin: float = EDGE_MARGIN,
) -> float:
    """Instante (segundos) con más energía dentro de la zona útil del vídeo.

    Descarta el ``margin`` inicial y final (fundidos) y devuelve el centro de
    la ventana con más energía. Si no hay medidas, cae al ``margin`` del
    principio.

    Args:
        energies: Energía por ventana (:func:`youber.visuals.short.window_energies`).
        duration: Duración del vídeo en segundos.
        window: Duración de cada ventana de energía (segundos).
        margin: Fracción inicial/final descartada (0..0.5).

    Returns:
        El segundo del fotograma elegido.
    """
    if not energies or duration <= 0:
        return max(0.0, duration * margin)

    start_index = int(len(energies) * margin)
    end_index = max(start_index + 1, int(len(energies) * (1.0 - margin)))
    end_index = min(end_index, len(energies))

    best_index = start_index
    best_energy = energies[start_index]
    for index in range(start_index, end_index):
        if energies[index] > best_energy:
            best_energy = energies[index]
            best_index = index
    return min(best_index * window, max(0.0, duration - window))


async def thumbnail_profile(
    video: str | Path,
    *,
    window: float = ANALYSIS_WINDOW,
    sample_rate: int = ANALYSIS_SAMPLE_RATE,
) -> list[float]:
    """Perfil de energía (RMS por ventana) del audio de un vídeo.

    Args:
        video: Fichero de vídeo (su pista de audio se analiza).
        window: Tamaño de ventana en segundos.
        sample_rate: Frecuencia de muestreo del análisis (Hz).

    Returns:
        Una energía por ventana.

    Raises:
        FileNotFoundError: si el vídeo no existe.
        RuntimeError: si FFmpeg falla o el vídeo no tiene audio.
    """
    samples = await decode_mono_pcm(video, sample_rate=sample_rate)
    return window_energies(samples, sample_rate=sample_rate, window=window)


# ---------------------------------------------------------------------------
# Construcción con FFmpeg
# ---------------------------------------------------------------------------


def wrap_text(text: str, width: int = DEFAULT_TEXT_WIDTH) -> list[str]:
    """Parte el título en líneas de como mucho ``width`` caracteres.

    Respeta las palabras; una palabra más larga que ``width`` ocupa su línea.
    """
    clean = " ".join(text.split())
    if not clean:
        return []
    lines: list[str] = []
    current = ""
    for word in clean.split(" "):
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _escape_drawtext(text: str) -> str:
    """Escapa un texto para el filtro ``drawtext`` de FFmpeg."""
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("%", "\\%")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def default_font_file() -> str | None:
    """Fuente del sistema para ``drawtext`` (necesaria en Windows), o ``None``.

    En Windows FFmpeg no usa fontconfig, así que hay que darle la ruta del
    ``.ttf``. En Linux/macOS devuelve ``None`` y FFmpeg resuelve por nombre.
    """
    if sys.platform != "win32":
        return None
    fonts = Path("C:/Windows/Fonts")
    for name in ("arialbd.ttf", "arial.ttf", "segoeuib.ttf", "segoeui.ttf"):
        candidate = fonts / name
        if candidate.is_file():
            return str(candidate)
    return None


def thumbnail_filter(
    *,
    size: tuple[int, int] = (THUMB_WIDTH, THUMB_HEIGHT),
    lines: Sequence[str] = (),
    font_file: str | None = None,
    font_size: int | None = None,
) -> str:
    """Cadena de filtros de FFmpeg (recorte 16:9 + título rotulado opcional).

    El fotograma se escala para cubrir el lienzo 16:9 y se recorta, de modo
    que ninguna miniatura salga deformada. Si hay ``lines``, se dibujan
    centradas abajo, en blanco con contorno negro (legibles sobre cualquier
    fondo), una línea por filtro ``drawtext``.

    Args:
        size: ``(ancho, alto)`` de salida.
        lines: Líneas del título (ya envueltas con :func:`wrap_text`).
        font_file: Ruta de la fuente (``None`` = FFmpeg decide).
        font_size: Tamaño en píxeles (por defecto, proporcional a la altura).

    Returns:
        La cadena de ``-vf`` lista para FFmpeg.
    """
    width, height = size
    parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
    ]
    if not lines:
        return ",".join(parts)

    active_size = font_size or max(12, round(height * FONT_SIZE_RATIO))
    line_height = round(active_size * 1.15)
    margin_bottom = round(height * 0.06)
    last_y = height - margin_bottom - active_size
    first_y = last_y - line_height * (len(lines) - 1)

    for index, line in enumerate(lines):
        y = first_y + line_height * index
        draw = [
            f"text='{_escape_drawtext(line)}'",
            f"fontsize={active_size}",
            "fontcolor=white",
            "borderw=4",
            "bordercolor=black@0.85",
            "x=(w-text_w)/2",
            f"y={y}",
        ]
        if font_file:
            draw.append(f"fontfile='{font_file.replace(chr(92), '/').replace(':', chr(92) + ':')}'")
        parts.append("drawtext=" + ":".join(draw))
    return ",".join(parts)


async def make_thumbnail(
    video: str | Path,
    output: str | Path | None = None,
    *,
    timestamp: float | None = None,
    text: str | None = None,
    size: tuple[int, int] = (THUMB_WIDTH, THUMB_HEIGHT),
    font_file: str | None = None,
    font_size: int | None = None,
    text_width: int = DEFAULT_TEXT_WIDTH,
    profile: Sequence[float] | None = None,
) -> ThumbnailResult:
    """Genera una miniatura del vídeo (fotograma + título rotulado opcional).

    Args:
        video: Vídeo de origen.
        output: Ruta del JPEG (default: ``<vídeo>_thumb.jpg``).
        timestamp: Segundo concreto del fotograma. Si es ``None``, se elige el
            instante con más energía del audio (el estribillo).
        text: Título a rotular (``None`` o vacío = miniatura limpia).
        size: ``(ancho, alto)`` de la miniatura.
        font_file: Fuente para el texto (por defecto, la del sistema).
        font_size: Tamaño del texto en píxeles.
        text_width: Ancho máximo del título en caracteres por línea.
        profile: Perfil de energía ya medido (evita re-decodificar el audio).

    Returns:
        :class:`ThumbnailResult` con la ruta, el instante y el texto.

    Raises:
        FileNotFoundError: si el vídeo no existe.
        RuntimeError: si FFmpeg falta o el render falla.
    """
    source = Path(video)
    if not source.is_file():
        raise FileNotFoundError(f"Vídeo no encontrado: {source}")
    ensure_ffmpeg()

    duration = await probe_duration(source)
    if timestamp is None:
        energies = list(profile) if profile is not None else await thumbnail_profile(source)
        timestamp = pick_thumbnail_time(energies, duration)
    timestamp = max(0.0, min(float(timestamp), max(0.0, duration - 0.05)))

    lines = wrap_text(text, text_width) if text else []
    output_path = Path(output) if output else source.with_name(f"{source.stem}_thumb.jpg")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    font = font_file if font_file is not None else default_font_file()
    vf = thumbnail_filter(
        size=size, lines=lines, font_file=font, font_size=font_size
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{timestamp:.3f}",
        "-i", str(source),
        "-frames:v", "1",
        "-vf", vf,
        "-q:v", str(THUMB_QUALITY),
        str(output_path),
    ]
    await run_command(cmd)
    logger.info(
        f"Miniatura generada en {timestamp:.2f} s → {output_path.name}"
        + (f" (título: {text!r})" if text else "")
    )
    return ThumbnailResult(
        path=output_path,
        timestamp=timestamp,
        text=text or "",
        resolution=size,
    )


def thumbnail_available() -> bool:
    """Indica si FFmpeg está disponible para generar miniaturas."""
    return shutil.which("ffmpeg") is not None
