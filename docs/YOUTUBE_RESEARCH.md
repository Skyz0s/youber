# Investigación de YouTube (`youber.research`)

Módulo educativo para extraer y analizar **datos públicos** de canales y
vídeos de YouTube: títulos, visualizaciones, likes, duración, hashtags...
y guardarlos en formato estructurado (JSON, CSV, Markdown).

```python
import asyncio
from youber.research import ChannelAnalyzer, VideoAnalyzer, channel_overview

async def main():
    # Datos públicos de un canal (suscriptores + vídeos recientes)
    analyzer = ChannelAnalyzer(api_key=None)  # modo HTML (educativo)
    channel = await analyzer.analyze("@python", max_videos=10)
    print(channel.subscribers, len(channel.videos))

    # Datos de un vídeo concreto
    video = await VideoAnalyzer().analyze("https://youtu.be/abc123def45")
    print(video.title, video.views, video.hashtags)

    # Análisis de patrones (hashtags, títulos, duración)
    overview = channel_overview(channel)
    print(overview["top_hashtags"])

asyncio.run(main())
```

## Dos modos de extracción

| Modo | Descripción | Requisitos |
|---|---|---|
| `api` | YouTube Data API v3 (conforme a ToS, datos exactos) | `YOUTUBE_API_KEY` |
| `html` | Parsea las páginas públicas (`ytInitialData`) | Ninguno (uso educativo) |

`mode="auto"` (por defecto) usa la API si hay clave y HTML si no.

### Modo HTML: límites y buenas prácticas

- Solo datos **públicos** visibles sin login; sin stealth ni evasión de anti-bot.
- Rate-limit configurable (`request_delay`, por defecto 1,5 s entre peticiones).
- `/watch` y `/channel` **no están bloqueados** en el robots.txt de YouTube;
  las rutas bloqueadas (`/youtubei/`, `/results`, `/api/`...) no se usan.
- El layout de YouTube cambia: el parser es de mejor esfuerzo. Para datos
  fiables en producción, usa el modo `api`.

## CLI ``youber-research``

Entry point instalable que extrae canales o vídeos y exporta a fichero:

```bash
youber-research https://www.youtube.com/@python -n 20 -o python_channel.csv
youber-research https://youtu.be/abc123 -o video_info.json
youber-research https://www.youtube.com/@python --insights -o reporte.md
```

- `-n/--max-videos`: vídeos a extraer (por defecto 10).
- `-o/--output` + `-f/--format` (csv|json|md): el formato se deduce de la
  extensión si se omite `-f`.
- `--api` / `--html`: fuerza la API oficial (requiere `YOUTUBE_API_KEY`) o el
  parser de la página pública (por defecto).
- `--insights`: añade patrones (hashtags, títulos, duración, vistas) al
  informe Markdown y los muestra por consola.

## Análisis de patrones (`patterns.py`)

Funciones puras para estudiar *qué publica* un canal:

- `extract_hashtags(texto)` — hashtags de una descripción.
- `hashtag_frequency(vídeos)` — hashtags más usados.
- `title_patterns(títulos)` — números, MAYÚSCULAS, emojis, preguntas, "vs",
  "top N", palabras de tutorial.
- `duration_stats(vídeos)` — duración media/mín/máx y tramos
  (corto <4 min, medio 4-15, largo >15).
- `channel_overview(canal)` — resumen global con todo lo anterior.

Esto es **análisis descriptivo**; el módulo no manipula métricas.

## Exportación (`exporters.py`)

```python
from youber.research import export_channel, export_videos

export_channel(channel, "reports/canal.json", fmt="json")   # JSON completo
export_channel(channel, "reports/canal.md", fmt="md")       # informe Markdown
export_videos(channel.videos, "reports/videos.csv", fmt="csv")  # CSV (Excel-ready)
```

## Nota ética

Este módulo existe para investigación y educación. El modo API es la vía
conforme a los términos de servicio de YouTube; el modo HTML es para estudio
de la estructura pública de las páginas con mesura y respeto (rate-limit,
sin evasión). No uses esta herramienta para scraping abusivo, inflado de
métricas o cualquier uso que viole los ToS de YouTube.
