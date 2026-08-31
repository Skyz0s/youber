# Análisis Musical (Audio Features)

Módulo `youber.music.audio_features` — enriquece el catálogo local de música
con **características de audio** usando la **API oficial de Spotify** como
fuente primaria y un **modelo de estimación local** como fallback.

> Límites éticos (igual que el resto del framework): solo metadatos públicos
> vía API oficial (conforme a ToS); **no se descargan ficheros**. El
> estimador local es una **estimación educativa** (siempre con
> `confidence=0.5`) y nunca se presenta como dato real de la API. Sin
> manipulación de métricas: esto es análisis descriptivo.

## Estructura

```
src/youber/music/audio_features/
├── __init__.py      # API pública
├── spotify.py       # Cliente de la API de Spotify (búsqueda + features)
├── analyzer.py      # Obtiene características (Spotify o estimación local)
├── models.py        # AudioFeatures + AudioProfile (spec exacta)
├── estimator.py     # Modelo de estimación local (fallback, sin red)
├── matcher.py       # Emparejamiento canción local → track de Spotify
├── enricher.py      # Enriquece el catálogo (MusicLibrary + store JSON)
├── recommender.py   # Recomendación por similitud de características
└── cli.py           # Subcomandos analyze/recommend de youber-music
```

## Modelos (`models.py`)

`AudioFeatures` — la spec exacta de la Fase 14: `danceability`, `energy`,
`valence`, `acousticness`, `instrumentalness`, `liveness`, `speechiness`
(todas 0-1), `tempo` (BPM), `duration_ms`, `key` (-1..11), `mode` (0/1),
`time_signature` (3..7) y `confidence` (0-1, por defecto 1.0 = API).
La propiedad `source` distingue `api` (confianza 1.0) de `estimator`.

`AudioProfile` — perfil completo para recomendación: `track_id`,
`track_title`, `artist`, `features`, `moods` (estados de ánimo sugeridos),
`recommendation_tags`, y los buckets `energy_level` (baja/media/alta),
`valence_bucket` (triste/neutral/alegre), `tempo_bucket` (lento/medio/rápido)
y `dance_bucket` (baja/media/alta).

Helpers puros (offline-testables): `build_profile()`, `energy_level_for()`,
`valence_bucket_for()`, `tempo_bucket_for()`, `dance_bucket_for()`,
`suggest_moods()` (usa los `Mood` del catálogo local) y `suggest_tags()`.

## Spotify (`spotify.py`)

`SpotifyClient` — cliente async de la **Web API de Spotify** (flujo Client
Credentials):

```python
from youber.music.audio_features import SpotifyClient

client = SpotifyClient()          # lee SPOTIFY_CLIENT_ID/SECRET (env o ~/.youber/spotify_credentials.json)
client.available                  # False sin credenciales
track = await client.search_track("Never Gonna Give You Up", "Rick Astley")
features = await client.get_audio_features(track["track_id"])
```

Sin credenciales, `available` es `False` y el framework cae al estimador
local. El token se obtiene una vez y se cachea.

## Estimador local (`estimator.py`)

`LocalEstimator.estimate(genre, bpm, duration_ms, moods)` — heurísticas
deterministas por género (15 perfiles: electronic, pop, rock, classical,
lofi, hip hop, podcast...) ajustadas por mood y BPM. Devuelve
`AudioFeatures` con `confidence=0.5` (estimación educativa, sin red).

## Analizador (`analyzer.py`)

`AudioAnalyzer.analyze(...)` — orquesta la obtención: **Spotify primero**
(si hay credenciales y la canción encaja con el `TrackMatcher`), **estimador
local como fallback** (sin credenciales, canción no encontrada o error de
red). Devuelve siempre un `AudioProfile` con buckets calculados.

## Emparejamiento (`matcher.py`)

`TrackMatcher` — normaliza títulos/artistas (minúsculas, sin acentos ni
puntuación) y puntúa candidatos (título 70 %, artista 30 %) para elegir el
track de Spotify correcto a partir de la pista local.

## Enriquecido del catálogo (`enricher.py`)

- `AudioFeatureStore` — almacén JSON persistente en
  `~/.youber/audio_features.json` (get/set/all/has/clear/stats).
- `CatalogEnricher` — analiza las pistas de una `MusicLibrary` y guarda sus
  perfiles; `enrich_all()` omite las ya analizadas.

```python
from youber.music import MusicLibrary
from youber.music.audio_features import CatalogEnricher

enricher = CatalogEnricher(library=MusicLibrary("music"))
result = await enricher.enrich_all()   # result.enriched / result.total / result.errors
```

## Recomendación (`recommender.py`)

`FeatureRecommender` — compara perfiles con **distancia euclídea ponderada**
sobre el vector de características normalizado (energía y bailabilidad pesan
más) y sugiere las pistas más parecidas:

```python
from youber.music.audio_features import FeatureRecommender

recommendations = FeatureRecommender(limit=5).recommend(target, catalog)
for item in recommendations:
    print(item.rank, item.track_title, item.score, item.shared_moods)
```

## CLI (`youber-music analyze`)

Se integra en el comando existente `youber-music`:

```
youber-music analyze <id>          # analiza una pista (Spotify o estimación)
youber-music analyze <id> --local  # fuerza la estimación local (sin red)
youber-music analyze --all         # analiza todo el catálogo
youber-music analyze --refresh     # reanaliza aunque ya exista perfil
youber-music recommend <id> -n 5   # pistas similares por características
```

Ejemplo completo sin credenciales (estimación local):

```bash
youber-music --library ~/musica scan
youber-music --library ~/musica analyze --all --local
youber-music --library ~/musica recommend <id> -n 3
```

Con `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` configurados (env o
`~/.youber/spotify_credentials.json`), `analyze` usa los datos reales de la
API (confianza 1.0) y solo cae al estimador si la canción no aparece.

## Verificación

- 68 tests (modelos, buckets, estimator determinista, matcher, Spotify con
  cliente HTTP fake, analyzer con fallback, store/enricher, recommender y
  CLI); suite completa: **423 passed**.
- ruff + mypy limpios (110 ficheros).
