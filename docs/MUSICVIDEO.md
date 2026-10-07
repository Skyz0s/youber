# YouTube Music Video — el videoclip dirigido por la letra

`youber.musicvideo` invierte la jerarquía del flujo de producción:

- **antes**: metadatos de un canal → tema → canción → guion de vídeo hablado
  (gancho/contenido/CTA) con planos genéricos. La letra solo elegía la canción.
- **ahora**: la **canción es la protagonista** y su **letra dirige** el vídeo.
  Cada línea con su ventana temporal se convierte en un plano cuya imagen sale
  de *esa* línea; la duración es la de la canción y la estructura es la de la
  canción (verso/estribillo/puente), no una plantilla.

De una misma dirección (un `MusicVideoPlan`) salen **dos líneas de producción**:

1. el **videoclip** completo (horizontal `16:9`, duración = canción);
2. un **corto vertical** (`9:16`, 30-60 s) con los *mejores momentos* — el
   estribillo — para Shorts/Reels.

## Piezas

| Módulo | Qué hace |
| --- | --- |
| `musicvideo.lexicon` | De una línea a un plano: localiza sujeto/acción/lugar/luz con un léxico local (es→en) y compone un `VisualBeat`. Offline y determinista. |
| `musicvideo.sections` | Detecta los **tramos** por repetición de la letra (el estribillo es lo que más se repite) y elige los **mejores momentos** (repetición + energía). |
| `musicvideo.director` | Une todo: `direct_song()` → `MusicVideoPlan`; `plan_to_shot_plan()` (planos para el motor visual) y `plan_to_script()` (texto de cada línea para quemar en pantalla). |
| `musicvideo.pipeline` | Mide la canción (duración, pulso, energía), dirige y produce **los dos vídeos**: pide los clips a `genvideo` y monta con `video`. El corto se **re-renderiza** en 9:16 (no se recorta). |
| `musicvideo.cli` | `youber-musicvideo plan` (enseña la dirección sin gastar GPU) y `render` (videoclip + corto). |

Reutiliza lo que ya había: `youber.sync` (letra con tiempos), `youber.visuals`
(planes, estilos, beat), `youber.genvideo` (generación local) y `youber.video`
(montaje). La **metadata** de un canal deja de dirigir; pasa a ser *empaquetado*
(título, descripción, tags, miniatura).

## Dos líneas de producción (tubería y CLI)

La tubería (`run_musicvideo`) mide la canción, dirige, genera los clips con el
backend local y monta. El corto vertical **se re-renderiza** en 9:16 a partir
del estribillo detectado (mejor encuadre que recortar el horizontal).

```bash
# Ver la dirección (tramos, mejores momentos, escenas) sin generar nada
youber-musicvideo plan cancion.m4a --lyrics cancion.lrc --title "Mi cancion"

# Producir el videoclip (16:9) y el corto vertical (9:16)
youber-musicvideo render cancion.m4a --lyrics cancion.lrc --title "Mi cancion" --preset 480p

# Probar la tubería entera sin GPU (MP4 sintético con FFmpeg)
youber-musicvideo render cancion.m4a --backend stub --preset 480p
```

Si no se pasa `--lyrics`, se busca `<audio>.lrc/.txt/.srt/.json` junto al audio.
El backend de generación es enchufable: `--backend comfy` (ComfyUI local, por
defecto) o `--backend stub` (sin GPU).

## Uso (biblioteca)

```python
import asyncio
from youber.genvideo.client import StubClient  # o ComfyUIClient en producción
from youber.musicvideo import run_musicvideo

result = asyncio.run(run_musicvideo(
    "mi_cancion.m4a", lyrics="mi_cancion.lrc", title="Mi canción",
    out_dir="salida", client=StubClient(width=832, height=480, fps=24),
))
print(result.video)  # videoclip 16:9
print(result.short)  # corto vertical 9:16 del estribillo
```

Y solo la dirección (sin generar):

```python
from youber.sync.timestamps import parse_lyrics_file
from youber.musicvideo import direct_song, plan_to_shot_plan, plan_to_script

document = parse_lyrics_file("mi_cancion.lrc")
plan = direct_song(document, title="Mi canción", duration=210.0)

videoclip = plan_to_shot_plan(plan)                     # 16:9, todos los planos
script = plan_to_script(plan)                           # textos = líneas

mejor = plan.highlights[0]
short = plan_to_shot_plan(plan, scenes=plan.highlight_scenes(mejor), aspect="9:16")
```

## Planos del guion (`youber.musicvideo.shots`)

La dirección dice *qué* se cuenta; el **guion** dice *cuándo* se corta. El
módulo reparte la canción en ``count`` huecos (:class:`ShotSlot`) y cada hueco es
un plano:

- **cubre la canción entera** (del segundo 0 a la duración), sin huecos ni
  solapes, instrumentales incluidos;
- cada hueco vive **dentro de un tramo** (un plano no cruza de verso a
  estribillo) y su encuadre sale de la **línea dominante** de esa ventana;
- los cortes caen **en el pulso** si se le pasa la rejilla medida;
- el **motivo** solo aparece donde la canción **se repite de verdad**:
  1. tramos con la **letra idéntica** (el estribillo que vuelve) comparten
     planos, alineados por posición relativa;
  2. dentro de un tramo, la **misma línea** comparte imagen en bloques de
     ``MAX_MOTIF_RUN`` huecos (más seguidos sería un plano congelado).

```python
from youber.musicvideo import build_shot_slots, slot_coverage, distinct_count

slots = build_shot_slots(plan, 40, grid=grid)   # 40 planos, cortes al pulso
report = slot_coverage(slots, plan)
assert report.ok                                # cubre la canción sin sorpresas
print(distinct_count(slots), "planos que hay que generar de verdad")
```

Y sin gastar GPU, desde el CLI:

```bash
youber-musicvideo shots mi_cancion.m4a --slots 40 --out planos.json
```

El parte de cobertura (``report``) es lo que vigila el test: si un plano se va a
otro tramo, si queda un hueco sin plano o si una escena se queda sin imagen, la
suite lo caza. Es justo el fallo que hacía que un videoclip pareciera «un vídeo
random con música encima».

## Ética

La letra es tuya (o se transcribe de tu propio audio con `youber-sync`); los
planos son **contenido original generado en local**. Nada de material ajeno ni
de manipulación de métricas.
