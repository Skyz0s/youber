"""Efectos de audio del módulo de audio de BARF (fade, volumen, mezcla).

Funciones asíncronas que operan sobre ficheros de audio usando FFmpeg:

- :func:`apply_fade` — fundido de entrada/salida (fade in/out).
- :func:`adjust_volume` — ajusta el volumen de una pista.
- :func:`mix_audios` — mezcla dos pistas con un ratio configurable.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import probe_duration, run_command
from youber.audio.formats import audio_codec_for, validate_audio_input, validate_audio_output

FADE_TYPES = ("in", "out", "both")


def _suffix_for(path: Path, tag: str) -> Path:
    """Genera un nombre de salida automático: ``nombre_tag.ext``."""
    return path.with_name(f"{path.stem}_{tag}{path.suffix}")


async def apply_fade(audio_path: str, duration: float, fade_type: str = "in") -> str:
    """Aplica un fundido (fade) de audio y guarda junto al original.

    Args:
        audio_path: Ruta al fichero de audio (MP3, WAV, M4A, FLAC).
        duration: Duración del fundido en segundos.
        fade_type: ``"in"``, ``"out"`` o ``"both"``.

    Returns:
        La ruta del fichero con el fade aplicado (``nombre_fadein.ext``,
        ``nombre_fadeout.ext`` o ``nombre_fadeboth.ext``).

    Raises:
        ValueError: si el tipo de fade no es válido o la duración es negativa.
    """
    if fade_type not in FADE_TYPES:
        raise ValueError(f"fade_type debe ser uno de {FADE_TYPES}: {fade_type!r}")
    if duration < 0:
        raise ValueError("duration no puede ser negativa")

    audio = validate_audio_input(audio_path)
    output = _suffix_for(audio, f"fade{fade_type}")

    filters: list[str] = []
    if fade_type in ("in", "both"):
        filters.append(f"afade=t=in:st=0:d={duration:.3f}")
    if fade_type in ("out", "both"):
        total = await probe_duration(audio)
        start = max(0.0, total - duration)
        filters.append(f"afade=t=out:st={start:.3f}:d={duration:.3f}")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio),
        "-af",
        ",".join(filters),
        "-c:a",
        audio_codec_for(output),
        str(output),
    ]
    await run_command(cmd)
    logger.info(f"Fade {fade_type} aplicado → {output}")
    return str(output)


async def adjust_volume(audio_path: str, volume: float, output_path: str) -> str:
    """Ajusta el volumen de un fichero de audio.

    Args:
        audio_path: Ruta al fichero de audio.
        volume: Factor de volumen entre 0.0 y 2.0 (1.0 = original).
        output_path: Ruta del fichero resultante.

    Returns:
        La ruta del fichero con el volumen ajustado.

    Raises:
        ValueError: si el volumen está fuera del rango [0.0, 2.0].
    """
    if not 0.0 <= volume <= 2.0:
        raise ValueError(f"volume debe estar entre 0.0 y 2.0 (recibido: {volume})")

    audio = validate_audio_input(audio_path)
    output = validate_audio_output(output_path)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio),
        "-af",
        f"volume={volume:.3f}",
        "-c:a",
        audio_codec_for(output),
        str(output),
    ]
    await run_command(cmd)
    logger.info(f"Volumen ajustado a {volume} → {output}")
    return str(output)


async def mix_audios(
    audio1_path: str,
    audio2_path: str,
    output_path: str,
    ratio: float = 0.5,
) -> str:
    """Mezcla dos pistas de audio en una sola.

    Args:
        audio1_path: Primera pista (base).
        audio2_path: Segunda pista.
        output_path: Ruta del fichero mezclado.
        ratio: Peso de la primera pista (0.5 = mitad y mitad; 1.0 = solo
            la primera; 0.0 = solo la segunda).

    Returns:
        La ruta del fichero mezclado.

    Raises:
        ValueError: si el ratio está fuera del rango [0.0, 1.0].
    """
    if not 0.0 <= ratio <= 1.0:
        raise ValueError(f"ratio debe estar entre 0.0 y 1.0 (recibido: {ratio})")

    audio1 = validate_audio_input(audio1_path)
    audio2 = validate_audio_input(audio2_path)
    output = validate_audio_output(output_path)

    filter_complex = (
        f"[0:a]volume={ratio:.3f}[a];"
        f"[1:a]volume={1 - ratio:.3f}[b];"
        f"[a][b]amix=inputs=2:duration=longest[mix]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio1),
        "-i",
        str(audio2),
        "-filter_complex",
        filter_complex,
        "-map",
        "[mix]",
        "-c:a",
        audio_codec_for(output),
        str(output),
    ]
    await run_command(cmd)
    logger.info(f"Mezcla de audios (ratio {ratio}) → {output}")
    return str(output)
