"""Persistencia de trabajos programados (JSON).

:class:`JobStorage` guarda los :class:`~youber.scheduler.models.ScheduledJob`
en un fichero JSON (por defecto ``~/.youber/schedule.json``). Cada operación
reescribe el fichero completo: el volumen de trabajos es pequeño.
"""

from __future__ import annotations

import json
from pathlib import Path

from youber.scheduler.models import ScheduledJob

DEFAULT_STORAGE_FILE = Path.home() / ".youber" / "schedule.json"


class JobStorage:
    """Almacén de trabajos programados en un fichero JSON."""

    def __init__(self, path: str | Path = DEFAULT_STORAGE_FILE) -> None:
        """Crea el almacén.

        Args:
            path: Ruta del fichero JSON (por defecto ``~/.youber/schedule.json``).
        """
        self.path = Path(path)

    def load(self) -> list[ScheduledJob]:
        """Carga todos los trabajos guardados (vacío si no existe el fichero)."""
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [ScheduledJob.model_validate(item) for item in raw]

    def _write(self, jobs: list[ScheduledJob]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [job.model_dump(mode="json") for job in jobs]
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add(self, job: ScheduledJob) -> ScheduledJob:
        """Añade un trabajo y lo persiste."""
        jobs = self.load()
        jobs.append(job)
        self._write(jobs)
        return job

    def get(self, job_id: str) -> ScheduledJob | None:
        """Devuelve un trabajo por id (o ``None``)."""
        for job in self.load():
            if job.id == job_id:
                return job
        return None

    def update(self, job: ScheduledJob) -> bool:
        """Actualiza un trabajo existente; ``True`` si existía."""
        jobs = self.load()
        for index, existing in enumerate(jobs):
            if existing.id == job.id:
                jobs[index] = job
                self._write(jobs)
                return True
        return False

    def remove(self, job_id: str) -> bool:
        """Elimina un trabajo; ``True`` si existía."""
        jobs = self.load()
        remaining = [job for job in jobs if job.id != job_id]
        if len(remaining) == len(jobs):
            return False
        self._write(remaining)
        return True
