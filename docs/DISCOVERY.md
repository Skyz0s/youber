# Descubrimiento de Canales (Channel Discovery)

Módulo `youber.discovery` — buscador inteligente de canales de YouTube por
**categorías, temas y métricas públicas**, para facilitar la investigación de
mercado.

> Límites éticos (igual que el resto del framework): solo datos públicos, sin
> evasión de anti-bot, respeto a robots.txt y ToS (modo API = conforme a
> ToS), y sin manipulación de métricas. Esto es **descubrimiento/análisis**,
> no inflado.

## Estructura

```
src/youber/discovery/
├── __init__.py      # API pública
├── categories.py    # 20 categorías predefinidas y sus temas
├── search.py        # Buscador de canales (API / HTML / demo)
├── ranking.py       # Ranking por métricas (subs, vistas, engagement...)
├── similarity.py    # Canales similares (temas + categoría + tamaño)
├── cache.py         # Caché de resultados (JSON con TTL)
└── cli.py           # Comando youber-discovery
```

## Categorías y temas

`ChannelCategory` define 20 categorías con valores en español
(`tecnología`, `educación`, `gaming`, `música`, `ciencia`, `negocios`,
`salud`, `viajes`, `cocina`, `moda`, `deportes`, `noticias`,
`entretenimiento`, `cine`, `animación`, `podcast`, `manualidades`,
`fotografía`, `marketing`...) y `CATEGORY_TOPICS` asocia temas de búsqueda a
cada una.

```python
from youber.discovery.categories import ChannelCategory, topics_for, infer_category

topics_for(ChannelCategory.TECHNOLOGY)
# ['python', 'javascript', 'ia', 'machine learning', ...]

infer_category("Curso de python con machine learning")
# ChannelCategory.TECHNOLOGY
```

## Buscador (`ChannelSearcher`)

Busca canales por texto libre, categoría o temas, con tres vías:

- **API oficial** (`mode="api"`): YouTube Data API v3 (conforme a ToS,
  requiere `YOUTUBE_API_KEY`).
- **Página pública** (`mode="html"`): parsea `ytInitialData` de la página de
  resultados de búsqueda (canales). Sin login, con rate-limit (1.5 s).
- **Demo** (`mode="demo"`): canales sintéticos deterministas, sin red —
  pensado para probar el flujo completo sin credenciales.

`mode="auto"` elige API si hay clave y HTML si no.

```python
import asyncio
from youber.discovery import ChannelSearcher

async def main():
    searcher = ChannelSearcher(api_key="TU_API_KEY")  # o sin clave (HTML)
    result = await searcher.search("python", category=ChannelCategory.TECHNOLOGY, limit=10)
    for hit in result.channels:
        print(hit.title, hit.subscriber_count, hit.category)
```

Cada `ChannelHit` incluye `channel_id`, `title`, `url`, `handle`,
`description`, `subscriber_count`, `video_count`, `view_count`,
`category` (inferida) y `matched_topics`.

## Ranking por métricas

`rank_channels()` ordena canales por:

- `subscribers` — suscriptores
- `views` — vistas totales
- `videos` — número de vídeos
- `engagement` — vistas por suscriptor (por defecto)
- `views_per_video` — vistas por vídeo

```python
from youber.discovery.ranking import RankingMetric, rank_channels

ranked = rank_channels(result.channels, metric=RankingMetric.ENGAGEMENT, limit=5)
for item in ranked:
    print(item.rank, item.channel.title, f"{item.score:.1f}")
```

## Canales similares

`find_similar(target, pool)` busca los canales de un pool más parecidos a uno
de referencia, combinando temas compartidos (40 %), misma categoría (30 %) y
proximidad de tamaño en escala logarítmica (30 %).

```python
from youber.discovery.similarity import find_similar

similar = find_similar(result.channels[0], result.channels, limit=5, min_score=0.3)
```

## Caché

`DiscoveryCache` guarda los resultados en `~/.youber/cache/discovery.json`
con TTL por entrada (1 hora por defecto) para no repetir peticiones al
investigar el mismo nicho.

```python
from youber.discovery.cache import DiscoveryCache

cache = DiscoveryCache()
cache.set("python:tecnología", result.model_dump(mode="json"))
cached = cache.get("python:tecnología")
```

## CLI (`youber-discovery`)

```
youber-discovery categories                     # lista categorías y temas
youber-discovery categories --category tecnología
youber-discovery search python --category tecnología --limit 10
youber-discovery search python --api --rank subscribers -o canales.json
youber-discovery search python --demo -o canales.csv   # sin red
youber-discovery similar @canal --query python --demo
youber-discovery cache stats
youber-discovery cache clear
```

Ejemplo real (modo HTML, sin API key):

```bash
youber-discovery search python --category tecnología --limit 10 --rank engagement
```

Ejemplo con exportación:

```bash
youber-discovery search "machine learning" --html -n 15 -o descubrimiento.md
```

El fichero de salida se deduce de la extensión (`.json`, `.csv` con BOM
UTF-8, `.md`), o se fuerza con `--format`.
