# Motor de edición de vídeo (`youber.video`)

Motor educativo de edición de vídeo con backend FFmpeg: proyectos con
**múltiples clips**, **transiciones**, **textos e imágenes superpuestas** y
**música de fondo** del catálogo.

## Estructura

| Módulo | Responsabilidad |
|---|---|
| `models.py` | `Project`, `Clip`, `Transition`, `TextOverlay`, `ImageOverlay` (pydantic v2) |
| `timeline.py` | Expande el proyecto en segmentos con duraciones y valida transiciones |
| `effects.py` | Filtros de vídeo/audio: velocidad, volumen, recorte, escala, B/N, sepia... |
| `transitions.py` | Cadenas `xfade`/`acrossfade`/`concat` entre clips |
| `overlays.py` | `drawtext` para textos y `overlay` para imágenes |
| `renderer.py` | Construye y ejecuta el comando FFmpeg completo |
| `editor.py` | `VideoEditor`: fachada para crear proyectos y renderizar |
| `cli.py` | Comando `youber-edit` |

## CLI

```bash
youber-edit new proyecto.json --title "Mi vídeo" --resolution 1280x720
youber-edit add-clip proyecto.json intro.mp4
youber-edit add-clip proyecto.json main.mp4 --speed 1.5
youber-edit add-transition proyecto.json --clip-index 1 --type fade --duration 1
youber-edit add-text proyecto.json "Hola mundo" --position bottom_center
youber-edit add-image proyecto.json logo.png --opacity 0.8
youber-edit set-music proyecto.json <track-id> --volume 0.3
youber-edit render proyecto.json -o final.mp4 --library ~/musica
```

## Uso desde código

```python
import asyncio
from youber.video import VideoEditor, TransitionType, TextPosition

async def main():
    editor = VideoEditor()
    project = editor.new_project("Mi vídeo", resolution=(1280, 720), fps=30)

    editor.add_clip(project, "intro.mp4")
    editor.add_clip(project, "main.mp4", speed=1.5)
    editor.add_transition(project, clip_index=1, type=TransitionType.FADE, duration=1.0)
    editor.add_text(project, "¡Hola!", position=TextPosition.TOP_CENTER, font_size=64)
    editor.set_music(project, track_id="abc123", volume=0.3)

    await editor.render(project, "final.mp4")
    print("Listo 🎬")

asyncio.run(main())
```

## Modelos

- **`Clip`**: `file_path`, `start` (offset en el fichero), `duration`, `volume`
  (0-2), `speed`, `crop (x, y, w, h)`.
- **`Transition`**: `clip_index` (clip donde termina), `type`
  (`none`, `fade`, `crossfade`, `wipe`, `slide`), `duration`.
- **`TextOverlay`**: `text`, `position` (7 posiciones), `font_size`, `color`,
  `background`, `font_file`, `start_time`, `duration`.
- **`ImageOverlay`**: `image_path`, `position`, `opacity`, `scale`,
  `start_time`, `duration`.
- **`Project`**: `title`, `clips`, `music_track_id`, `music_volume`,
  `transitions`, `text_overlays`, `image_overlays`, `output_format` (mp4/mkv),
  `resolution`, `fps`, `created_at`, `updated_at`.

## Cómo renderiza

El renderer construye un único `filter_complex`:

1. Cada clip se recorta (`trim`) y se normaliza (escala, FPS, `yuv420p`).
2. Los clips se encadenan con `xfade` (vídeo) y `acrossfade` (audio), o
   `concat` si no hay transición.
3. Se dibujan textos (`drawtext`) e imágenes (`overlay`) con ventana
   temporal (`enable=between(t, ...)`).
4. La música del catálogo se mezcla con `amix` (volumen + fades de 2 s).
5. Salida MP4/MKV con `libx264` + `aac` y `-shortest`.

### Nota sobre fuentes

`drawtext` necesita una fuente. En sistemas sin fontconfig (p. ej. Windows)
hay que pasar `font_file` en el `TextOverlay` (p. ej.
`C:/Windows/Fonts/arial.ttf`); la CLI y el editor lo aceptan.

## Ética

Igual que el resto del framework: solo contenido propio o con licencia
(clips, imágenes, música y fuentes). Es edición educativa, no manipulación
de métricas ni distribución de contenido ajeno.
