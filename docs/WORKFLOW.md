# Flujo completo (`youber-workflow`)

Pipeline educativo de principio a fin: **investigación de YouTube + edición
de audio**. Une los módulos `research` y `audio` en un solo comando.

```bash
youber-workflow --channel @python -n 10 -o reports
youber-workflow --demo -o reports   # sin red: canal sintético + medios generados
youber-workflow --video mi_video.mp4 --music mi_musica.mp3 -o reports
```

## Pasos del flujo

1. **Investigación del canal** — `ChannelAnalyzer` (modo HTML público o API v3).
2. **Vídeos recientes** — tabla con títulos, vistas y duración.
3. **Insights de patrones** — `channel_overview()`: hashtags, patrones de
   títulos, duración media, vistas medias.
4. **Vídeo de ejemplo** — local (`--video`) o generado con FFmpeg
   (`testsrc` + tono senoidal, sin dependencias externas).
5. **Música de fondo** — local (`--music`) o generada con FFmpeg
   (`sine` → MP3). Se añade con `add_background_music` (volumen 0.3,
   fades de 2 s).
6. **Exportación** — vídeo final MP4 + canal en JSON, CSV (vídeos) y
   Markdown.

## Modo demo (`--demo`)

El canal sintético (`demo_channel()`) incluye 4 vídeos con patrones
variados (títulos con números, MAYÚSCULAS, preguntas, "vs", tutoriales)
para que los insights sean demostrativos. El vídeo y la música se generan
con FFmpeg, así que **el flujo completo funciona sin red ni ficheros
externos**:

```bash
python examples/complete_workflow.py --demo -o reports
```

## Desde código

```python
import asyncio
from youber.cli.workflow_cli import run_workflow

result = asyncio.run(run_workflow(demo=True, output_dir="reports"))
print(result["final_video"])  # reports/canal-demo-sintetico_final.mp4
```

`run_workflow()` devuelve un dict con las rutas de todos los artefactos:
`video`, `music`, `final_video`, `json`, `csv`, `markdown`.

## Ética

El flujo genera vídeo y música **sintéticos** (sin derechos de autor) y
analiza solo datos públicos. Si usas tus propios ficheros, que sean de tu
creación o con licencia, y vídeos propios o con permiso.
