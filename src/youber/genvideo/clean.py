"""Lavado de un clip generado: quita el grano/partículas y el «latido» de luz.

El motor no devuelve el clip listo. La difusión deja **grano fino** (en
movimiento se ve como «cristal roto») y la decodificación del VAE por teselas
deja además un **latido lento** de exposición y contraste, que en un plano
quieto se nota como un parpadeo de la luz. Corregir eso se hacía a mano, fuera
del lote, con un script aparte; aquí vive como un paso más del lote: cada clip
verificado pasa por :func:`clean_clip` antes de darse por bueno.

La receta es la aprobada durante la producción de *Argumentos v2*:

1. ``hqdn3d`` + ``tmix`` → grano y partículas;
2. igualado temporal de histograma → el latido de exposición/contraste;
3. x264 crf 20 → listo para el montaje.

Todo el trabajo fino se hace sobre el plano **Y** (luminancia) y en Python
puro: el histograma de cada fotograma se saca con ``collections.Counter`` (una
sola pasada en C) y el igualado con ``bytes.translate``, así que no hace falta
arrastrar NumPy solo por este paso.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

from loguru import logger
from pydantic import BaseModel

from youber.audio._ffmpeg import ensure_ffmpeg
from youber.genvideo.verify import parse_fraction, probe_stream

#: Cadena de filtros del denoiser (la aprobada): primera el grano, después un
#: suavizado temporal corto que no emborrona el movimiento.
DENOISE_FILTER = "hqdn3d=2.5:2.5:14:14,tmix=frames=5:weights='0.08 0.16 0.52 0.16 0.08'"

#: Receta fuerte, aprobada el 2026-10-22 con el 5B a 720p/193 fotogramas: el
#: grano de la difusión **crece a lo largo del plano** (hf_luma 1,4 al principio
#: y 2,1 en la cola con :data:`DENOISE_FILTER`), así que en la segunda mitad del
#: plano la receta normal se queda corta y se sigue viendo «nevar». Medido en el
#: plano 001 de *Everything is breaking down*: la cola baja de 1,78 a **1,24**
#: conservando el 97,7 % de la estructura.
DENOISE_STRONG = (
    "hqdn3d=12:9:24:24,"
    "tmix=frames=9:weights='0.04 0.06 0.1 0.15 0.3 0.15 0.1 0.06 0.04'"
)

#: Ajustes de salida: lo que se le pasó al montaje en la producción real.
CRF = 20
ENCODE_PRESET = "medium"

#: Si el lavado mueve el nivel medio más que esto, algo ha salido mal (se usa
#: como comprobación de cordura, igual que en la receta original).
MAX_LEVEL_SHIFT = 3.0

#: Por debajo de este nivel el fotograma es prácticamente negro.
MIN_LEVEL = 20.0

#: Puntos de la tabla de cuantiles (256 = una por nivel de gris).
LUT_POINTS = 256

#: Percentil con el que se separan los «blancos» (destellos, ventana, nieve).
WHITES_PERCENTILE = 0.90

_PROBS: tuple[float, ...] = tuple(index / (LUT_POINTS - 1) for index in range(LUT_POINTS))

class CleanReport(BaseModel):
    """Resultado del lavado de un clip (métricas de antes y de después)."""

    source: str
    output: str
    seconds: float
    frames: int
    pulse_before: float
    pulse_after: float
    whites_before: float
    whites_after: float
    level_before: float
    level_after: float
    denoise: str = DENOISE_FILTER
    crf: int = CRF
    equalized: bool = True
    ok: bool = True

    @property
    def summary(self) -> str:
        """Resumen corto para logs e informes."""
        return (
            f"latido {self.pulse_before:.2f}->{self.pulse_after:.2f} · "
            f"blancos {self.whites_before:.2f}->{self.whites_after:.2f} · "
            f"nivel {self.level_before:.1f}->{self.level_after:.1f}"
        )


def histogram(plane: bytes) -> list[int]:
    """Histograma de 256 cubetas de un plano en gris (una pasada, en C)."""
    counts = Counter(plane)
    return [counts.get(value, 0) for value in range(256)]


def total_pixels(histograms: list[list[int]]) -> int:
    """Píxeles contados en total (suma de todos los histogramas)."""
    return sum(sum(hist) for hist in histograms)


def sum_histograms(histograms: list[list[int]]) -> list[int]:
    """Histograma acumulado de un clip entero (fotograma a fotograma)."""
    accumulated = [0] * 256
    for hist in histograms:
        for value, count in enumerate(hist):
            accumulated[value] += count
    return accumulated


def percentile_threshold(hist: list[int], fraction: float) -> int:
    """Nivel de gris donde el histograma alcanza ``fraction`` de su masa."""
    total = sum(hist)
    if total <= 0:
        return 0
    target = fraction * total
    cumulative = 0
    for value, count in enumerate(hist):
        cumulative += count
        if cumulative >= target:
            return value
    return 255


def frame_means(histograms: list[list[int]]) -> list[float]:
    """Nivel medio de cada fotograma (a partir de su histograma)."""
    means: list[float] = []
    for hist in histograms:
        total = sum(hist)
        if total <= 0:
            means.append(0.0)
            continue
        means.append(sum(value * count for value, count in enumerate(hist)) / total)
    return means


def frame_whites(histograms: list[list[int]], threshold: int) -> list[float]:
    """Nivel medio de los «blancos» de cada fotograma (píxeles ≥ umbral)."""
    values: list[float] = []
    for hist in histograms:
        count = sum(hist[threshold:])
        if count <= 0:
            values.append(0.0)
            continue
        values.append(sum(value * hist[value] for value in range(threshold, 256)) / count)
    return values


def pulse(histograms: list[list[int]]) -> tuple[float, float, float]:
    """Latido del clip: ``(latido de luz, latido de blancos, nivel medio)``.

    El «latido» es cuánto baila el nivel medio (y el de los blancos) entre el
    fotograma más claro y el más oscuro. Un clip estable da casi 0.
    """
    if not histograms:
        return 0.0, 0.0, 0.0
    threshold = percentile_threshold(sum_histograms(histograms), WHITES_PERCENTILE)
    means = frame_means(histograms)
    whites = frame_whites(histograms, threshold)
    pulse_luma = max(means) - min(means)
    pulse_whites = max(whites) - min(whites)
    level = sum(means) / len(means)
    return pulse_luma, pulse_whites, level


def cumulative(hist: list[int]) -> list[float]:
    """Función de distribución acumulada, normalizada a ``[0, 1]``."""
    total = sum(hist)
    if total <= 0:
        return [0.0] * 256
    accumulated = 0
    cdf = [0.0] * 256
    for value, count in enumerate(hist):
        accumulated += count
        cdf[value] = accumulated / total
    return cdf


def _interp(x: float, xs: tuple[float, ...], ys: list[float]) -> float:
    """Interpolación lineal en ``xs`` (creciente) — el ``np.interp`` de bolsillo."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    low, high = 0, len(xs) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if xs[middle] <= x:
            low = middle
        else:
            high = middle
    span = xs[high] - xs[low]
    if span <= 0:
        return ys[high]
    weight = (x - xs[low]) / span
    return ys[low] * (1.0 - weight) + ys[high] * weight


def inverse_cdf(reference: list[int]) -> list[float]:
    """Inversa de la CDF de referencia: el nivel para cada cuantil (0..255)."""
    cdf = cumulative(reference)
    return [_interp(prob, tuple(cdf), [float(value) for value in range(256)]) for prob in _PROBS]


def match_table(frame_hist: list[int], inverse: list[float]) -> bytes:
    """Tabla de traducción de 256 bytes que lleva este fotograma a la referencia.

    Es un igualado de histograma clásico: cada nivel del fotograma se reescribe
    al nivel que ocupa **el mismo cuantil** en la referencia. Como la referencia
    es la media del clip, lo que se va es el latido: todos los fotogramas acaban
    con la misma distribución.
    """
    cdf = cumulative(frame_hist)
    table = bytearray(256)
    for value in range(256):
        mapped = _interp(cdf[value], _PROBS, inverse)
        table[value] = max(0, min(255, round(mapped)))
    return bytes(table)


def _read_exactly(handle: IO[bytes], size: int) -> bytes:
    """Lee exactamente ``size`` bytes (o menos si el flujo se acaba)."""
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = handle.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _frames_from_stream(handle: IO[bytes], frame_bytes: int) -> Iterator[bytes]:
    """Recorre un flujo rawvideo fotograma a fotograma."""
    while True:
        frame = _read_exactly(handle, frame_bytes)
        if len(frame) < frame_bytes:
            break
        yield frame


def _run(args: list[str], *, stdout: int | None = None) -> subprocess.Popen[bytes]:
    """Lanza FFmpeg sin shell (con la salida donde se pida)."""
    return subprocess.Popen(args, stdout=stdout, stderr=subprocess.DEVNULL)


async def _gray_histograms(source: Path, plane: int) -> tuple[list[list[int]], int]:
    """Histogramas del plano Y del clip tal cual (medición de «antes»)."""

    def worker() -> tuple[list[list[int]], int]:
        process = _run([
            "ffmpeg", "-v", "error", "-i", str(source), "-pix_fmt", "gray",
            "-f", "rawvideo", "-",
        ], stdout=subprocess.PIPE)
        assert process.stdout is not None  # noqa: S101 - stdout pedido a FFmpeg
        histograms: list[list[int]] = []
        for plane_bytes in _frames_from_stream(process.stdout, plane):
            histograms.append(histogram(plane_bytes))
        process.stdout.close()
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg falló leyendo el clip ({process.returncode})")
        return histograms, len(histograms)

    return await asyncio.to_thread(worker)


async def _denoised_histograms(source: Path, plane: int, denoise: str, temp: Path) -> list[list[int]]:
    """Aplica el denoiser y devuelve los histogramas de Y del resultado."""

    def worker() -> list[list[int]]:
        raw = temp / "denoised.raw"
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(source), "-vf", denoise,
            "-pix_fmt", "yuv444p", "-f", "rawvideo", str(raw),
        ], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg falló en el denoiser: {result.stderr[-300:]}")
        histograms: list[list[int]] = []
        with raw.open("rb") as handle:
            for frame in _frames_from_stream(handle, plane * 3):
                histograms.append(histogram(frame[:plane]))
        return histograms

    return await asyncio.to_thread(worker)


async def _equalize(
    temp: Path, plane: int, inverse: list[float]
) -> tuple[list[list[int]], int]:
    """Reescribe los fotogramas con el LUT de cada uno y devuelve sus histogramas."""

    def worker() -> tuple[list[list[int]], int]:
        raw = temp / "denoised.raw"
        out = temp / "equalized.raw"
        after: list[list[int]] = []
        with raw.open("rb") as src, out.open("wb") as dst:
            for frame in _frames_from_stream(src, plane * 3):
                luma = frame[:plane]
                table = match_table(histogram(luma), inverse)
                washed = luma.translate(table)
                after.append(histogram(washed))
                dst.write(washed)
                dst.write(frame[plane:])
        return after, len(after)

    return await asyncio.to_thread(worker)


async def _passthrough(temp: Path, plane: int) -> tuple[list[list[int]], int]:
    """Copia los fotogramas ya desruidados sin tocar el nivel.

    Es el camino de ``equalize=False``: se salta el igualado de histograma (el
    que corrige el «latido» de exposición) porque en planos con mucho grano
    estira el contraste y realza lo que queda de ruido.
    """

    def worker() -> tuple[list[list[int]], int]:
        raw = temp / "denoised.raw"
        out = temp / "equalized.raw"
        histograms: list[list[int]] = []
        with raw.open("rb") as src, out.open("wb") as dst:
            for frame in _frames_from_stream(src, plane * 3):
                histograms.append(histogram(frame[:plane]))
                dst.write(frame)
        return histograms, len(histograms)

    return await asyncio.to_thread(worker)


async def _encode(temp: Path, target: Path, width: int, height: int, fps: float, crf: int, preset: str) -> None:
    """Codifica el raw igualado a H.264 (yuv420p, faststart) en ``target``."""

    def worker() -> None:
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "yuv444p", "-s", f"{width}x{height}",
            "-r", f"{fps:g}", "-i", str(temp / "equalized.raw"),
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
        ], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg falló codificando: {result.stderr[-300:]}")

    await asyncio.to_thread(worker)


async def clean_clip(
    source: str | Path,
    target: str | Path | None = None,
    *,
    denoise: str = DENOISE_FILTER,
    crf: int = CRF,
    preset: str = ENCODE_PRESET,
    equalize: bool = True,
    max_level_shift: float = MAX_LEVEL_SHIFT,
) -> CleanReport:
    """Lava un clip (grano + latido) dejándolo en ``target``.

    Args:
        source: Clip de entrada (el que sale del motor).
        target: Clip de salida. Si falta, se escribe junto al original con el
            sufijo ``_lavado``.
        denoise: Cadena de filtros del denoiser.
        crf: Calidad de x264 (menor = mejor).
        preset: Preset de x264.
        equalize: Igualar el histograma de cada fotograma contra el del clip
            (quita el «latido» de exposición). Con ``False`` solo se desruida.
        max_level_shift: Cuánto puede moverse el nivel medio sin dar el clip por
            sospechoso (se marca en ``ok``, no se tira nada).

    Returns:
        El informe con las métricas de antes y de después.

    Raises:
        FileNotFoundError: si el clip de entrada no existe.
        RuntimeError: si FFmpeg no está o falla, o el clip no se puede leer.
    """
    origin = Path(source)
    if not origin.exists():
        raise FileNotFoundError(f"No existe el clip: {origin}")
    destination = Path(target) if target else origin.with_name(f"{origin.stem}_lavado{origin.suffix}")
    if destination.resolve() == origin.resolve():
        raise ValueError("el lavado necesita una ruta de salida distinta de la de entrada")
    ensure_ffmpeg()
    started = time.monotonic()
    stream = await probe_stream(origin)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    fps = parse_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate")) or 24.0
    if width <= 0 or height <= 0:
        raise RuntimeError(f"No pude leer el tamaño de {origin}")
    plane = width * height

    before, frame_count = await _gray_histograms(origin, plane)
    if frame_count == 0:
        raise RuntimeError(f"El clip no tiene fotogramas legibles: {origin}")
    with tempfile.TemporaryDirectory(prefix="youber-lavado-") as folder:
        temp = Path(folder)
        denoised = await _denoised_histograms(origin, plane, denoise, temp)
        if not denoised:
            raise RuntimeError(f"El denoiser no devolvió fotogramas: {origin}")
        if equalize:
            inverse = inverse_cdf(sum_histograms(denoised))
            after, _ = await _equalize(temp, plane, inverse)
        else:
            after, _ = await _passthrough(temp, plane)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await _encode(temp, destination, width, height, fps, crf, preset)

    pulse_before, whites_before, level_before = pulse(before)
    pulse_after, whites_after, level_after = pulse(after)
    report = CleanReport(
        source=str(origin),
        output=str(destination),
        seconds=round(time.monotonic() - started, 1),
        frames=frame_count,
        pulse_before=pulse_before,
        pulse_after=pulse_after,
        whites_before=whites_before,
        whites_after=whites_after,
        level_before=level_before,
        level_after=level_after,
        denoise=denoise,
        crf=crf,
        equalized=equalize,
        ok=abs(level_after - level_before) < max_level_shift and level_after >= MIN_LEVEL,
    )
    logger.info(f"Lavado {destination.name}: {report.summary} ({report.seconds:.0f}s)")
    return report


def clean_clip_sync(source: str | Path, target: str | Path | None = None, **kwargs: Any) -> CleanReport:
    """:func:`clean_clip` en versión síncrona (para scripts y CLI)."""
    return asyncio.run(clean_clip(source, target, **kwargs))


def replace(source: Path, target: Path) -> None:
    """Mueve ``source`` sobre ``target`` (atómico donde el sistema lo permita)."""
    os.replace(str(source), str(target))
