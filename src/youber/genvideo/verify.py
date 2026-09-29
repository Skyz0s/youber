"""Verificación de los clips generados: que ninguno cuele plano u oscuro.

Generar no garantiza nada. El spike lo dejó claro: con la LoRA Turbo a **4
steps y 720p** el clip se genera «bien» (ComfyUI dice ``success``) pero la
imagen sale **plana y oscura**; no es opinión, el detalle del fotograma medido
caía a 9-21 frente a ~40-54 con 8 steps. Por eso cada clip pasa por aquí antes
de darse por bueno:

1. ``ffprobe``: duración, resolución, fps y número de fotogramas;
2. ``ffmpeg``: brillo medio y **detalle** de un fotograma central (desviación
   típica en escala de grises) y **movimiento** (diferencia media entre el 20 %
   y el 80 % del clip, que caza los clips congelados);
3. :func:`judge_quality`: umbrales medidos → ``ok`` con motivos legibles.

El runner usa el veredicto para **reintentar con más steps** en vez de dejar
pasar basura.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from youber.audio._ffmpeg import ensure_ffmpeg, run_command
from youber.genvideo.models import ClipQuality

#: Detalle mínimo del fotograma (desviación típica en gris). Con Turbo a 4
#: steps a 720p la medición dio 9-21; con 8 steps, ~40-54.
MIN_DETAIL = 25.0

#: Brillo medio aceptable (0-255): ni casi negro ni quemado.
MIN_BRIGHTNESS = 15.0
MAX_BRIGHTNESS = 240.0

#: Movimiento mínimo entre el 20 % y el 80 % del clip (diferencia media).
MIN_MOTION = 1.0

#: Puntos del clip donde se toman las muestras de movimiento.
MOTION_START = 0.2
MOTION_END = 0.8


async def _run_binary(args: list[str]) -> bytes:
    """Ejecuta un binario y devuelve su salida binaria (para leer fotogramas)."""
    result = await asyncio.to_thread(subprocess.run, args, capture_output=True)
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"FFmpeg falló ({result.returncode}): {stderr}")
    return result.stdout


def parse_fraction(value: str | None) -> float:
    """Convierte ``"24/1"`` en ``24.0`` (los fps de ffprobe vienen así)."""
    if not value:
        return 0.0
    if "/" in value:
        numerator, _, denominator = value.partition("/")
        try:
            divisor = float(denominator)
            return float(numerator) / divisor if divisor else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


async def probe_stream(path: str | Path) -> dict[str, Any]:
    """Propiedades del flujo de vídeo (primer stream) según ``ffprobe``."""
    result = await run_command([
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration",
        "-of",
        "json",
        str(path),
    ])
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:  # pragma: no cover - salida inesperada
        raise RuntimeError(f"ffprobe devolvió algo ilegible para {path}") from exc
    streams = data.get("streams") or []
    return streams[0] if streams else {}


async def gray_frame(path: str | Path, at: float) -> array.array:
    """Un fotograma en escala de grises (8 bits) en el segundo ``at``.

    El ``-ss`` va **después** del ``-i`` a propósito: con búsqueda rápida ambos
    fotogramas pueden caer en el mismo keyframe y el «movimiento» daría 0 en un
    clip que sí se mueve. El fotograma se reduce a 320 px de ancho: para medir
    brillo y detalle sobra, y así la medición no cuesta más que la generación.
    """
    data = await _run_binary([
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-ss",
        f"{at:.3f}",
        "-vf",
        "scale=320:-2",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ])
    samples = array.array("B")
    samples.frombytes(data)
    return samples


def stats_of(samples: array.array) -> tuple[float, float]:
    """Media y desviación típica de un fotograma en gris (brillo y detalle)."""
    if not samples:
        return 0.0, 0.0
    mean = sum(samples) / len(samples)
    variance = sum((float(value) - mean) ** 2 for value in samples) / len(samples)
    return mean, math.sqrt(variance)


async def frame_stats(path: str | Path, at: float) -> tuple[float, float]:
    """Brillo medio y detalle del fotograma del segundo ``at``."""
    return stats_of(await gray_frame(path, at))


async def frame_delta(path: str | Path, first: float, second: float) -> float:
    """Diferencia media entre dos fotogramas del clip (movimiento)."""
    before = await gray_frame(path, first)
    after = await gray_frame(path, second)
    if not before or len(before) != len(after):
        return 0.0
    total = sum(abs(int(a) - int(b)) for a, b in zip(before, after, strict=True))
    return total / len(before)


def judge_quality(
    quality: ClipQuality,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: float | None = None,
    frames: int | None = None,
    min_detail: float = MIN_DETAIL,
    min_motion: float = MIN_MOTION,
) -> ClipQuality:
    """Aplica los umbrales a unas métricas y devuelve el veredicto.

    Es una función **pura** (no toca FFmpeg) para poder testear los umbrales
    sin generar vídeo.

    Args:
        quality: Métricas medidas.
        width: Ancho esperado (si se indica, se compara).
        height: Alto esperado.
        fps: Fotogramas por segundo esperados (tolerancia de 0,5).
        frames: Fotogramas esperados (tolerancia del 10 %).
        min_detail: Detalle mínimo aceptable.
        min_motion: Movimiento mínimo aceptable.

    Returns:
        Una copia de ``quality`` con ``ok`` y ``reasons`` resueltos.
    """
    reasons: list[str] = []
    if quality.frames <= 0 or quality.duration <= 0:
        reasons.append("el clip está vacío (0 frames o 0 s)")
    if width is not None and quality.width and quality.width != width:
        reasons.append(f"ancho {quality.width} ≠ {width}")
    if height is not None and quality.height and quality.height != height:
        reasons.append(f"alto {quality.height} ≠ {height}")
    if fps is not None and quality.fps and abs(quality.fps - fps) > 0.5:
        reasons.append(f"fps {quality.fps:.2f} ≠ {fps:g}")
    if frames is not None and quality.frames and abs(quality.frames - frames) > max(2, frames // 10):
        reasons.append(f"frames {quality.frames} ≠ {frames}")
    if quality.detail is not None and quality.detail < min_detail:
        reasons.append(
            f"detalle bajo ({quality.detail:.1f} < {min_detail:g}): imagen plana"
        )
    if quality.brightness is not None and not MIN_BRIGHTNESS <= quality.brightness <= MAX_BRIGHTNESS:
        reasons.append(f"brillo fuera de rango ({quality.brightness:.1f})")
    if quality.motion is not None and quality.motion < min_motion:
        reasons.append(f"sin movimiento ({quality.motion:.2f} < {min_motion:g})")
    return quality.model_copy(update={"ok": not reasons, "reasons": reasons})


async def verify_clip(
    path: str | Path,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: float | None = None,
    frames: int | None = None,
    min_detail: float = MIN_DETAIL,
    min_motion: float = MIN_MOTION,
) -> ClipQuality:
    """Mide un clip y decide si sirve.

    Args:
        path: Fichero de vídeo.
        width: Ancho esperado.
        height: Alto esperado.
        fps: Fotogramas por segundo esperados.
        frames: Fotogramas esperados.
        min_detail: Detalle mínimo aceptable.
        min_motion: Movimiento mínimo aceptable.

    Returns:
        Las métricas con el veredicto (``ok`` y ``reasons``).

    Raises:
        FileNotFoundError: si el clip no existe.
        RuntimeError: si FFmpeg no está instalado o falla.
    """
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"No existe el clip: {source}")
    ensure_ffmpeg()
    stream = await probe_stream(source)
    duration = float(stream.get("duration") or 0.0)
    frame_count = int(stream.get("nb_frames") or 0)
    fps_measured = parse_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    if fps_measured <= 0 and frame_count and duration > 0:
        fps_measured = frame_count / duration
    quality = ClipQuality(
        duration=duration,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        fps=fps_measured,
        frames=frame_count,
    )
    if duration <= 0:
        return judge_quality(quality, width=width, height=height, fps=fps, frames=frames)
    brightness, detail = await frame_stats(source, duration / 2)
    motion = await frame_delta(
        source, duration * MOTION_START, duration * MOTION_END
    )
    quality.brightness = brightness
    quality.detail = detail
    quality.motion = motion
    return judge_quality(
        quality,
        width=width,
        height=height,
        fps=fps,
        frames=frames,
        min_detail=min_detail,
        min_motion=min_motion,
    )
