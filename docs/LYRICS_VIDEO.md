# Flujo «metadatos → letras → vídeo» (`--lyrics-video`)

Cambia el paso final del workflow: en vez de montar un vídeo de prueba con
una música cualquiera, **busca en las letras** de tu catálogo la canción que
hace falta para el contenido, compone un **prompt** a partir de eso y genera
el vídeo **en local** con clips de **Pexels/Pixabay** + la canción elegida.

## Flujo

1. **Metadatos del canal** — `ChannelAnalyzer` (HTML o API) o `--demo`.
2. **Vídeos recientes** — tabla con título/vistas/duración.
3. **Insights de patrones** — `youber.research.patterns.channel_overview`.
4. **Canción (por letra)** — el texto de los metadatos (títulos,
   descripciones, hashtags) se analiza con el **mismo léxico** que las letras
   (`youber.music.lyrics_analyzer`), y `youber.music.selector` puntúa cada
   pista del catálogo por temas compartidos + sentimiento + mood + keywords.
5. **Prompt y guion** — `youber.script.prompt` compone el prompt de
   producción (tono, estructura, B-roll, banda sonora) y el guion editable
   (`Script`), coherente con la canción elegida.
6. **Vídeo local + audio** — clips de B-roll de Pexels/Pixabay
   (`youber.video.stock`) → `youber.script.builder` → render FFmpeg
   (`youber.video.editor`) con la canción seleccionada como banda sonora.

Artefactos: `<slug>_final.mp4`, `<slug>_brief.json`, `<slug>_guion.json`,
`<canal>.json`, `<canal>.md` y los clips en `clips/`.

## CLI

```bash
# Flujo completo (metadatos reales + letras + Pexels + render)
youber-workflow --lyrics-video --channel @python -n 10 \
    --topic "Mi vídeo" --library music --lyrics-dir letras -o reports

# Sin red: canal sintético + clip sintético si no hay key de stock
youber-workflow --lyrics-video --demo --topic "Demo" \
    --library music --stock none -o reports

# Solo el prompt y el guion (sin render)
youber-workflow --lyrics-video --demo --topic "Demo" --no-render
```

Flags: `--topic`, `--lyrics-dir`, `--clips` (tus propios clips), `--stock`
(`auto|pexels|pixabay|none`), `--track` (fuerza una canción del catálogo),
`--no-render`.

## Desde código

```python
from youber.music.selector import select_best_track, theme_profile
from youber.script.prompt import build_video_brief, brief_to_script

profile = theme_profile("Antes de desaparecer: despedidas y nostalgia...")  # metadatos
match = select_best_track(library.all(), profile)                          # canción
brief = build_video_brief(insights, topic="Antes de desaparecer", profile=profile,
                          track_match=match)                               # prompt
script = brief_to_script(brief, insights)                                  # guion
```

`build_project(..., music_track_id=match.track_id)` fija la canción elegida
en el proyecto (tiene prioridad sobre la sugerencia por mood).

## Requisitos

- **Clips de B-roll**: `PEXELS_API_KEY` o `PIXABAY_API_KEY` (o
  `~/.youber/pexels_key.txt`). Sin key, el flujo cae a un clip sintético
  generado con FFmpeg para poder renderizar offline.
- **Catálogo con letras**: `youber-music --library music scan --lyrics-dir letras`
  (los ficheros `.txt` se emparejan por título de forma tolerante).
- **FFmpeg** (render local).

## Ética

Solo metadatos públicos y tu propia música/con licencia; clips de stock con
licencia libre (Pexels/Pixabay License). El análisis de letras es 100 %
offline (léxicos locales, sin modelos descargados ni scraping) y no se
manipulan métricas de ninguna plataforma.
