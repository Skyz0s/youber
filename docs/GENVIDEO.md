# Generación de vídeo local (`youber.genvideo`)

Genera clips de vídeo **en esta máquina**, de noche y sin depender de nadie:
ComfyUI (API HTTP local) con **Wan 2.2 TI2V-5B** y la receta que se midió en el
spike (`C:\Users\bypau\ai\spike\RESULTS.md`). Los backends externos quedan como
opción explícita, apagados por defecto.

## La receta (medida, no supuesta)

| Ajuste | Valor | Por qué |
| --- | --- | --- |
| Pesos | `wan2.2_ti2v_5B_fp16.safetensors` | el GGUF Q8 salió **un 10 % más lento** |
| LoRA | `wan22_ti2v_5b_turbo_lora_rank64_fp16` @1.0 | sin ella hacen falta ~20 steps |
| Decodificación | `VAEDecodeTiled` (tile 256, solape 64) | a 720p el cuello era el VAE: 5× más rápido y −4,7 GB de pico |
| Steps | **8** a 720p · **4** a 480p | con 4 steps a 720p la imagen sale plana y oscura (detalle 9-21 frente a ~40) |
| cfg / sampler | 1.0 · `euler`/`simple`, shift 8 | lo que mejor salió con la LoRA Turbo |
| Frames | 121 @ 24 fps ≈ 5 s (el trozo del spike); desde un guion, los de cada plano, ajustados a `4k+1` y acotados a 2-10 s | Wan 2.2 comprime el tiempo 4×: la longitud del latente tiene que ser `4k+1` |
| Multiplicador del latente | 1.0 | el truco del ×0,8 no mejora el detalle medido |

Coste por clip en la RTX 3050 (8 GB): **~9,5 min a 720p**, **~2,8 min a 480p** para
121 frames (5 s). El coste crece con los frames, así que un clip de 9 s cuesta
~1,8× uno de 5 s. En una noche de 8 h: **~50 clips de 5 s a 720p** (≈4 min de
metraje) o **~170 a 480p**.

## Qué hace el módulo

- **`models.py`** — `GenConfig` (la receta, con los presets `720p`/`480p`),
  `ClipRequest` (un clip autocontenido, con su propia configuración para que la
  cola se pueda reanudar), `ClipQuality` y `BatchReport`.
- **`graph.py`** — traduce un clip al grafo API de ComfyUI.
- **`client.py`** — `ComfyUIClient` (`/prompt`, `/history`, `/view`,
  `/system_stats`, `/object_info`) y `StubClient` (MP4 sintético con FFmpeg,
  sin GPU) para probar el flujo entero en CI.
- **`queue.py`** — cola **persistida** en JSON con escritura atómica y
  reanudación: lo que quedó en `running` vuelve a `pending` al arrancar.
- **`verify.py`** — verificación de cada clip con `ffprobe` (duración,
  resolución, fps, frames) y `ffmpeg` (brillo, **detalle** y **movimiento**),
  con los umbrales medidos.
- **`runner.py`** — `NightlyRunner`: guion → prompts por escena (guion visual de
  `youber.visuals.beats`) → cola → generación → verificación → reintento con más
  steps → manifiesto. Cada clip se pide con la duración de su plano en el
  montaje (frames `4k+1`, 2-10 s), no con 5 s fijos.
- **`cli.py`** — `youber-genvideo`.

## Uso

```bash
# ¿Está listo el backend y qué cabe esta noche?
youber-genvideo check

# Encolar los planos de un guion (JSON de youber-script)
youber-genvideo enqueue --script guion.json --preset 720p

# Lote nocturno: de 22:00 a 07:00, con informe
youber-genvideo run --start 22:00 --end 07:00 --report reports/

# Todo el flujo sin GPU ni ComfyUI (útil para probar la máquina)
youber-genvideo run --topic "prueba" --demo --max-clips 2

# ¿Este clip sirve?
youber-genvideo verify clips/001-plano-abc123.mp4
```

En Python:

```python
from youber.genvideo import GenConfig, JobQueue, Resolution, run_nightly
from youber.genvideo.runner import requests_from_script

config = GenConfig.for_resolution(Resolution.HD)
report = await run_nightly(script=guion, config=config, end=dt_time(7, 0))
print(report.to_markdown())
```

## ComfyUI: arranque y parada automáticos

El motor no tiene por qué estar levantado todo el día: tenerlo abierto mantiene
los modelos cargados en la GPU (≈2,8 GB de los 8 GB de una RTX 3050) aunque no
haga nada. Por eso lo gestiona el propio lote (`youber.genvideo.service`):

- si ComfyUI no responde, lo **levanta** (proceso desprendido, salida en
  `~/.youber/genvideo/comfyui.log`) y espera a que el API conteste (hasta 5 min:
  cargar 10 GB de pesos tarda);
- si ya estaba levantado, **no lo toca** (y no lo para al terminar);
- al acabar, **para lo que arrancó él**, así que la GPU queda libre;
- si no hay nada pendiente en la cola, ni lo levanta (volver a lanzar el mismo
  guion no despierta la GPU).

Ajustes: `YOUBER_COMFYUI_DIR` (por defecto `~/ai/ComfyUI`) y las opciones
`--no-manage-comfyui` / `--keep-comfyui` / `--comfyui-dir`.

## Rutina nocturna (22:00 → 07:00)

El lote se lanza a las 22:00 desde el *cron* del gateway con el guion del día, y
a las 07:05 otro trabajo manda el resumen (clips buenos, metraje, minutos de GPU
y por qué paró). El propio lote se encarga de la ventana horaria, de no empezar
un clip que no quepa antes del cierre y de la suspensión del equipo.

Ejemplo de lanzamiento manual equivalente::

```bash
youber-genvideo run --script state/genvideo/guion.json --preset 720p \
    --start - --end 07:00 -o state/genvideo/clips --report reports/genvideo \
    --state state/genvideo/queue.json
```

## Verificación: por qué existe

Generar no garantiza nada. Con Turbo a **4 steps y 720p** ComfyUI responde
`success` pero la imagen sale **plana y oscura**: el detalle medido cae a 9-21
frente a ~40-54 con 8 steps. Como eso no da error, el runner **mide** cada
clip y decide:

- `detalle < 25` → imagen plana · `brillo` fuera de 15-240 → oscuro/quemado ·
  `movimiento < 1` → clip congelado;
- si falla y quedan intentos, **sube los steps** (8 → 16) y lo regenera;
- si vuelve a fallar, lo marca como descartado con el motivo, en vez de
  dejarlo pasar.

## Cola y estado

- Cola: `~/.youber/genvideo/queue.json` (o `YOUBER_GENVIDEO_DIR`).
- Clips: `~/.youber/genvideo/clips` (o `-o`).
- Manifiesto y resumen: `lote-<id>.json` y `lote-<id>.md` (`--report`).
- El id de cada clip es **determinista** (prompt + semilla + ancho + steps):
  volver a lanzar el mismo lote no duplica trabajo.

## Enganche con el scheduler

```bash
youber-schedule add --name "b-roll nocturno" --type genvideo --schedule daily \
  --value 22:00 --params '{"script": "guion.json", "preset": "720p", "end": "07:00", "report_dir": "reports"}'
```

El runner del scheduler llama a `run_nightly` con esos parámetros y devuelve
clips generados, metraje y minutos de GPU.

## Lo que este módulo **no** hace

- No descarga ni usa material de terceros sin permiso, ni evade sistemas de
  seguridad.
- No sube nada a ninguna plataforma: para eso está `youber-upload`, y siempre
  con la propiedad de la cuenta.
- No manda nada fuera de casa: la generación es local por defecto.
