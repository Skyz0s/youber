"""Anima un still con movimiento de cámara (efecto Ken Burns).

El still se escala un poco por encima del tamaño de entrega
(:data:`OVERSCAN`) y el filtro ``zoompan`` de FFmpeg hace el paneo o el zoom
sobre ese margen. Así el movimiento nunca deja ver bordes vacíos y no hace
falta escalar la imagen 2x (que multiplica el coste del filtro).

Los clips salen **sin pista de audio**: el renderer del motor de vídeo
(:mod:`youber.video.renderer`) inserta silencio donde falte, y la banda
sonora va aparte.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import ensure_ffmpeg, run_command
from youber.visuals.models import Motion

#: Margen de imagen sobre el tamaño de entrega (para que el paneo tenga recorrido).
OVERSCAN = 1.3

#: Zoom fijo de los movimientos de paneo/inclinación.
PAN_ZOOM = 1.25

#: Zoom del plano estático (un pelín de zoom evita el look de foto pegada).
STATIC_ZOOM = 1.04

#: Calidad por defecto de los clips intermedios (CRF de libx264).
DEFAULT_CRF = 18

#: Preset por defecto de libx264 para los clips intermedios.
DEFAULT_PRESET = "medium"


def motion_expressions(
    motion: Motion, frames: int, *, cycle_frames: int | None = None
) -> tuple[str, str, str]:
    """Expresiones ``(zoom, x, y)`` del filtro ``zoompan`` para un movimiento.

    Args:
        motion: Movimiento a aplicar.
        frames: Número de fotogramas del clip (define la velocidad).
        cycle_frames: Fotogramas que dura un ciclo **completo** del movimiento
            (ida y vuelta). Si se indica (el pulso de la canción lo dicta), el
            movimiento es **periódico**: recorre su recorrido y vuelve, con el
            pico a mitad de ciclo, así respira al compás en vez de completar un
            único barrido a lo largo del plano. ``None`` (sin pulso) mantiene
            el barrido monótono de siempre.

    Returns:
        La terna de expresiones que consume ``zoompan``.
    """
    frames = max(1, frames)
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    zoom_step = (OVERSCAN - 1.0) / frames
    if cycle_frames is not None:
        # Onda triangular: 0 → 1 → 0 dentro del ciclo (pico a mitad de ciclo).
        cycle = max(1, int(round(cycle_frames)))
        position = f"(mod(on,{cycle})/{cycle})"
        triangle = f"min(2*{position},2-2*{position})"
        amplitude = OVERSCAN - 1.0
        if motion is Motion.ZOOM_IN:
            return f"1+{amplitude:.6f}*{triangle}", center_x, center_y
        if motion is Motion.ZOOM_OUT:
            return f"{OVERSCAN}-{amplitude:.6f}*{triangle}", center_x, center_y
        if motion is Motion.PAN_LEFT:
            return f"{PAN_ZOOM}", f"(iw-iw/zoom)*(1-{triangle})", center_y
        if motion is Motion.PAN_RIGHT:
            return f"{PAN_ZOOM}", f"(iw-iw/zoom)*{triangle}", center_y
        if motion is Motion.TILT_UP:
            return f"{PAN_ZOOM}", center_x, f"(ih-ih/zoom)*(1-{triangle})"
        if motion is Motion.TILT_DOWN:
            return f"{PAN_ZOOM}", center_x, f"(ih-ih/zoom)*{triangle}"
        return f"{STATIC_ZOOM}", center_x, center_y
    if motion is Motion.ZOOM_IN:
        return f"min(1+{zoom_step:.6f}*on,{OVERSCAN})", center_x, center_y
    if motion is Motion.ZOOM_OUT:
        return f"max({OVERSCAN}-{zoom_step:.6f}*on,1.0)", center_x, center_y
    if motion is Motion.PAN_LEFT:
        return f"{PAN_ZOOM}", f"(iw-iw/zoom)*(1-on/{frames})", center_y
    if motion is Motion.PAN_RIGHT:
        return f"{PAN_ZOOM}", f"(iw-iw/zoom)*(on/{frames})", center_y
    if motion is Motion.TILT_UP:
        return f"{PAN_ZOOM}", center_x, f"(ih-ih/zoom)*(1-on/{frames})"
    if motion is Motion.TILT_DOWN:
        return f"{PAN_ZOOM}", center_x, f"(ih-ih/zoom)*(on/{frames})"
    return f"{STATIC_ZOOM}", center_x, center_y


def _even(value: float) -> int:
    """Redondea al entero par más cercano (lo exige ``libx264``/``zoompan``)."""
    rounded = int(round(value))
    return rounded if rounded % 2 == 0 else rounded + 1


def animate_filter(
    motion: Motion,
    *,
    duration: float,
    size: tuple[int, int],
    fps: int,
    motion_period: float | None = None,
) -> str:
    """Cadena de filtros FFmpeg que anima el still (sin entrada de audio).

    Args:
        motion: Movimiento de cámara.
        duration: Duración del clip (segundos).
        size: Tamaño de entrega ``(ancho, alto)``.
        fps: Fotogramas por segundo.
        motion_period: Segundos que dura un ciclo de movimiento (compases
            medidos); ``None`` para un único barrido a lo largo del clip.
    """
    width, height = size
    frames = max(2, int(round(duration * fps)))
    cycle_frames = max(2, int(round(motion_period * fps))) if motion_period else None
    zoom, x, y = motion_expressions(motion, frames, cycle_frames=cycle_frames)
    over_w, over_h = _even(width * OVERSCAN), _even(height * OVERSCAN)
    return (
        f"scale={over_w}:{over_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={over_w}:{over_h},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
        "format=yuv420p"
    )


async def animate_shot(
    image: str | Path,
    output: str | Path,
    *,
    duration: float,
    motion: Motion = Motion.ZOOM_IN,
    size: tuple[int, int] = (1920, 1080),
    fps: int = 30,
    motion_period: float | None = None,
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
) -> Path:
    """Convierte un still en un clip de vídeo con movimiento de cámara.

    Args:
        image: Imagen de entrada (PNG/JPG).
        output: Fichero MP4 de salida (sin audio).
        duration: Duración del clip en segundos.
        motion: Movimiento de cámara a aplicar.
        size: Tamaño de entrega ``(ancho, alto)``.
        fps: Fotogramas por segundo.
        motion_period: Segundos que dura un ciclo del movimiento (un número
            entero de compases, si se midió el pulso de la canción).
        crf: Calidad de ``libx264`` (más alto = menos peso).
        preset: Preset de ``libx264``.

    Returns:
        La ruta del clip generado.

    Raises:
        FileNotFoundError: si la imagen no existe.
        RuntimeError: si FFmpeg falla o no está instalado.
    """
    ensure_ffmpeg()
    source = Path(image)
    if not source.exists():
        raise FileNotFoundError(f"No existe la imagen del plano: {source}")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    filters = animate_filter(
        motion, duration=duration, size=size, fps=fps, motion_period=motion_period
    )
    frames = max(2, int(round(duration * fps)))
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-loop",
        "1",
        "-i",
        str(source),
        "-vf",
        filters,
        "-frames:v",
        str(frames),
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(target),
    ]
    logger.debug(f"animate_shot: {' '.join(cmd)}")
    await run_command(cmd)
    logger.debug(f"Plano animado → {target}")
    return target
