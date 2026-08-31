# Edición de audio (`youber.audio`)

Módulo educativo para añadir **tu propia música** de fondo a vídeos, extraer
o reemplazar pistas de audio, aplicar efectos y sincronizar audio con vídeo.
Backend: **FFmpeg** (el estándar de facto).

## Requisito: FFmpeg

El módulo necesita `ffmpeg` y `ffprobe` en el `PATH`:

```bash
# Windows
winget install Gyan.FFmpeg
# macOS
brew install ffmpeg
# Linux
sudo apt install ffmpeg
```

Si no están instalados, las operaciones lanzan un `RuntimeError` con estas
instrucciones. El resto del framework funciona sin FFmpeg; solo este módulo
lo requiere.

## Uso

```python
import asyncio
from youber.audio import (
    add_background_music,
    extract_audio,
    adjust_volume,
    detect_silence,
)

async def main():
    # Añade tu música de fondo a un vídeo (MP4 → MP4)
    out = await add_background_music(
        "mi_video.mp4", "mi_musica.mp3", "resultado.mp4",
        volume=0.3, fade_in=2, fade_out=2, loop=True,
    )
    print(out)

    # Extrae el audio del vídeo como MP3
    audio = await extract_audio("mi_video.mp4", "audio.mp3")

    # Baja el volumen a la mitad
    await adjust_volume("audio.mp3", 0.5, "audio_bajo.mp3")

    # Detecta silencios (para encontrar dónde empieza el sonido)
    silences = await detect_silence("audio.mp3")
    print(silences)

asyncio.run(main())
```

## Operaciones

| Función | Descripción |
|---|---|
| `add_background_music(video, music, output, **cfg)` | Añade música de fondo (volumen, inicio, fades, loop, volumen del audio original) |
| `extract_audio(video, output)` | Extrae la pista de audio a MP3/WAV/M4A/FLAC |
| `replace_audio(video, audio, output)` | Sustituye por completo el audio del vídeo |
| `apply_fade(audio, duration, fade_type)` | Fade `in` / `out` / `both` |
| `adjust_volume(audio, volume, output)` | Volumen 0.0–2.0 (1.0 = original) |
| `mix_audios(a1, a2, output, ratio)` | Mezcla dos pistas (0.5 = mitad y mitad) |
| `detect_silence(audio, threshold)` | Lista de silencios `{start, end, duration}` |
| `align_audio_to_video(video, audio, output)` | Alinea el audio al vídeo por detección del primer sonido |

## Formatos

- **Vídeo (entrada):** MP4, MOV, AVI, MKV
- **Audio (entrada):** MP3, WAV, M4A, FLAC
- **Vídeo (salida):** MP4 (con audio integrado)
- **Audio (salida):** MP3, WAV, M4A, FLAC

Los formatos se validan por extensión (`formats.py`); las salidas se mapean
a códecs de FFmpeg (`libmp3lame`, `pcm_s16le`, `aac`, `flac`).

## Configuración (`models.py`)

`AudioConfig` valida los parámetros de `add_background_music`:

- `volume`: 0.0–1.0 (default 0.3)
- `music_start`: segundos de inicio en la música (default 0)
- `fade_in` / `fade_out`: segundos de fundido (default 2)
- `loop`: repetir música si es más corta que el vídeo (default True)
- `original_audio_volume`: 0.0–1.0 (default 0.7)

## Nota ética

Este módulo existe para editar **contenido propio**: usa solo música de tu
creación o con licencia, en vídeos que sean tuyos o con permiso. No añadas
música con derechos de autor a contenido ajeno, y no uses la edición de
audio para manipular métricas (el framework es educativo).
