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

Reutiliza lo que ya había: `youber.sync` (letra con tiempos), `youber.visuals`
(planes, estilos, beat), `youber.genvideo` (generación local) y `youber.video`
(montaje). La **metadata** de un canal deja de dirigir; pasa a ser *empaquetado*
(título, descripción, tags, miniatura).

## Uso (biblioteca)

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

## Ética

La letra es tuya (o se transcribe de tu propio audio con `youber-sync`); los
planos son **contenido original generado en local**. Nada de material ajeno ni
de manipulación de métricas.
