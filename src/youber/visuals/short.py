"""Corta un **Short** de una canción: el trozo con más energía (el estribillo).

YouTube Shorts admite hasta 3 minutos, pero el formato vive del gancho: un
corte de 45-90 s con la parte más reconocible de la canción funciona mucho
mejor que un fragmento cualquiera. Aquí el trozo se elige **midiendo**, no a
ojo: se decodifica la canción a PCM mono, se calcula la energía (RMS) por
ventana y se busca la ventana de ``duration`` segundos con más energía
acumulada. Es determinista y no depende de metadatos de la canción.
"""

from __future__ import annotations

import array
import math
import tempfile
from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import ensure_ffmpeg, run_command

#: Duración por defecto del corte vertical (segundos).
DEFAULT_SHORT_DURATION = 75.0

#: Frecuencia de muestreo del análisis (basta para medir energía).
ANALYSIS_SAMPLE_RATE = 8000

#: Ventana del análisis de energía (segundos).
ANALYSIS_WINDOW = 1.0

#: Bitrate del audio del Short (estéreo AAC).
SHORT_AUDIO_BITRATE = "192k"


def window_energies(samples: array.array, *, sample_rate: int, window: float) -> list[float]:
    """Energía RMS por ventana de ``window`` segundos.

    Args:
        samples: Muestras PCM mono de 16 bits con signo.
        sample_rate: Frecuencia de muestreo de ``samples``.
        window: Tamaño de ventana en segundos.

    Returns:
        Una energía por ventana (la última puede ser más corta).
    """
    size = max(1, int(round(sample_rate * window)))
    energies: list[float] = []
    for start in range(0, len(samples), size):
        chunk = samples[start : start + size]
        if not chunk:
            continue
        total = 0.0
        for value in chunk:
            total += float(value) * float(value)
        energies.append(math.sqrt(total / len(chunk)))
    return energies


def best_window_start(
    energies: list[float], duration: float, *, window: float = ANALYSIS_WINDOW
) -> float:
    """Inicio (segundos) de la ventana de ``duration`` s con más energía.

    Si la pista es más corta que ``duration``, devuelve 0.0.

    Args:
        energies: Energía por ventana (:func:`window_energies`).
        duration: Duración deseada del corte (segundos).
        window: Duración de cada ventana de energía (segundos).

    Returns:
        El segundo en el que empieza el mejor corte.
    """
    span = max(1, int(round(duration / window)))
    if span >= len(energies):
        return 0.0
    current = sum(energies[:span])
    best_sum = current
    best_index = 0
    for index in range(1, len(energies) - span + 1):
        current += energies[index + span - 1] - energies[index - 1]
        if current > best_sum:
            best_sum = current
            best_index = index
    return best_index * window


async def loudness_profile(
    song: str | Path,
    *,
    window: float = ANALYSIS_WINDOW,
    sample_rate: int = ANALYSIS_SAMPLE_RATE,
) -> list[float]:
    """Perfil de energía de una canción (RMS por ventana).

    Decodifica a PCM mono 16 bits con FFmpeg en un fichero temporal y calcula
    la energía en Python: sin dependencias extra y reproducible.

    Args:
        song: Fichero de audio.
        window: Tamaño de ventana en segundos.
        sample_rate: Frecuencia de muestreo del análisis.

    Returns:
        La energía por ventana.

    Raises:
        FileNotFoundError: si el fichero no existe.
        RuntimeError: si FFmpeg falla.
    """
    ensure_ffmpeg()
    source = Path(song)
    if not source.exists():
        raise FileNotFoundError(f"No existe la canción: {source}")
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "audio.pcm"
        await run_command(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "s16le",
                str(raw),
            ]
        )
        samples = array.array("h")
        samples.frombytes(raw.read_bytes())
    if samples.itemsize != 2:  # pragma: no cover - depende de la plataforma
        raise RuntimeError("Se esperaban muestras de 16 bits del análisis de audio")
    return window_energies(samples, sample_rate=sample_rate, window=window)


async def pick_window(
    song: str | Path, duration: float = DEFAULT_SHORT_DURATION
) -> tuple[float, float]:
    """Elige el mejor corte de ``duration`` segundos de una canción.

    Returns:
        ``(inicio, duración)`` en segundos.

    Raises:
        ValueError: si ``duration`` no es positiva.
    """
    if duration <= 0:
        raise ValueError("La duración del corte debe ser mayor que 0")
    energies = await loudness_profile(song)
    start = best_window_start(energies, duration)
    logger.info(f"Ventana elegida: {start:.1f} s (+{duration:.1f} s) sobre {len(energies)} ventanas")
    return start, duration


async def extract_window(
    song: str | Path,
    output: str | Path,
    *,
    start: float,
    duration: float,
    fade_in: float = 0.8,
    fade_out: float = 2.0,
) -> Path:
    """Recorta un fragmento de la canción (con fundidos) a AAC estéreo.

    Args:
        song: Canción de origen.
        output: Fichero de salida (``.m4a`` o ``.aac``).
        start: Segundo en el que empieza el corte.
        duration: Duración del corte en segundos.
        fade_in: Fundido de entrada (segundos).
        fade_out: Fundido de salida (segundos).

    Returns:
        La ruta del fragmento generado.
    """
    ensure_ffmpeg()
    source = Path(song)
    if not source.exists():
        raise FileNotFoundError(f"No existe la canción: {source}")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    filters = []
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:g}")
    if fade_out > 0:
        filters.append(f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:g}")
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        f"{max(0.0, start):.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
    ]
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        SHORT_AUDIO_BITRATE,
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(target),
    ]
    logger.debug(f"extract_window: {' '.join(cmd)}")
    await run_command(cmd)
    logger.info(f"Corte del Short → {target} ({start:.1f} s + {duration:.1f} s)")
    return target
