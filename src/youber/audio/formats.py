"""Formatos de audio/vídeo soportados por el módulo de edición.

Define qué extensiones acepta el módulo (entradas y salidas) y el mapeo a
códecs de FFmpeg. Centralizar esto evita comandos inválidos y da errores
claros al usuario.
"""

from __future__ import annotations

from pathlib import Path

# Entradas: contenedores de vídeo y de audio.
VIDEO_INPUT_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
AUDIO_INPUT_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac"}

# Salidas: MP4 (vídeo con audio integrado) y formatos de audio.
VIDEO_OUTPUT_EXTENSIONS = {".mp4"}
AUDIO_OUTPUT_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac"}

# Códec de audio según la extensión de salida.
AUDIO_CODECS = {
    ".mp3": "libmp3lame",
    ".wav": "pcm_s16le",
    ".m4a": "aac",
    ".flac": "flac",
}
VIDEO_CODEC = "aac"  # audio dentro del contenedor MP4


def is_video_input(path: str | Path) -> bool:
    """Comprueba si la extensión corresponde a un vídeo de entrada soportado."""
    return Path(path).suffix.lower() in VIDEO_INPUT_EXTENSIONS


def is_audio_input(path: str | Path) -> bool:
    """Comprueba si la extensión corresponde a un audio de entrada soportado."""
    return Path(path).suffix.lower() in AUDIO_INPUT_EXTENSIONS


def validate_video_input(path: str | Path) -> Path:
    """Valida un vídeo de entrada; lanza ``ValueError`` si no está soportado."""
    target = Path(path)
    if not is_video_input(target):
        raise ValueError(
            f"Formato de vídeo no soportado: {target.suffix or '(sin extensión)'}. "
            f"Soportados: {', '.join(sorted(VIDEO_INPUT_EXTENSIONS))}"
        )
    return target


def validate_audio_input(path: str | Path) -> Path:
    """Valida un audio de entrada; lanza ``ValueError`` si no está soportado."""
    target = Path(path)
    if not is_audio_input(target):
        raise ValueError(
            f"Formato de audio no soportado: {target.suffix or '(sin extensión)'}. "
            f"Soportados: {', '.join(sorted(AUDIO_INPUT_EXTENSIONS))}"
        )
    return target


def validate_audio_output(path: str | Path) -> Path:
    """Valida una salida de audio; lanza ``ValueError`` si no está soportada."""
    target = Path(path)
    if target.suffix.lower() not in AUDIO_OUTPUT_EXTENSIONS:
        raise ValueError(
            f"Formato de salida de audio no soportado: {target.suffix or '(sin extensión)'}. "
            f"Soportados: {', '.join(sorted(AUDIO_OUTPUT_EXTENSIONS))}"
        )
    return target


def audio_codec_for(path: str | Path) -> str:
    """Devuelve el códec de audio de FFmpeg para la extensión dada."""
    suffix = Path(path).suffix.lower()
    if suffix in AUDIO_CODECS:
        return AUDIO_CODECS[suffix]
    raise ValueError(
        f"No hay códec definido para {suffix or '(sin extensión)'}. "
        f"Soportados: {', '.join(sorted(AUDIO_CODECS))}"
    )
