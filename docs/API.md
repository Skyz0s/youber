# API — Bridge JSON de Youber (youber-api)

`youber.api` expone las funcionalidades de Youber como **JSON puro** para el
dashboard (plugin de Control UI, Fase 2) y para scripts. Un dispatcher
central (`youber.api.server.handle`) enruta peticiones canónicas a handlers
por dominio (`youber.api.routes.*`).

```
CLI (youber-api) ──┐
                   ├→ server.handle(route, params) → routes/{status,music,...}
plugin (Fase 2) ───┘        {"ok": true, "data": ...} | {"ok": false, "error": ...}
```

Siempre imprime JSON en stdout. Exit 0 si `ok`, 1 si error.

## Comandos

```bash
youber-api status --json
youber-api music list --limit 10 --json
youber-api music search "Bohemian" --json
youber-api music lyrics "Bohemian Rhapsody" --json
youber-api discovery search "python" --category tecnología --limit 10 --json
youber-api research channel "@python" --limit 10 --json
youber-api schedule list --json
youber-api jobs submit --type produce --topic "Python" \
    --pipeline screen-demo --track "Bohemian Rhapsody" --sync --json
youber-api jobs status <job-id> --json
youber-api jobs history --limit 20 --json
youber-api uploads status --json
```

## Rutas (equivalencia HTTP de Fase 2)

| Ruta | Handler | Descripción |
| --- | --- | --- |
| `status` | `routes/status.py` | Catálogo, schedule, jobs activos, credenciales (solo booleanos) |
| `music.list` | `routes/music.py` | Pistas del catálogo (`--library`, `--limit`) |
| `music.search` | `routes/music.py` | Búsqueda por texto (título/artista/género) |
| `music.lyrics` | `routes/music.py` | Letra de una pista: ID exacto o texto; sidecar junto al audio |
| `discovery.search` | `routes/discovery.py` | Canales por texto/categoría (`--mode auto\|api\|html\|demo`) |
| `research.channel` | `routes/research.py` | Datos públicos de un canal (`--mode auto\|html\|api`) |
| `schedule.list` | `routes/schedule.py` | Tareas programadas (youber-schedule) |
| `jobs.submit` | `routes/jobs.py` | Lanza un job produce/workflow/upload (worker detached) |
| `jobs.status` | `routes/jobs.py` | Estado de un job por id |
| `jobs.history` | `routes/jobs.py` | Historial de jobs |
| `uploads.status` | `routes/uploads.py` | Estado de subida a YouTube (booleanos, sin secretos) |

## Jobs de larga duración

`jobs submit` construye el argv con una **lista blanca de flags por tipo**
(nunca shell; valores que empiezan por `-` se rechazan), guarda el registro en
`~/.youber/jobs/<id>.json` y lanza un **worker detached**
(`python -m youber.api.routes.jobs <id>`) que ejecuta el comando, vuelca
stdout+stderr a `<job_dir>/run.log` y actualiza el registro
(`queued → running → done|failed`). El dashboard hace polling con
`jobs status`. Tipos: `produce` (requiere `--topic`/`--pattern`), `workflow`
(`--channel`/`--demo`), `upload` (`--video --title`).

Seguridad: los secretos nunca salen en las respuestas (solo presencia
booleanos); el directorio de jobs se puede redirigir con `YOUBER_JOBS_DIR`.

## Uso como librería

```python
from youber.api.server import handle

envelope = await handle("music.list", {"library": "music", "limit": 10})
# {"ok": True, "data": {"count": ..., "tracks": [...]}}
```

## Tests

`tests/test_api.py`: dispatcher, rutas offline (catálogo vacío en tmp, modo
demo de discovery, mocks para research/schedule), CLI smoke.
`tests/test_api_jobs.py`: whitelist de `build_command`, submit/status/history
con spawn mockeado, y `run_job` con subprocesos reales triviales.
