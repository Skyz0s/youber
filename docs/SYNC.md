# Sync — Letras sincronizadas y subtítulos (youber-sync)

`youber.sync` añade letras sincronizadas a los vídeos generados por Youber:
dada una canción del catálogo (o un audio cualquiera), extrae la letra, la
**alinea con timestamps** y la **quema como subtítulos** en el vídeo final.

```
letra (.lrc/.txt/.srt) ─┐
                         ├→ LyricsAligner → .lrc/.srt/.json → SubtitleRenderer → MP4
audio (--audio/--track) ─┘        (Whisper o rough)              (FFmpeg/libass)
```

## Instalación

- Base: sin dependencias nuevas (FFmpeg obligatorio para `burn` y para
  conocer la duración del audio en `align`).
- Timestamps precisos con Whisper (opcional):

```bash
pip install 'youber[sync]'        # o: pip install faster-whisper
```

## CLI

```bash
youber-sync extract <letra.lrc|.txt|.srt|.json>     # letra en texto plano
youber-sync align --audio cancion.mp3 --lyrics letra.txt -o letra.lrc
youber-sync align --track <id> --lyrics letra.txt --whisper -f json
youber-sync burn --video final.mp4 --lyrics letra.lrc -o final_sub.mp4
```

### align

| Entrada | Sin `--whisper` | Con `--whisper` |
|---|---|---|
| Letra `.lrc`/`.srt` (temporizada) | Se usa tal cual (sus marcas mandan) | Se realinea a los segmentos transcritos de ESTE audio |
| Letra `.txt` (sin marcas) | Alineación rough (heurística determinista, sin red) | Timestamps precisos por segmentos Whisper |
| Sin `--lyrics` | — | Transcripción pura: la letra es lo transcrito |

- `--track <id>` resuelve el audio desde el catálogo `youber.music`
  (`--library`, default `music`); mete título/artista en los metadatos.
- `--model tiny|base|small|medium|large-v3` (default `small`); el modelo se
  descarga en el primer uso.
- `-f lrc|srt|json|txt` (default `lrc`); `-o` escribe fichero (si no, stdout).

### burn

Genera subtítulos con el filtro `subtitles` de FFmpeg (libass, con
`fontsdir`/`Arial` automáticos en Windows) y re-encodea a MP4 h264+aac.
`--font` y `--font-size` ajustan el estilo.

## API

```python
from youber.sync import LyricsExtractor, LyricsAligner, SubtitleRenderer

# 1) Letra desde fichero (o transcribe el audio: extract_from_audio)
texto = await LyricsExtractor().extract_from_file(Path("letra.lrc"))

# 2) Alinear: LRC ya temporizado pasa tal cual; .txt → rough sin Whisper
doc = await LyricsAligner().align("cancion.mp3", "letra.txt")

# 3) Preciso con Whisper (backend opcional): alinea las líneas a los segmentos
doc = await LyricsAligner().align("cancion.mp3", "letra.txt", model_size="small")

# 4) Quemar subtítulos en el vídeo
result = await SubtitleRenderer().render("final.mp4", doc, output="final_sub.mp4")
```

Formatos en `youber.sync.timestamps` (puro, offline): `parse_lrc/parse_srt/
parse_txt/parse_json`, `parse_lyrics_file`, `serialize(doc, "lrc|srt|json|txt")`,
modelos `LyricsDocument`/`SyncLine` (pydantic v2).

## Nota ética / licencias

- **Usa letras que poseas o con licencia** (ficheros .lrc/.txt propios) o
  transcribe TU audio con Whisper. El lookup online de letras está
  **deshabilitado por defecto**: servir letras de terceros (Genius, etc.)
  requiere licencia y scrapear viola sus ToS. `get_lyrics()` es el punto de
  extensión para un provider con API key y licencia explícita.
- Whisper transcribe contenido local; el modelo se descarga de Hugging Face
  (red) en el primer uso.

## Tests

`tests/test_sync.py`: parsers/serializers (LRC/SRT/JSON/TXT), alineación
rough y por segmentos, extracción, errores sin backend Whisper, CLI.
`tests/test_sync_render.py`: construcción del filtro (puro) + integración
real FFmpeg/libass con `skipif` si no hay FFmpeg.
