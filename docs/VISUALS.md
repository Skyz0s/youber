# Generación visual con IA local (`youber.visuals`)

Crea un vídeo **desde cero**: los planos los dibuja un modelo de difusión
local y el framework los anima y los monta con la canción. No usa clips
ajenos, ni stock, ni servicios en la nube: todo se genera en tu máquina.

```
guion + mood de la canción
        │
        ├─ 1. plan de planos    (prompt, encuadre y movimiento por plano)
        ├─ 2. stills            (SDXL-Turbo local, 1344×768 / 768×1344)
        ├─ 3. animación         (Ken Burns: paneo/zoom con FFmpeg)
        └─ 4. montaje           (xfade + canción + textos, motor youber.video)
```

## Instalación

```bash
pip install youber[visuals]      # torch + diffusers + pillow
```

Sin GPU ni modelos funciona igual con el **generador de prueba** (`--model
stub`), que dibuja degradados deterministas: ideal para tests y CI.

Modelo por defecto: [`stabilityai/sdxl-turbo`](https://huggingface.co/stabilityai/sdxl-turbo)
(1-4 pasos, gratis, se descarga la primera vez a la caché de Hugging Face).

## CLI

```bash
# Máster 16:9 con la canción completa (14 planos, GPU)
youber-visuals --topic "el paso del tiempo" \
    --song "Music/Distrokid/Ira/Antesdelatardecer.wav" \
    --out out/ --model stabilityai/sdxl-turbo --ai-steps 2

# Vertical 9:16 de 75 s del estribillo (dos ficheros de una pasada)
youber-visuals --topic "..." --song cancion.wav --out out/ --aspect 9:16 --short 75

# Sin GPU: mismo flujo con el generador de prueba
youber-visuals --topic "prueba" --song cancion.wav --out out/ --model stub --duration 20
```

Y dentro del flujo de metadatos → letras → vídeo:

```bash
youber-workflow --lyrics-video --visuals ai \
    --ai-shots 14 --ai-aspect 16:9 \
    --short 75 --preview
```

`--short SEGUNDOS` genera **además** el corte vertical eligiendo el trozo con
más energía de la canción (el estribillo), no el arranque.

`--ai-style` (y `--style` en `youber-visuals`) aceptan `auto` —por defecto— o
un estilo concreto (`cinematic`, `dreamy`, `dark`, `vibrant`, `minimal`) si
quieres forzarlo.

## Estilo automatico: el audio y los metadatos deciden

Un estilo fijo quema el concepto: si todos los videos salen iguales, en una
semana el canal parece el mismo video repetido. Por eso el estilo **ya no es
fijo**: `youber.visuals.selector` lo deduce de senales medibles.

**Fuentes**

| Fuente | De donde sale | Que aporta |
| --- | --- | --- |
| Audio | `AudioProfile` del catalogo (`youber-music analyze`) | energia, valencia, tempo, baile, acustica, modo |
| Sonoridad | FFmpeg sobre la cancion (RMS por segundo) | energia y dinamica (si no hay perfil) |
| Metadatos | titulo, descripcion y etiquetas del canal/video | temas/sentimiento y palabras clave |
| Guion | mood del brief | tinte adicional |

Cada fuente aporta `(valor, peso)` por eje (`energy`, `valence`, `tempo`,
`dance`, `tension`, `intimacy`) y el resultado es su media ponderada: cambiar
un dato mueve el estilo, no lo sortea.

**Que decide**

- **Estilo** — puntuacion lineal de cada estilo sobre los ejes + bonus por
  palabras clave (`lofi`->dreamy, `workout`->vibrant, `tutorial`/`python`->minimal,
  `documental`/`viaje`->cinematic...). Si dos estilos empatan, la
  `variation_key` (tema + formato + semilla) reparte de forma determinista:
  dos videos distintos no reciben lo mismo.
- **Fundidos** — tempo alto -> cortes agiles; lento -> fundidos largos (0.4-1.3 s).
- **Planos** — mas energia -> planos mas cortos (10-24 s por plano).
- **Movimientos** — el ciclo Ken Burns arranca en un punto distinto segun la
  pieza, para que no se repita la secuencia.

Todo queda escrito en la consola y en el `<nombre>_plan.json` (`style`,
`style_reason`, `style_scores`, `style_signals`, `seed`), asi que cualquier
render se puede **repetir** aun cambiando los valores por defecto.

```bash
# Forzar un estilo concreto (el ritmo y los fundidos siguen saliendo del audio)
youber-visuals --topic "..." --song cancion.wav --out out/ --style dreamy
```

## Formatos

| Formato | Genera el modelo | Entrega | Uso |
| --- | --- | --- | --- |
| `16:9` | 1344×768 | 1920×1080 | vídeo largo, YouTube Music |
| `9:16` | 768×1344 | 1080×1920 | Shorts / Reels |
| `1:1` | 1024×1024 | 1080×1080 | feed cuadrado |

Los tamaños de generación son *buckets* de entrenamiento de SDXL: se genera
en la proporción final (nada de recortes raros) y FFmpeg escala a la
resolución de entrega.

## Plan de planos

Cada plano sale de la escena del guion a la que pertenece (gancho, intro,
desarrollo, clímax, cta), que decide el *beat* de encuadre; el tema, las
palabras clave, el tono y el mood de la canción completan el prompt. Es
determinista: mismas entradas ⇒ mismo plan (y mismo vídeo, con la misma
semilla).

Las duraciones se reparten para que `suma − solapamientos = duración de la
canción`, así que el vídeo dura exactamente lo mismo que el audio.

## Movimientos (Ken Burns)

`zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `tilt_up`, `tilt_down` y
`static`, alternándose por defecto. El still se escala un 30 % por encima de
la entrega y el `zoompan` de FFmpeg hace el resto (sin bordes vacíos).

## Short: el corte del estribillo

`youber.visuals.short` decodifica la canción a PCM mono, calcula la energía
(RMS) por segundo y elige la ventana de N segundos con más energía. Después
recorta el audio con fundidos y renderiza el vertical con el mismo plan.
Determinista y sin depender de metadatos de la canción.

## API

```python
import asyncio
from youber.visuals import Aspect, VisualStyle, create_generator, render_visuals

result = asyncio.run(render_visuals(
    topic="la lluvia en la ciudad",
    output="out/lluvia.mp4",
    song="cancion.wav",                 # define la duración
    aspect=Aspect.VERTICAL,
    style=VisualStyle.DREAMY,
    mood="tristeza",
    shots=10,
    generator=create_generator("stabilityai/sdxl-turbo", steps=2),
    texts=False,                        # o True para superponer el guion
    preview=True,
))
print(result.video, result.plan.total_duration)
```

## GPU: offload para tarjetas de 8 GB

SDXL en `float16` ocupa ~7 GB de VRAM. En una tarjeta de 8 GB **compartida
con el escritorio** (Chrome, Telegram, etc.) no cabe: Windows empieza a
paginar a RAM y cada imagen pasa de ~10 s a **minutos**. El generador activa
por defecto `enable_model_cpu_offload()` (+ *slicing* de atención y VAE), que
mueve los módulos a la GPU por turnos. Con eso: carga ~38 s y **~10 s por
imagen** en una RTX 3050. Con mucha VRAM libre se puede desactivar
(`DiffusersGenerator(..., offload=False)`).

## Límites éticos

- Los planos son **contenido original** generado en local; el modelo es libre
  y no se envía nada a servicios externos.
- Nada de copiar material ajeno, scraping ni manipular métricas.
- La música debe ser tuya o con licencia (el flujo la coge de tu catálogo
  local).

## Tests

`tests/test_visuals.py`: 25 tests — plan de planos, generador *stub*,
animación, montaje completo, elección del estribillo, CLI y el flujo
`--lyrics-video --visuals ai`. Los que necesitan FFmpeg van con `skipif`;
ninguno necesita GPU ni red.
