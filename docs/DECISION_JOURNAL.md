# Registro de decisiones (*decision journal*)

Un generador que no recuerda **por qué** hizo cada cosa no sirve para aprender.
Este módulo guarda, para cada vídeo, todo el razonamiento del algoritmo y —más
tarde— cómo rindió de verdad. Al cabo de unos meses no tienes solo un
generador: tienes un **dataset** para saber qué características del *matching*
predicen que un vídeo funcione.

Es análisis descriptivo de **datos propios** (tu catálogo, tu canal): no se
manipula ninguna métrica de plataforma.

## Qué se guarda en cada decisión

| Bloque | Contenido |
|---|---|
| `attributes` | Tema, temas emocionales → peso, tema dominante, sentimiento, keywords, hashtags, patrones de títulos del canal, nº de vídeos analizados, duración objetivo. |
| `track` | Canción elegida, **motivo**, puntuación desglosada (`theme_score`, `sentiment_match`, `mood_match`, `keyword_hits`, `favorite`, `usage_count`), ventaja sobre la 2ª candidata (`margin`) y el **ranking completo** de candidatas. |
| `prompt` / `artifacts` | Prompt de producción y rutas de brief/guion/exports. |
| `video` | Fichero, duración, tamaño, nº de clips y **origen** de los clips (`local`, `pexels`, `pixabay`, `synthetic`). |
| `upload` | Id/URL del vídeo publicado (la llave para cruzar métricas después). |
| `performance` | Mediciones por ventana (`24h`, `7d`, `28d`, `lifetime`...): impresiones, **CTR**, vistas, retención (% medio visto), duración media vista, tiempo de visualización, me gusta, comentarios, compartidos, suscriptores ganados/perdidos, ingresos. |

Además, cada decisión lleva `algorithm_version` (para estudiar la deriva del
matcher) y `run_id`.

## Uso

### 1. Genera el vídeo (se registra solo)

```bash
youber-workflow --lyrics-video --channel @tu_canal --topic "Mi vídeo" \
    --library music --lyrics-dir letras -o reports
```

Cada ejecución deja su decisión en el journal
(`~/.youber/journal.db`, o `YOUBER_JOURNAL_DB`). Flags: `--no-journal` para no
registrar y `--journal-db <ruta>` para usar otra base de datos.

### 2. Asocia el vídeo subido

```bash
youber-journal upload dec-1a2b3c4d5e6f --video-id abc123 \
    --url https://youtu.be/abc123 --privacy public --published-at 2026-09-15T18:00
```

### 3. Pega las métricas de YouTube Studio

En Studio → *Analytics* → **Modo avanzado** → exporta la tabla a CSV. Luego:

```bash
youber-journal import studio_analytics.csv --window 28d --dry-run   # ver el cruce
youber-journal import studio_analytics.csv --window 28d             # guardarlo
```

El importador detecta las columnas por su nombre (español o inglés), admite
CSV con `,` o `;` y números en formato español (`1.000`, `4,5 %`). Cruza por
**id del vídeo** y, si no lo hay, por título. Las filas sin decisión registrada
salen en el resumen (con el título) para saber qué falta.

También puedes registrar métricas a mano (p. ej. la retención a las 48 h):

```bash
youber-journal performance dec-1a2b3c4d5e6f --window 48h \
    --views 1250 --impressions 25000 --ctr 4.7 --avg-view-percentage 39 \
    --subs-gained 12 --subs-lost 2
```

### 4. Mira y analiza

```bash
youber-journal list -n 10 --with-performance   # últimas decisiones
youber-journal show dec-1a2b3c4d5e6f           # ficha completa + candidatas
youber-journal stats                           # cuántas decisiones/mediciones hay
youber-journal dataset -o dataset.csv          # features + resultados (plano)
youber-journal analyze --metric ctr -o informe.md
```

`--json` (antes del subcomando) devuelve JSON para encadenar con otras
herramientas.

## El análisis: de journal a predicción

`youber-journal analyze` construye un dataset donde cada fila es un vídeo con:

- **features** *(lo que el algoritmo sabía al decidir)*: `chosen_score`,
  `theme_score`, `matched_theme_count`, `sentiment_match`, `mood_match`,
  `favorite`, `usage_count`, `keyword_hits`, `candidate_margin`,
  `catalog_size`, `theme_count`, `target_duration`, `scene_count`,
  `clip_count`, `video_duration`, `forced`...
- **resultados** *(lo que pasó después)*: `views`, `impressions`, `ctr`,
  `retention`, `avg_view_duration_seconds`, `watch_time_minutes`, `likes`,
  `comments`, `shares`, `subscribers_gained`, `net_subscribers`,
  `engagement_rate`.

Con eso calcula **correlaciones de Pearson** feature → métrica (ordenadas por
fuerza) y **medias por grupo** (tema dominante, origen de los clips,
sentimiento). El informe en Markdown incluye el `n` de cada correlación y los
avisos de siempre: correlación ≠ causalidad, y con pocos vídeos cualquier
correlación es ruido.

La separación features/resultados es deliberada: ninguna feature usa
información del futuro, así que el dataset sirve como base para un modelo
predictivo (con suficientes datos) en vez de ser una profecía autocumplida.

## Desde código

```python
from youber.journal import DecisionJournal, PerformanceSnapshot

journal = DecisionJournal()
journal.record(record)                                   # lo hace el workflow
journal.attach_upload(record.id, video_id="abc123")
journal.record_performance(record.id, PerformanceSnapshot(window="7d", views=1200, ctr=4.5))

for row in journal.dataset(window="7d"):
    print(row.features["theme_score"], row.outcomes["ctr"])

journal.export("dataset.csv", fmt="csv")
```

## Integración con el workflow

- `youber-workflow` (flujo clásico) y `youber-workflow --lyrics-video`
  registran su decisión al terminar (metadatos, pista usada, vídeo y —si se
  subió— la URL, de la que se extrae el id).
- El registro es local y barato: SQLite en `~/.youber/journal.db`, con las
  filas completas en JSON y unas columnas «calientes» (`created_at`,
  `video_id`, `views`, `ctr`...) para filtrar sin deserializar.
- Los tests aíslan `YOUBER_JOURNAL_DB` a un `tmp_path` (ver `tests/conftest.py`):
  la suite nunca escribe en tu journal real.
