"""Programador de tareas (scheduler) de BARF.

Ejecuta trabajos programados en segundo plano: investigación de canales,
flujo completo de edición, subida a YouTube y escaneo del catálogo de
música. Programación por una vez, diaria, semanal o con expresión cron.

Límites éticos (igual que el resto del framework):

- Solo contenido propio o con licencia; sin spam ni scraping abusivo.
- La automatización no cambia los límites del framework: sigue siendo
  educativo y respetuoso con ToS y robots.txt.
"""

from youber.scheduler.daemon import Daemon, run_daemon
from youber.scheduler.executor import JobExecutor, next_run_for
from youber.scheduler.jobs import JOB_RUNNERS, run_job
from youber.scheduler.models import JobType, ScheduledJob, ScheduleType
from youber.scheduler.scheduler import Scheduler
from youber.scheduler.storage import JobStorage

__all__ = [
    "Daemon",
    "JOB_RUNNERS",
    "JobExecutor",
    "JobStorage",
    "JobType",
    "ScheduleType",
    "ScheduledJob",
    "Scheduler",
    "next_run_for",
    "run_daemon",
    "run_job",
]
