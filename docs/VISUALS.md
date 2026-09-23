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
| Sonoridad | FFmpeg sobre la cancion (RMS por segundo) | energia y dinamica |
| Tempo | onsets sobre la cancion (`youber.visuals.tempo`) | tempo real (BPM) sin depender del catalogo |
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
- **Cortes** — con pulso fiable, cada plano cambia en el beat (ver abajo).
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

### Tempo medido en local (por onsets)

El tempo es lo que mueve los fundidos, pero solo llegaba desde el
`AudioProfile` del catalogo (Spotify o estimador). `youber.visuals.tempo` lo
**mide del propio fichero**: sin red, sin dependencias extra y sin subir audio
a ningun sitio.

1. decodifica un tramo a PCM mono de 16 bits con FFmpeg (180 s como mucho),
2. calcula la **envolvente de ataques**: filtro paso-alto por diferencias
   (resalta la percusion), energia por fotograma solapado y solo el *subidon*
   respecto al fotograma anterior,
3. le resta una media movil (umbral adaptativo) y busca el **pulso** por
   autocorrelacion en 60-200 BPM, plegando la ambiguedad de octava hacia
   80-160 BPM (corcheas acentuadas a 150 no son "75 lento").

La `confidence` es la energia que sigue al pulso sobre el total (normalizada):
en el catalogo de prueba, musica mezclada con voz da 0,19-0,78 y un tren de
clics sube a 1,0.

```python
from youber.visuals.tempo import detect_tempo

estimate = await detect_tempo("cancion.wav")
print(estimate.bpm, estimate.confidence)   # 172.3 0.53
```

```bash
# En consola, el CLI imprime el tempo medido antes de elegir el estilo
# make: 172 BPM -> fundido 0,40 s; 94 BPM -> fundido 0,78 s
```

El desfase es determinista (el ataque aparece hasta un fotograma antes del
instante real; `onset_time_offset()` lo documenta): no cambia los intervalos y
por tanto no toca el BPM.

### Cortes al beat

Con el pulso medido, los planos ya no cambian "cada N segundos": cambian
**cuando suena el beat**. `detect_grid()` mide tempo **y fase** (el segundo del
primer beat) y `youber.visuals.prompts` reparte las duraciones con cada corte
en la rejilla:

- **Fase** — se prueban todas las fases posibles y gana la que mas energia de
  ataque acumula sobre la rejilla (`beat_offset`); `phase_strength` dice cuanto
destaca.
- **Duraciones** — `beat_durations()` pone cada corte en `offset + k * intervalo`
  y la ultima toma llega justo al final de la cancion, asi que el video sigue
  cuadrando al milisegundo.
- **Red de seguridad** — si el pulso es flojo (`BeatGrid.reliable()`) o los
  cortes no dejan planos de la duracion minima, se cae al reparto uniforme de
  siempre. Cortar mal es peor que no cortar.
- El fragmento del Short usa `grid.shifted(start)`: al recortar el estribillo
  la rejilla se desplaza con el, y los cortes siguen cayendo en el pulso de
  la cancion original.

```bash
youber-visuals --topic "..." --song cancion.wav --out out/          # cortes al beat
youber-visuals --topic "..." --song cancion.wav --out out/ --no-beat # reparto uniforme
```

El plan JSON lo deja escrito: `beat_bpm`, `beat_offset` y `beat_aligned`.

**Medido sobre el catalogo real** (5 planos en 40 s): el peor desvio entre
corte y beat fue **0,4-1,4 ms** con `Argumentos` (172,3 BPM), `Caos` (94,0),
`Justodelante` (184,6), `StormonYou` (123,0) y `Solootromodo` (117,5).

### Estilo por escena

Un estilo único para todo el vídeo se queda corto cuando la canción tiene
partes muy distintas: la intro floja y el estribillo a tope no piden lo mismo.
Con guion de varias escenas, cada una se mapea a **su tramo de la canción**
(las escenas van en orden y suman la duración del montaje) y se elige un estilo
propio:

- `scene_section_energies` mide la energía (RMS medio) del perfil de
  sonoridad en la ventana de cada escena.
- `signals_for_section` reescribe las señales del tema cambiando solo el eje de
  **energía**: vale el 70 % la del tramo y el 30 % la global
  (`SECTION_ENERGY_WEIGHT`). El resto (valencia, tensión, temas, metadatos) es
  del tema entero: lo que cambia escena a escena es cómo suena esa parte.
- `scene_choices` resuelve un estilo por escena con la misma lógica de siempre
  (`choose_style`), pero **sin rotación de empatados**
  (`SCENE_TIE_EPSILON = 0`): dentro de un vídeo gana el que mejor encaja con el
  tramo; la rotación es para variar vídeos enteros.
- Cada plano hereda el estilo de su escena: el prompt lleva su sufijo
  (`STYLE_SUFFIXES`) y `Shot.style` lo deja escrito.

Si no hay perfil de sonoridad, con una sola escena o con `--no-scene-style`,
todo el vídeo lleva el estilo global de siempre (y el plan lo refleja:
`scene_styles` vacío).

```bash
youber-visuals --topic "..." --song cancion.wav --out out/                 # por escena
youber-visuals --topic "..." --song cancion.wav --out/ --no-scene-style   # uno solo
```

El plan JSON guarda el reparto: `scene_styles`, `scene_reasons` y
`section_energies`.

**Medido sobre una canción sintética** (mitad floja, mitad a tope, dos escenas
de 5 s): la primera sale `minimal` y la segunda `vibrant`, con energías
0,33 y 0,89. Determinista: mismas señales ⇒ mismo reparto.

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

### Movimiento al compás

Con el pulso medido, el zoom/paneo ya no completa un único barrido a lo largo
del plano (que iba "a su aire": rápido en planos cortos, lento en largos):
**cierra su ciclo cada N compases**. El movimiento es una onda triangular —
entra, llega al pico a mitad de ciclo y vuelve — así que respira con la
música en vez de deslizarse una sola vez.

- **Compases por ciclo** (`motion_bars`): los pone el estilo y los corrige la
  energía. `vibrant` respira en ciclos de **2** compases; `cinematic` y `dark`,
  de **4**; `dreamy` y `minimal`, de **8**. Mucha energía (≥ 0,68) acorta el
  ciclo a la mitad; muy poca (≤ 0,32) lo dobla. El resultado se limita a 1, 2,
  4 u 8 compases (cifras musicales).
- **Segundos de ciclo** (`motion_period`): `motion_bars × 4 × 60 / BPM`. Con la
  rejilla del Short, el ciclo viaja con el recorte (`grid.shifted`).
- **Se asume 4/4** (`BEATS_PER_BAR = 4`): del tempo solo no se puede deducir la
  métrica, así que el compás es una convención de montaje.
- Sin pulso (`--no-beat`, o tempo poco firme) todo esto se desactiva y vuelve
  el barrido monótono de siempre.

```bash
# Ciclo automático (estilo + energía)
youber-visuals --topic "..." --song cancion.wav --out out/
# Forzar los compases del ciclo (1, 2, 4 u 8)
youber-visuals --topic "..." --song cancion.wav --out out/ --motion-bars 8
```

El plan JSON lo deja escrito: `motion_bars` y `motion_period` (además de
`motion_offset`, el desplazamiento del ciclo entre planos).

**Medido sobre el catálogo real**: `Fog on glass` → 126 BPM, compás 1,905 s,
2 compases por ciclo (3,81 s) con estilo `vibrant`; los planos de ~11 s dan
casi 3 respiraciones completas cada uno.

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
