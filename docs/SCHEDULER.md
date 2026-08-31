# Programador de tareas (`youber.scheduler`)

Ejecuta trabajos programados en segundo plano: investigación de canales,
flujo completo de edición, subida a YouTube y escaneo del catálogo de
música. Programación por una vez, diaria, semanal o con expresión cron.

## Estructura

| Módulo | Responsabilidad |
|---|---|
| `models.py` | `JobType`, `ScheduleType`, `ScheduledJob` (pydantic v2) |
| `storage.py` | Persistencia JSON (`JobStorage`, por defecto `~/.youber/schedule.json`) |
| `jobs.py` | Runners: asocia cada `JobType` con su función asíncrona |
| `executor.py` | `JobExecutor` + cálculo de `next_run` (once/daily/weekly/cron) |
| `scheduler.py` | `Scheduler`: añadir/listar/eliminar/activar y ejecutar pendientes |
| `daemon.py` | `run_daemon()` + `Daemon`: servicio en segundo plano |
| `cli.py` | Comando `youber-schedule` |

## CLI

```bash
# Añadir un trabajo diario de investigación
youber-schedule add --name "research @python" --type research --schedule daily --at "09:00" --param channel=@python

# Añadir una subida puntual
youber-schedule add --name "subir vídeo" --type upload --schedule once --at "2026-09-15 10:00:00" --param video=final.mp4 --param title="Mi Video"

# Listar / eliminar / activar / desactivar
youber-schedule list
youber-schedule remove <id>
youber-schedule enable <id>
youber-schedule disable <id>

# Ejecutar los pendientes una vez
youber-schedule run

# Servicio en segundo plano (comprueba cada 60 s)
youber-schedule daemon --interval 60
```

## Tipos de trabajo (`JobType`)

| Tipo | Qué hace | Params |
|---|---|---|
| `research` | Investiga un canal | `channel`, `max_videos` |
| `workflow` | Flujo completo (investigación + edición) | `channel`, `demo`, `output_dir` |
| `upload` | Sube un vídeo a YouTube | `video`, `title`, `description`, `tags` |
| `music_scan` | Escanea el catálogo de música | `library` |

## Tipos de programación (`ScheduleType`)

| Tipo | `schedule_value` | Ejemplo |
|---|---|---|
| `once` | `YYYY-MM-DD HH:MM:SS` | `2026-09-15 10:00:00` (se desactiva al ejecutarse) |
| `daily` | `HH:MM` | `09:00` |
| `weekly` | `monday` o `monday 09:00` | `monday 09:00` (es/inglés) |
| `cron` | expresión cron de 5 campos | `30 0 * * *` (min hora día-mes mes día-semana) |

## Uso desde código

```python
import asyncio
from youber.scheduler import Scheduler

async def main():
    scheduler = Scheduler()
    job = scheduler.add_job(
        name="research diario",
        job_type="research",
        schedule_type="daily",
        schedule_value="09:00",
        params={"channel": "@python"},
    )
    print(job.id, job.next_run)

    # Ejecutar los pendientes (devuelve resultados ok/error)
    results = await scheduler.run_due()
    print(results)

asyncio.run(main())
```

## Daemon en segundo plano

```python
import asyncio
from youber.scheduler import Scheduler, Daemon

async def main():
    daemon = Daemon(Scheduler(), interval=60)
    await daemon.start()   # bucle en tarea asíncrona
    await asyncio.sleep(3600)
    await daemon.stop()    # parada limpia

asyncio.run(main())
```

## Ética

El scheduler automatiza **trabajos legítimos del framework** (investigación de
datos públicos, edición y subida de contenido propio). Los mismos límites
aplican: sin spam, sin scraping abusivo, respetando ToS y robots.txt.
