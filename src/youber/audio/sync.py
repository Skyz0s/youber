"""Sincronización audio-vídeo del módulo de audio de BARF.

Utilidades para alinear pistas usando FFmpeg:

- :func:`detect_silence` — localiza los silencios de una pista (útil para
  encontrar dónde empieza el sonido real).
- :func:`align_audio_to_video` — alinea un audio a un vídeo comparando el
  inicio del primer sonido de cada pista.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import run_command
from youber.audio.editor import extract_audio
from youber.audio.formats import VIDEO_CODEC, validate_audio_input, validate_video_input

_SILENCE_RE = re.compile(r"silence_(start|end): ([\d.]+)")


async def detect_silence(audio_path: str, threshold: float = -40) -> list[dict]:
    """Detecta los silencios de una pista de audio.

    Args:
        audio_path: Ruta al fichero de audio.
        threshold: Umbral en dB por debajo del cual se considera silencio
            (por defecto -40 dB).

    Returns:
        Lista de silencios: ``[{"start": s, "end": e, "duration": d}, ...]``.
        Si no hay silencios, devuelve una lista vacía.
    """
    audio = validate_audio_input(audio_path)

    cmd = [
        "ffmpeg",
        "-i",
        str(audio),
        "-af",
        f"silencedetect=n={threshold}dB:d=0.3",
        "-f",
        "null",
        "-",
    ]
    result = await run_command(cmd)

    # FFmpeg escribe la detección en stderr: silence_start / silence_end.
    events: list[tuple[str, float]] = []
    for match in _SILENCE_RE.finditer(result.stderr or ""):
        events.append((match.group(1), round(float(match.group(2)), 3)))

    silences: list[dict] = []
    for kind, timestamp in events:
        if kind == "start":
            silences.append({"start": timestamp, "end": None, "duration": None})
        elif silences and silences[-1]["end"] is None:
            silences[-1]["end"] = timestamp
            silences[-1]["duration"] = round(timestamp - silences[-1]["start"], 3)

    logger.debug(f"detect_silence: {len(silences)} silencio(s) en {audio}")
    return silences


async def _first_sound_offset(audio_path: str) -> float:
    """Devuelve el instante (segundos) en que empieza el primer sonido.

    Si la pista empieza con silencio, es el final del primer silencio;
    si no, es 0.
    """
    silences = await detect_silence(audio_path)
    if silences and silences[0]["start"] is not None and silences[0]["start"] < 0.05:
        return float(silences[0]["end"] or 0.0)
    return 0.0


async def _video_first_sound(video_path: str) -> float:
    """Primer sonido del audio contenido en un vídeo (extrayéndolo a WAV)."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = str(Path(tmp) / "video_audio.wav")
        await extract_audio(video_path, wav)
        return await _first_sound_offset(wav)


async def align_audio_to_video(video_path: str, audio_path: str, output_path: str) -> str:
    """Alinea un audio a un vídeo usando la detección del primer sonido.

    Calcula el desfase entre el inicio del sonido real del vídeo y el del
    audio, y desplaza el audio (adelantándolo o retrasándolo) para que
    ambos empiecen a la vez. Es una alineación por onset, adecuada para
    pistas cuyo comienzo está limpio (sin ruido de fondo prolongado).

    Args:
        video_path: Ruta al vídeo de referencia.
        audio_path: Ruta al audio que se quiere alinear.
        output_path: Ruta del vídeo resultante (MP4).

    Returns:
        La ruta del vídeo con el audio alineado.
    """
    video = validate_video_input(video_path)
    audio = validate_audio_input(audio_path)

    video_offset = await _video_first_sound(str(video))
    audio_offset = await _first_sound_offset(str(audio))
    delta = video_offset - audio_offset  # >0: el audio empieza antes

    logger.debug(
        f"align_audio_to_video: vídeo {video_offset:.2f}s, audio {audio_offset:.2f}s, Δ={delta:.2f}s"
    )

    # Desplazamiento: adelantar (atrim) o retrasar (adelay) el audio.
    if delta > 0:
        audio_filter = f"atrim=start={delta:.3f},asetpts=PTS-STARTPTS"
    elif delta < 0:
        audio_filter = f"adelay={int(abs(delta) * 1000)}:all=1"
    else:
        audio_filter = "anull"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-filter_complex",
        f"[1:a]{audio_filter}[aligned]",
        "-map",
        "0:v",
        "-map",
        "[aligned]",
        "-c:v",
        "copy",
        "-c:a",
        VIDEO_CODEC,
        "-shortest",
        str(output_path),
    ]
    await run_command(cmd)
    logger.info(f"Audio alineado al vídeo → {output_path}")
    return str(output_path)
