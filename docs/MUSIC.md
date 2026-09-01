# Catálogo de música (`youber.music`)

Gestión de una biblioteca musical local: escaneo de ficheros de audio,
metadatos en SQLite, etiquetas de estado de ánimo (mood), búsqueda y
sugerencias para elegir la música de fondo de tus vídeos.

## Estructura

| Módulo | Responsabilidad |
|---|---|
| `models.py` | `Mood`, `TrackSource` (enum) y `Track` (pydantic v2) |
| `database.py` | Persistencia SQLite (`MusicDatabase`) |
| `scanner.py` | Escaneo de ficheros + metadatos con ffprobe |
| `matcher.py` | Búsqueda por mood/género/texto y sugerencias |
| `library.py` | `MusicLibrary`: orquesta todo |
| `providers.py` | Importación desde plataformas (Apple/iTunes, Spotify) |
| `apple_library.py` | Importación de la biblioteca completa de Apple (XML exportado) |
| `spotify_library.py` | Conector OAuth de Spotify (requiere Premium; dormante) |
| `youtube_music.py` | Cliente YouTube Music + importación de biblioteca personal |
| `cli.py` | Comando `youber-music` |

## CLI

```bash
youber-music --library ~/musica scan        # escanea y sincroniza
youber-music --library ~/musica list        # lista todas las pistas
youber-music --library ~/musica search --mood relajante
youber-music --library ~/musica search --text piano --favorite
youber-music --library ~/musica suggest --mood energética -n 5
youber-music --library ~/musica favorite <id>
youber-music --library ~/musica info <id>

youber-music import-cloud "lofi beats" --source apple      # iTunes (sin API key)
youber-music import-cloud "lofi beats" --source spotify -n 5  # Spotify (credenciales)
youber-music import-cloud "piano" --source apple --dry-run  # solo busca, no guarda
youber-music import-apple-library "Music Library.xml"       # TODA tu biblioteca de Apple
youber-music import-apple-library "Music Library.xml" --dry-run
youber-music import-ytmusic-library                          # tu biblioteca de YouTube Music
youber-music import-ytmusic-library --no-playlists           # solo Me gusta + guardadas
```

## Importar tu biblioteca de YouTube Music (gratis, sin API keys)

BARF puede importar **toda tu biblioteca personal de YouTube Music** (Me
gusta, canciones guardadas y playlists) usando ``ytmusicapi`` — sin API
keys, sin cuentas de pago. **Solo metadatos: nunca se descarga audio**.

### 1. Generar los headers de autenticación (una vez)

La biblioteca personal requiere autenticación. Genera el fichero de
headers con la herramienta oficial:

```bash
python -c "from ytmusicapi import setup; setup(filepath='headers.json')"
```

Se abre una ventana del navegador: inicia sesión en tu cuenta de Google
(en music.youtube.com) y el script guarda el fichero. Después muévelo a su
sitio:

```bash
mkdir -p ~/.youber && mv headers.json ~/.youber/ytmusic_headers.json
```

(Alternativa manual: en music.youtube.com logueado, DevTools → Network →
recargar → clic en cualquier petición → copiar las cabeceras a un JSON
con las claves `User-Agent`, `Accept`, `Accept-Language`, `Cookie`…)

### 2. Importar la biblioteca

Desde el dashboard (botón **🎧 Importar mi biblioteca de YouTube Music**,
con opción de incluir playlists) o desde la CLI:

```bash
youber-music import-ytmusic-library
```

Importa «Me gusta», guardadas y playlists como pistas ``source=youtube``
con su ``videoId`` como ``external_id``. **Idempotente**: si repites la
importación (p. ej. tras añadir canciones nuevas), no duplica nada.

Nota: el conector de **Spotify** (``spotify_library.py``) está dormante —
Spotify exige cuenta Premium para usar su Web API, así que no se activa
hasta tener credenciales de una cuenta Premium.

## Registrar TODA tu biblioteca de Apple (exportación XML)

Para importar **todas tus canciones de Apple Music/iTunes de una vez** (no
una búsqueda a la vez):

1. En la app Música/iTunes: **Archivo → Biblioteca → Exportar biblioteca…**
   (en Windows/iTunes: **File → Library → Export Library**).
2. Se genera un fichero plist XML con toda tu biblioteca:
   - Mac: `~/Music/Music/Music Library.xml`
   - Windows/iTunes: `~/Music/iTunes/iTunes Music Library.xml`
3. Impórtalo (CLI o dashboard):

```bash
youber-music import-apple-library "C:/Users/tu/Music/iTunes/iTunes Music Library.xml"
```

El parser (`youber.music.apple_library`) lee el XML con ``plistlib``,
extrae título, artista, álbum, duración y género de cada canción (omite
vídeos, podcasts y entradas sin título) y las guarda como pistas
``source=apple`` con su ``Persistent ID`` de Apple como ``external_id``
(estable entre exportaciones: reimportar no duplica nada).

**Solo metadatos: nunca se descarga ni copia audio** (legal/ético). Si tus
canciones tienen ficheros locales, escanéalas con `scan` para tenerlas
como pistas ``local`` editables en vídeo.

## Importar catálogo desde plataformas (metadatos públicos)

`youber-music import-cloud` busca canciones en **Apple/iTunes** (Search
API pública, sin API key) o **Spotify** (Web API, requiere credenciales
gratuitas de desarrollador: `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` o
`~/.youber/spotify_credentials.json`) y las añade al catálogo con sus
metadatos: título, artista, álbum, duración, género, carátula y URL de
preview.

**Solo metadatos públicos: nunca se descarga audio** (legal/ético,
conforme a ToS). Las pistas importadas se marcan con su origen
(`source` = `apple`/`spotify`) y un `external_id`; repetir la importación
no duplica nada. Aparecen en el dashboard (widget `catalog-stats`, con
desglose `by_source`) y en las búsquedas por mood/género.

Las pistas cloud **no** se pueden usar como música de un vídeo (no hay
fichero local): el editor lo rechaza con un mensaje claro. Para editar
vídeos necesitas ficheros de audio propios (escaneados con `scan`).

```python
import asyncio
from youber.music.providers import import_cloud
from youber.music.database import MusicDatabase

async def main():
    db = MusicDatabase("music/.music.db")
    summary = await import_cloud("lofi beats", "apple", limit=10, db=db)
    print(summary)  # {'added': ..., 'skipped': ..., 'total': ...}
    db.close()

asyncio.run(main())
```

Moods disponibles: `energética`, `relajante`, `épica`, `productiva`,
`triste`, `alegre`, `misteriosa`, `personalizada`.

## Uso desde código

```python
import asyncio
from youber.music import MusicLibrary, Mood

async def main():
    library = MusicLibrary("~/musica")       # crea ~/musica/.music.db
    summary = await library.scan()           # añade/actualiza/elimina
    print(summary)

    # Sugerencias para un estado de ánimo (favoritas y menos usadas primero)
    for track in library.suggest(mood=Mood.RELAXING, limit=3):
        print(f"🎵 {track.title} — {track.artist} ({track.duration:.0f}s)")

    library.mark_favorite(track_id, True)    # ⭐
    library.record_usage(track_id)           # incrementa uso
    library.close()

asyncio.run(main())
```

## Cómo funciona el escaneo

`scan_library()` recorre el directorio (recursivo), analiza cada fichero de
audio (MP3, WAV, M4A, FLAC) con `ffprobe` (duración, título, artista,
género) y calcula el SHA-256 del fichero:

- Pista nueva → se añade.
- Mismo hash → sin cambios (se conserva).
- Hash distinto → se actualiza (conservando favorito y uso).
- Fichero eliminado → se retira del catálogo.

## Sugerencias (`matcher.py`)

`score_track()` puntúa cada pista: +5 si coincide el mood, +2 si es
favorita, +1 por palabra del texto encontrada en título/artista/género, y
−0.1 por uso (para rotar sugerencias). `suggest_tracks()` ordena por esa
puntuación y devuelve las mejores.

## Ética

El catálogo organiza **música propia o con licencia**. No lo uses para
distribuir música ajena ni para eludir derechos de autor; es una herramienta
de organización y selección para tus propios vídeos.
