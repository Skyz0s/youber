# Análisis de letras (`youber.music.lyrics_analyzer`)

Extrae la **temática y el sentimiento** de las letras de tus canciones
para alinear mejor la música de fondo con el contenido del vídeo: si el
vídeo habla de pérdida, busca temas de letra tristes; si es una
celebración, temas de energía o alegría.

## Enfoque (offline, sin dependencias nuevas)

- **100 % local y determinista**: léxicos propios (temas emocionales y
  stop words en español/inglés) + frecuencias de palabras. Nada de
  modelos descargados, APIs ni scraping.
- **Sin dependencias nuevas**: solo biblioteca estándar + pydantic.
- **Opcional**: si una pista no tiene letra, el catálogo funciona igual
  (los campos quedan vacíos).
- Solo analiza ficheros `.txt` **tuyos** (los que ya tienes en disco).

## Temas detectados

`felicidad`, `tristeza`, `energia`, `calma`, `misterio`, `amor`.

Cada uno se puntúa con un peso `0..1` que combina el número de
coincidencias del léxico con su densidad en la letra. El **sentimiento**
global se deriva de la polaridad de los temas detectados
(`positive` / `negative` / `neutral`).

Cada tema se puede traducir a un `Mood` del catálogo para filtrar y
buscar: `felicidad→alegre`, `tristeza→triste`, `energia→energética`,
`calma→relajante`, `misterio→misteriosa`.

## CLI

```bash
# Escanear el catálogo analizando además las letras de un directorio
youber-music --library ~/musica scan --lyrics-dir ~/letras

# Ver el análisis de una pista concreta
youber-music --library ~/musica lyrics <id> --lyrics-dir ~/letras

# Buscar por temática de letra
youber-music --library ~/musica search --lyric-theme tristeza
youber-music --library ~/musica search --lyric-sentiment negative
youber-music --library ~/musica suggest --lyric-theme calma -n 5
```

Los ficheros de letras se emparejan de forma tolerante con la pista:
título, título + artista, artista + título o coincidencia parcial, todo
normalizado (sin acentos, signos ni mayúsculas). Se prueban varias
codificaciones (UTF-8, UTF-8 con BOM, Latin-1, CP1252) al leer.

## Uso desde código

```python
from youber.music import LyricsAnalyzer

analyzer = LyricsAnalyzer()
analysis = analyzer.analyze_lyrics(open("letra.txt", encoding="utf-8").read())

print(analysis.themes)          # {'tristeza': 0.87, 'amor': 0.42}
print(analysis.dominant_theme)  # 'tristeza'
print(analysis.sentiment)       # 'negative'
print(analysis.language)        # 'es'
print([m.value for m in analysis.moods()])  # ['triste']
```

Integrado con el catálogo:

```python
import asyncio
from youber.music import MusicLibrary

library = MusicLibrary("~/musica")
asyncio.run(library.scan(lyrics_dir="~/letras"))   # guarda el análisis en SQLite

# Pistas cuyo contenido encaja con un vídeo sobre soledad/pérdida
for track in library.search(lyrical_theme="tristeza"):
    print(track.title, track.lyrical_themes)
```

## Persistencia

El resultado se guarda en la pista (`Track`):

- `lyrical_themes: dict[str, float]` — tema → peso.
- `lyrical_sentiment: str` — `positive` / `negative` / `neutral`.

En SQLite son las columnas `lyrical_themes` (JSON) y
`lyrical_sentiment`; las bases de datos antiguas se migran
automáticamente (`ALTER TABLE`).

**Al re-escanear**: si el audio no cambia (mismo hash) la pista se
conserva tal cual, así que ejecuta el escaneo con `--lyrics-dir` cuando
añadas o cambies letras. Si cambia el audio, se recalcula todo.

## Ética

El análisis trabaja **solo con letras que ya tienes en disco**: no
descarga letras de internet, no consulta APIs de letras y no elude
términos de servicio. Es una ayuda para elegir mejor tu propia música.
