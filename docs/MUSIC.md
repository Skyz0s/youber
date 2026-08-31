# Catálogo de música (`youber.music`)

Gestión de una biblioteca musical local: escaneo de ficheros de audio,
metadatos en SQLite, etiquetas de estado de ánimo (mood), búsqueda y
sugerencias para elegir la música de fondo de tus vídeos.

## Estructura

| Módulo | Responsabilidad |
|---|---|
| `models.py` | `Mood` (enum) y `Track` (pydantic v2) |
| `database.py` | Persistencia SQLite (`MusicDatabase`) |
| `scanner.py` | Escaneo de ficheros + metadatos con ffprobe |
| `matcher.py` | Búsqueda por mood/género/texto y sugerencias |
| `library.py` | `MusicLibrary`: orquesta todo |
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
