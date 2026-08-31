"""Gestor principal de tareas programadas de BARF.

:class:`Scheduler` orquesta el ciclo de vida de los trabajos: añadir,
listar, eliminar, activar/desactivar, calcular el próximo instante de
ejecución y ejecutar los trabajos pendientes con :class:`JobExecutor`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from youber.scheduler.executor import JobExecutor, next_run_for
from youber.scheduler.models import JobType, ScheduledJob, ScheduleType
from youber.scheduler.storage import JobStorage


class Scheduler:
    """Gestor de trabajos programados persistidos en JSON."""

    def __init__(
        self,
        storage: JobStorage | None = None,
        executor: JobExecutor | None = None,
    ) -> None:
        """Crea el scheduler.

        Args:
            storage: Almacén de trabajos (por defecto, el JSON por defecto).
            executor: Ejecutor de trabajos (por defecto, uno nuevo).
        """
        self.storage = storage or JobStorage()
        self.executor = executor or JobExecutor()

    # -- Gestión de trabajos ------------------------------------------------

    def add_job(
        self,
        name: str,
        job_type: JobType | str,
        schedule_type: ScheduleType | str,
        schedule_value: str,
        params: dict[str, Any] | None = None,
    ) -> ScheduledJob:
        """Crea y persiste un trabajo programado.

        Args:
            name: Nombre descriptivo del trabajo.
            job_type: Tipo de trabajo (``research``, ``workflow``, ...).
            schedule_type: Tipo de programación (``once``, ``daily``, ...).
            schedule_value: Valor según el tipo ("09:00", "monday", cron...).
            params: Parámetros que recibirá el runner.

        Returns:
            El trabajo creado (con ``id`` y ``next_run`` calculado).
        """
        if isinstance(job_type, str):
            job_type = JobType(job_type)
        if isinstance(schedule_type, str):
            schedule_type = ScheduleType(schedule_type)

        job = ScheduledJob(
            id=uuid.uuid4().hex[:8],
            name=name,
            job_type=job_type,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            params=params or {},
        )
        job.next_run = next_run_for(job, datetime.now())
        self.storage.add(job)
        logger.info(f"Trabajo añadido: {job.id} — {job.name} ({job.job_type.value})")
        return job

    def list_jobs(self) -> list[ScheduledJob]:
        """Devuelve todos los trabajos programados."""
        return self.storage.load()

    def get_job(self, job_id: str) -> ScheduledJob | None:
        """Devuelve un trabajo por id."""
        return self.storage.get(job_id)

    def remove_job(self, job_id: str) -> bool:
        """Elimina un trabajo; ``True`` si existía."""
        return self.storage.remove(job_id)

    def set_enabled(self, job_id: str, enabled: bool) -> bool:
        """Activa/desactiva un trabajo; ``True`` si existía."""
        job = self.storage.get(job_id)
        if job is None:
            return False
        job.enabled = enabled
        job.updated_at = datetime.now()
        self.storage.update(job)
        return True

    # -- Ejecución ----------------------------------------------------------

    def due_jobs(self, now: datetime | None = None) -> list[ScheduledJob]:
        """Devuelve los trabajos activos cuyo ``next_run`` ya ha pasado."""
        now = now or datetime.now()
        return [
            job
            for job in self.storage.load()
            if job.enabled and job.next_run is not None and job.next_run <= now
        ]

    async def run_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Ejecuta todos los trabajos pendientes y actualiza su estado.

        Returns:
            Lista de resultados (uno por trabajo ejecutado), con el id del
            trabajo y el estado (``ok``/``error``).
        """
        now = now or datetime.now()
        results: list[dict[str, Any]] = []
        for job in self.due_jobs(now):
            result = await self.executor.execute(job)
            result["job_id"] = job.id
            result["job_name"] = job.name
            results.append(result)

            if job.schedule_type == ScheduleType.ONCE:
                # Los trabajos de una sola vez se desactivan tras ejecutarse.
                job.enabled = False
                job.next_run = None
            else:
                job.next_run = next_run_for(job, datetime.now())
            job.updated_at = datetime.now()
            self.storage.update(job)
        return results

    def next_run(self, job_id: str) -> datetime | None:
        """Recalcula y persiste el próximo instante de un trabajo."""
        job = self.storage.get(job_id)
        if job is None:
            return None
        job.next_run = next_run_for(job, datetime.now())
        job.updated_at = datetime.now()
        self.storage.update(job)
        return job.next_run
