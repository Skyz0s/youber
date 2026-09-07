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
```

Ejemplos:

```bash
youber-produce --pattern https://youtu.be/abc123 --mood epica
youber-produce --pattern video.mp4 --audio musica.mp3 --mode remix -o remix.mp4
```

## Adapter OpenMontage — contrato de integración

`OpenMontageAdapter` (canónico en `youber/montage/adapter.py`; el paquete
`youber/adapters` es un re-export de compatibilidad) ejecuta OpenMontage como
subproceso con un **driver** `montage.py` en la raíz del clon:

```bash
python montage.py --prompt <texto> --output-dir <dir> \
    [--pipeline <name>] [--playbook <name>] [--budget-usd <n>] \
    [--output <fichero.mp4>]
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

### Estado real de OpenMontage (verificado 2026-09-07)

OpenMontage (calesthio/OpenMontage) es un sistema **agent-driven**: la
inteligencia la pone un agente (Claude Code, Cursor, etc.) que lee los
manifiestos de pipeline (`pipeline_defs/*.yaml`) y maneja las ~52 herramientas
(`tools/`) — *no expone todavía un CLI headless estable tipo `montage.py`*.
Por eso la integración se define como contrato de driver: cuando el clon
disponga de un `montage.py` con esa interfaz, `youber-produce` funciona sin
cambios. Mientras tanto, los tests ejercitan el subprocess con drivers fake.

## MiniMax H3 vs Pexels (evaluación)

Contexto: sustituir la búsqueda de clips de stock (Pexels) por generación.

| | Pexels (actual) | MiniMax H3 |
|---|---|---|
| Paradigma | Banco de footage real (API) | Modelo generativo multimodal (texto→vídeo, edición, image-animation) |
| Uso en youber | `youber.video.stock` (b-roll por escena) | Provider de *generación*, no de búsqueda |
| Coste | Gratuito con API key | De pago por segundo de vídeo (API MiniMax / ElevenLabs / fal.ai "H3 Max") |
| ToS/contenido | Footage con licencia Pexels | Contenido generado; política de uso del proveedor |
| Encaje | B-roll real para documental/montaje | Escenas sintéticas donde no hay stock |

**Conclusión:** H3 no es un *drop-in* de Pexels (buscar ≠ generar) y añade
coste por minuto; sí es una alternativa real para escenas generadas y para el
pipeline `documentary-montage` de OpenMontage, que ya orquesta providers
(minimax_video, pexels_video, etc.) con scoring. **Recomendación:** mantener
Pexels/Pixabay como stock por defecto y añadir MiniMax H3 como provider
opt-in (requiere `MINIMAX_API_KEY` y validación de coste), sin tocar el flujo
por defecto. Pendiente de aprobación.

## Tests

`tests/test_montage.py`: unificación de adapters, detección de checkout,
`produce()` con driver fake (subprocess real, sin red), errores sin clon,
e2e del CLI con mocks, y test de integración real con `skipif` si
`OPENMONTAGE_DIR` apunta a un clon con `montage.py`.
