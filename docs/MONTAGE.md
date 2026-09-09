# Montage — Producción de vídeo con OpenMontage (youber-produce)

`youber.montage` es el motor de producción de vídeo de Youber: dado un **vídeo
patrón** (YouTube o local), analiza su estructura y produce un vídeo nuevo
usando **OpenMontage** como motor, con nuestra pista de audio opcional.

```
vídeo patrón → PatternAnalyzer (ffprobe / research.VideoAnalyzer)
             → ProductionPlan (pipeline, audio, salida)
             → OpenMontageAdapter.produce()  → vídeo final (MP4)
```

## CLI

```bash
youber-produce --pattern <youtube-url|video.mp4> [--mode remix|inspired|hybrid]
               [--mood <mood> | --audio <file.mp3>] [--pipeline <name>]
               [--playbook <name>] [--budget <usd>] [-o salida.mp4]
youber-produce --topic "<tema libre>" [--pipeline <name>] [-o salida.mp4]
youber-produce --topic "Python tutorial" --track "<canción>" --sync -o salida.mp4
youber-produce --install-driver
```

Ejemplos:

```bash
youber-produce --topic "Python tutorial" --pipeline screen-demo -o demo.mp4
youber-produce --pattern https://youtu.be/abc123 --mood epica
youber-produce --pattern video.mp4 --audio musica.mp3 --mode remix -o remix.mp4
youber-produce --install-driver   # instala montage_driver/montage.py en el clon
```

- `--topic` produce sin vídeo patrón (no hace falta analizar nada).
- `--install-driver` copia el driver incluido en el repo
  (`montage_driver/montage.py`) a la raíz del clon de OpenMontage y sale.
- `--track <id|título> --sync`: la canción del catálogo pasa a ser la banda
  sonora del montaje y su letra se sincroniza y quema como subtítulos
  (`--style clean|classic|box|minimal`, `--lyrics`, `--whisper`).

## Adapter OpenMontage — contrato de integración

`OpenMontageAdapter` (canónico en `youber/montage/adapter.py`; el paquete
`youber/adapters` es un re-export de compatibilidad) ejecuta OpenMontage como
subproceso con un **driver** `montage.py` en la raíz del clon:

```bash
python montage.py --prompt <texto> --output-dir <dir> \
    [--pipeline <name>] [--playbook <name>] [--budget-usd <n>] \
    [--output <fichero.mp4>] [--duration <s>] [--resolution WxH] \
    [--fps <n>]
```

El driver escribe el vídeo (en `--output` o en `--output-dir`) y termina con
código 0. `produce()` rellena después el `ProductionResult` con datos reales
de ffprobe (duración y resolución).

### Localización del clon (por orden)

1. Parámetro `openmontage_dir` del constructor.
2. Variable de entorno `OPENMONTAGE_DIR`.
3. `<project_dir>/OpenMontage` (convenio histórico).

Se considera un checkout válido si contiene `config.yaml`, `setup.py` o
`render_demo.py`. Si no hay clon o no hay `montage.py`, `produce()` devuelve
`ProductionResult(success=False)` con un error accionable (no falla en
silencio ni inventa rutas).

### Estado real de OpenMontage (verificado 2026-09-09)

OpenMontage (calesthio/OpenMontage) es un sistema **agent-driven**: la
inteligencia la pone un agente (Claude Code, Cursor, etc.) que lee los
manifiestos de pipeline (`pipeline_defs/*.yaml`) y maneja las herramientas
(`tools/`) — *no expone un CLI headless estable tipo `montage.py`*.

**Decisión tomada (2026-09-09): híbrido — Pexels primero, MiniMax H3 opt-in.**
youber incluye un driver real (`montage_driver/montage.py`) que implementa el
contrato usando las tools del propio checkout (`tools.video.pexels_video`) +
FFmpeg, de forma determinista y sin agente LLM. Se instala en el clon con
`youber-produce --install-driver`.

## Driver montage.py (incluido en youber)

`montage_driver/montage.py` es un driver standalone (sin dependencias de
youber) que produce un montaje real:

1. **Clips**: busca y descarga footage real vía `PexelsVideo` (la tool del
   checkout de OpenMontage), con queries derivadas del `--prompt` y keywords
   de sabor por pipeline (`screen-demo` → code/programming/keyboard, etc.).
2. **Montaje**: normaliza cada clip (mismo tamaño/fps/códec, sin audio) y los
   concatena con FFmpeg en un MP4 final validado con ffprobe.

Configuración y modos:

```bash
# Credencial (obligatoria para footage real): añadir al .env del clon
PEXELS_API_KEY=...   # gratis en https://www.pexels.com/api/

# Validar dependencias (0 = listo, 2 = falta algo)
python montage.py --prompt x --output-dir out --self-check

# Validar el pipeline completo SIN red ni API key (clips sintéticos)
python montage.py --prompt "Python tutorial" --output-dir out \
    --pipeline screen-demo --demo --duration 12 --clips 3 --resolution 640x360
```

Nombres de pipeline: acepta los reales de OpenMontage
(`documentary-montage`, `animated-explainer`, `screen-demo`, `hybrid`, ...)
y los alias de youber (`documentary`, `explainer`, `tutorial` → `screen-demo`).
Códigos de salida: 0 OK, 1 error de ejecución, 2 error de configuración.

Para ejecutar desde youber, el clon se localiza por orden: parámetro
`openmontage_dir` → `OPENMONTAGE_DIR` → `<project_dir>/OpenMontage`; el driver
se ejecuta con el Python del `.venv` del clon. Un checkout se considera válido
si contiene `config.yaml`, `setup.py` o `render_demo.py`. Si no hay clon o no
hay `montage.py`, `produce()` devuelve `ProductionResult(success=False)` con un
error accionable (no falla en silencio ni inventa rutas).

## MiniMax H3 vs Pexels (evaluación)

Contexto: sustituir la búsqueda de clips de stock (Pexels) por generación.

| | Pexels (actual) | MiniMax H3 |
|---|---|---|
| Paradigma | Banco de footage real (API) | Modelo generativo multimodal (texto→vídeo, edición, image-animation) |
| Uso en youber | `youber.video.stock` (b-roll por escena) | Provider de *generación*, no de búsqueda |
| Coste | Gratuito con API key | De pago por segundo de vídeo (API MiniMax / ElevenLabs / fal.ai "H3 Max") |
| ToS/contenido | Footage con licencia Pexels | Contenido generado; política de uso del proveedor |
| Encaje | B-roll real para documental/montaje | Escenas sintéticas donde no hay stock |

**Decisión (2026-09-09):** híbrido aprobado — **Pexels como motor de clips por
defecto** (driver `montage.py` real, gratis) y **MiniMax H3 como provider
opt-in** para escenas generadas, pendiente de `MINIMAX_API_KEY`/`FAL_KEY` y
validación de coste. Dentro de OpenMontage, H3 ya está disponible como tool
`minimax_video` / `minimax_fal_video` (ver preflight), pero sin credenciales
el registry lo marca `unavailable`; no se toca el flujo por defecto.

## Tests

`tests/test_montage.py`: unificación de adapters, detección de checkout,
`produce()` con driver fake (subprocess real, sin red), errores sin clon,
e2e del CLI con mocks, y test de integración real con `skipif` si
`OPENMONTAGE_DIR` apunta a un clon con `montage.py`.

`tests/test_montage_produce.py`: contrato del driver empaquetado,
`install_driver()`, y los modos `--topic` / `--install-driver` del CLI
(sin red: el driver real no se ejecuta, necesita `PEXELS_API_KEY` o `--demo`).
