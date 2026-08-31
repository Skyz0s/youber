"""Módulo de edición de audio de BARF.

Herramientas educativas para añadir **tu propia música** de fondo a vídeos,
extraer/reemplazar pistas de audio, aplicar efectos (fade, volumen, mezcla)
y sincronizar audio con vídeo. Backend: FFmpeg.

Límites éticos (igual que el resto del framework):

- Solo contenido propio o con licencia; sin piratear música ni vídeos.
- Sin manipulación de métricas: es edición de audio, no inflado.
- Uso educativo y de investigación.
"""

from youber.audio.editor import add_background_music, extract_audio, replace_audio
from youber.audio.effects import adjust_volume, apply_fade, mix_audios
from youber.audio.models import AudioConfig, ProcessingResult
from youber.audio.sync import align_audio_to_video, detect_silence

__all__ = [
    "AudioConfig",
    "ProcessingResult",
    "add_background_music",
    "adjust_volume",
    "align_audio_to_video",
    "apply_fade",
    "detect_silence",
    "extract_audio",
    "mix_audios",
    "replace_audio",
]
