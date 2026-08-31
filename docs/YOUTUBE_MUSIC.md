# YouTube Music (`youber.music.youtube_music` + `importers`)

Integración con **YouTube Music** como catálogo en la nube: busca canciones,
obtiene su información y las añade a la biblioteca del usuario. Incluye un
**importador desde CSV** que enriquece listas de canciones con los metadatos
de YouTube Music. **No descarga archivos**: solo metadatos públicos, para
usar música de forma legal y ética en los vídeos editados.

## Requisito

```bash
pip install -e ".[dev]"   # incluye ytmusicapi
```

Autenticación opcional (para añadir a la biblioteca): genera un fichero de
headers con `ytmusicapi` y guárdalo en `~/.youber/ytmusic_headers.json`, o
pásalo explícitamente. Sin autenticación, la búsqueda funciona en modo
anónimo.

## Cliente (`youtube_music.py`)

```python
import asyncio
from youber.music import YouTubeMusicClient

async def main():
    client = YouTubeMusicClient()  # usa ~/.youber/ytmusic_headers.json si existe

    song = await client.search_song("Never Gonna Give You Up", "Rick Astley")
    print(song["id"], song["title"], song["artist"], song["duration"])

    info = await client.get_song_info(song["id"])
    print(info["album"])

    ok = await client.add_to_library(song["id"])  # añade a "Me gusta"
    print("Añadida" if ok else "Fallo (¿sin autenticación?)")

asyncio.run(main())
```

Métodos:

- `search_song(title, artist)` → dict con `id`, `title`, `artist`,
  `duration`, `album`, `thumbnail` (o `None` si no hay resultados).
- `get_song_info(song_id)` → dict con `id`, `title`, `artist`, `duration`,
  `album`.
- `add_to_library(song_id)` → `True` si se añadió a la playlist "Me gusta"
  (requiere autenticación).

## Importador CSV (`importers.py`)

Lee un CSV con canciones y las busca en YouTube Music:

```python
import asyncio
from youber.music import YouTubeMusicClient, import_csv

async def main():
    result = await import_csv("catalogo.csv", client=YouTubeMusicClient())
    print(f"{result.matched} coincidencias, {result.unmatched} sin coincidencia")
    for song in result.songs:
        if song.matched:
            print(f"✅ {song.title} — {song.artist} ({song.ytmusic_id})")

asyncio.run(main())
```

- Columnas aceptadas (con alias en español): `title`/`título`/`canción`,
  `artist`/`artista`, `album`/`álbum`, `duration`/`duración` (acepta
  `"3:45"` o segundos).
- `import_csv(path, client=None, match=True)` devuelve un
  `ImportResult` con `total`, `matched`, `unmatched`, `errors` y la lista
  de `SongImport`.
- `match=False` solo lee el CSV sin buscar (para validar el formato).
- `read_csv(path)` devuelve las filas normalizadas.

## Ética

El módulo **no descarga archivos**: consulta metadatos públicos de YouTube
Music y opera sobre la cuenta del propio usuario (añadir a su biblioteca).
Es una vía legal y ética para usar música en vídeos editados, alineada con
los límites del framework (solo contenido propio o con licencia).
