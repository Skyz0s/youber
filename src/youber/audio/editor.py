"""Edición de audio principal del módulo de audio de BARF.

Operaciones de alto nivel sobre vídeo/audio usando FFmpeg como backend:

- :func:`add_background_music` — añade música de fondo (de tu creación) a un vídeo.
- :func:`extract_audio` — extrae la pista de audio de un vídeo.
- :func:`replace_audio` — sustituye por completo el audio de un vídeo.

Ética: úsalo solo con **tu propia música** o contenido con licencia. No
añadas música con derechos a vídeos que no sean tuyos.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import probe_duration, run_command
from youber.audio.formats import (
    VIDEO_CODEC,
    audio_codec_for,
    validate_audio_input,
    validate_audio_output,
    validate_video_input,
)
from youber.audio.models import AudioConfig


def _filter_escape(value: float) -> str:
    """Formatea un número para usarlo dentro de un filtro de FFmpeg."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


async def add_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    **kwargs,
) -> str:
    """Añade música de fondo a un vídeo y guarda el resultado.

    Args:
        video_path: Ruta al vídeo original (MP4, MOV, AVI, MKV).
        music_path: Ruta a tu música (MP3, WAV, M4A, FLAC).
        output_path: Ruta donde guardar el resultado (MP4).
        **kwargs: Parámetros opcionales de :class:`AudioConfig`:
            ``volume`` (0.0-1.0, default 0.3), ``music_start`` (s, default 0),
            ``fade_in`` (s, default 2), ``fade_out`` (s, default 2),
            ``loop`` (bool, default True), ``original_audio_volume``
            (0.0-1.0, default 0.7).

    Returns:
        La ruta del vídeo resultante.

    Raises:
        ValueError: si los formatos no están soportados o la configuración
            es inválida.
        RuntimeError: si FFmpeg no está instalado o falla la operación.
    """
    video = validate_video_input(video_path)
    music = validate_audio_input(music_path)
    output = validate_video_output(output_path)
    config = AudioConfig(music_path=music, **kwargs)

    # Duración del vídeo: necesaria para loop/fade_out.
    video_duration = await probe_duration(video)

    music_filter = [
        f"volume={_filter_escape(config.volume)}",
    ]
    if config.music_start > 0:
        music_filter.append(
            f"adelay={int(config.music_start * 1000)}:all=1"
        )
    if config.fade_in > 0:
        music_filter.append(f"afade=t=in:st=0:d={_filter_escape(config.fade_in)}")
    if config.fade_out > 0:
        fade_out_start = max(0.0, video_duration - config.fade_out)
        music_filter.append(
            f"afade=t=out:st={_filter_escape(fade_out_start)}:d={_filter_escape(config.fade_out)}"
        )

    # Loop: repetir la música si es más corta que el vídeo.
    inputs = ["-i", str(video)]
    if config.loop:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
    else:
        inputs += ["-i", str(music)]

    filter_complex = (
        f"[1:a]{','.join(music_filter)}[bg];"
        f"[0:a]volume={_filter_escape(config.original_audio_volume)}[orig];"
        f"[orig][bg]amix=inputs=2:duration=first:dropout_transition=0[mix]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[mix]",
        "-c:v",
        "copy",
        "-c:a",
        VIDEO_CODEC,
        "-shortest",
        str(output),
    ]
    logger.debug(f"add_background_music: {' '.join(cmd)}")
    await run_command(cmd)
    logger.info(f"Música de fondo añadida → {output}")
    return str(output)


async def extract_audio(video_path: str, output_path: str) -> str:
    """Extrae el audio de un vídeo como fichero independiente.

    Args:
        video_path: Ruta al vídeo (MP4, MOV, AVI, MKV).
        output_path: Ruta de salida (MP3, WAV, M4A o FLAC).

    Returns:
        La ruta del audio extraído.
    """
    video = validate_video_input(video_path)
    output = validate_audio_output(output_path)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-c:a",
        audio_codec_for(output),
        str(output),
    ]
    await run_command(cmd)
    logger.info(f"Audio extraído → {output}")
    return str(output)


async def replace_audio(video_path: str, audio_path: str, output_path: str) -> str:
    """Reemplaza por completo el audio del vídeo por otro fichero de audio.

    Args:
        video_path: Ruta al vídeo original.
        audio_path: Ruta al audio que sustituirá a la pista original.
        output_path: Ruta del vídeo resultante (MP4).

    Returns:
        La ruta del vídeo con el audio reemplazado.
    """
    video = validate_video_input(video_path)
    audio = validate_audio_input(audio_path)
    output = validate_video_output(output_path)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "copy",
        "-c:a",
        VIDEO_CODEC,
        "-shortest",
        str(output),
    ]
    await run_command(cmd)
    logger.info(f"Audio reemplazado → {output}")
    return str(output)


def validate_video_output(path: str) -> Path:
    """Valida una salida de vídeo; lanza ``ValueError`` si no está soportada."""
    from youber.audio.formats import VIDEO_OUTPUT_EXTENSIONS

    target = Path(path)
    if target.suffix.lower() not in VIDEO_OUTPUT_EXTENSIONS:
        raise ValueError(
            f"Formato de salida de vídeo no soportado: {target.suffix or '(sin extensión)'}. "
            f"Soportados: {', '.join(sorted(VIDEO_OUTPUT_EXTENSIONS))}"
        )
    return target
