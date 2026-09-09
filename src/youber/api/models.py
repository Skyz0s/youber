"""Modelos del bridge ``youber.api`` (respuestas JSON del dashboard).

Errores, estados de jobs y registros de ejecución. Las respuestas de datos
usan los modelos pydantic de los módulos de dominio (Track, ChannelHit,
ScheduledJob, ...) serializados con ``model_dump(mode="json")``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class ApiError(RuntimeError):
    """Error controlado del bridge: mensaje JSON-safe para el dashboard."""


class JobStatus(StrEnum):
    """Estado de un job de larga duración."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobRecord(BaseModel):
    """Registro persistente de un job lanzado desde el dashboard.

    Se guarda como JSON en ``~/.youber/jobs/<id>.json``; ``command`` es el
    argv completo (construido solo con flags de una lista blanca, nunca con
    shell) que ejecuta el runner.
    """

    id: str
    type: str  # produce | workflow | upload
    status: JobStatus = JobStatus.QUEUED
    params: dict[str, object] = Field(default_factory=dict)
    command: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    exit_code: int | None = None
    log: str = ""  # cola del log (últimos KB)
    output_path: Path | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
