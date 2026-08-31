"""Modelos del programador de tareas (scheduler) de BARF.

Define los tipos de trabajo (:class:`JobType`), los tipos de programación
(:class:`ScheduleType`) y el trabajo programado (:class:`ScheduledJob`) que
el scheduler ejecuta en segundo plano.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class JobType(StrEnum):
    """Tipos de trabajo que el scheduler puede ejecutar."""

    RESEARCH = "research"
    WORKFLOW = "workflow"
    UPLOAD = "upload"
    MUSIC_SCAN = "music_scan"


class ScheduleType(StrEnum):
    """Tipos de programación temporal."""

    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    CRON = "cron"


class ScheduledJob(BaseModel):
    """Un trabajo programado."""

    id: str
    name: str
    job_type: JobType
    schedule_type: ScheduleType
    schedule_value: str  # "09:00" para daily, "monday" para weekly, expresión cron
    params: dict = Field(default_factory=dict)
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = None
