"""Ejecutor de trabajos del scheduler de BARF.

:class:`JobExecutor` ejecuta un :class:`~youber.scheduler.models.ScheduledJob`
a través del runner correspondiente (``jobs.run_job``), registra el resultado
y actualiza los campos ``last_run`` / ``next_run``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from youber.scheduler.jobs import run_job
from youber.scheduler.models import ScheduledJob, ScheduleType


class JobExecutor:
    """Ejecuta trabajos y devuelve su resultado con estado."""

    async def execute(self, job: ScheduledJob) -> dict[str, Any]:
        """Ejecuta el trabajo y devuelve un dict con el resultado.

        Args:
            job: Trabajo a ejecutar (se modifica: ``last_run`` se actualiza).

        Returns:
            ``{"status": "ok"|"error", "result": {...}, "error": str|None}``
        """
        job.last_run = datetime.now()
        try:
            result = await run_job(job)
            logger.info(f"Trabajo {job.name} completado: {result}")
            return {"status": "ok", "result": result, "error": None}
        except Exception as exc:
            logger.error(f"Trabajo {job.name} falló: {exc}")
            return {"status": "error", "result": {}, "error": str(exc)}


def next_run_for(job: ScheduledJob, now: datetime) -> datetime | None:
    """Calcula el próximo instante de ejecución de un trabajo.

    Args:
        job: Trabajo programado.
        now: Instante de referencia.

    Returns:
        El próximo ``datetime``, o ``None`` si no hay (p. ej. un ``once``
        ya pasado).
    """
    value = job.schedule_value.strip()

    if job.schedule_type == ScheduleType.ONCE:
        return _once_next(value, now)

    if job.schedule_type == ScheduleType.DAILY:
        return _daily_next(value, now)

    if job.schedule_type == ScheduleType.WEEKLY:
        return _weekly_next(value, now)

    if job.schedule_type == ScheduleType.CRON:
        return _cron_next(value, now)

    return None


def _once_next(value: str, now: datetime) -> datetime | None:
    """``once``: la fecha se da en ``schedule_value`` (``YYYY-MM-DD HH:MM:SS``)."""
    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return parsed if parsed > now else None


def _daily_next(value: str, now: datetime) -> datetime | None:
    """``daily``: ``schedule_value`` es ``HH:MM``."""
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (ValueError, AttributeError):
        return None
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


_WEEKDAYS = {
    "monday": 0,
    "lunes": 0,
    "tuesday": 1,
    "martes": 1,
    "wednesday": 2,
    "miércoles": 2,
    "miercoles": 2,
    "thursday": 3,
    "jueves": 3,
    "friday": 4,
    "viernes": 4,
    "saturday": 5,
    "sábado": 5,
    "sabado": 5,
    "sunday": 6,
    "domingo": 6,
}


def _weekly_next(value: str, now: datetime) -> datetime | None:
    """``weekly``: ``schedule_value`` es ``monday`` u ``monday 09:00``."""
    parts = value.split()
    day_name = parts[0].lower()
    weekday = _WEEKDAYS.get(day_name)
    if weekday is None:
        return None
    hour, minute = 9, 0
    if len(parts) > 1:
        try:
            hour, minute = (int(part) for part in parts[1].split(":", 1))
        except (ValueError, AttributeError):
            return None

    days_ahead = (weekday - now.weekday()) % 7
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidate = candidate + timedelta(days=days_ahead)
    if candidate <= now:
        candidate = candidate + timedelta(days=7)
    return candidate


# ---------------------------------------------------------------------------
# Cron simplificado (5 campos: minuto hora día-mes mes día-semana)
# ---------------------------------------------------------------------------


def _parse_cron_field(field: str, low: int, high: int) -> set[int] | None:
    """Parsea un campo cron; ``None`` = cualquier valor (*)."""
    if field == "*":
        return None
    values: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            step = int(step_text)
        if part == "*":
            values.update(range(low, high + 1, step))
            continue
        if "-" in part:
            start_text, _, end_text = part.partition("-")
            values.update(range(int(start_text), int(end_text) + 1, step))
        else:
            values.add(int(part))
    return values


def _cron_next(expr: str, now: datetime) -> datetime | None:
    """Calcula el próximo minuto que cumple la expresión cron (5 campos)."""
    fields = expr.split()
    if len(fields) != 5:
        return None
    minute_set = _parse_cron_field(fields[0], 0, 59)
    hour_set = _parse_cron_field(fields[1], 0, 23)
    dom_set = _parse_cron_field(fields[2], 1, 31)
    month_set = _parse_cron_field(fields[3], 1, 12)
    dow_set = _parse_cron_field(fields[4], 0, 6)

    candidate = now.replace(second=0, microsecond=0)
    # Búsqueda acotada hacia delante (evita bucles infinitos).
    for _ in range(366 * 24 * 60):
        candidate = candidate + timedelta(minutes=1)
        if minute_set is not None and candidate.minute not in minute_set:
            continue
        if hour_set is not None and candidate.hour not in hour_set:
            continue
        if dom_set is not None and candidate.day not in dom_set:
            continue
        if month_set is not None and candidate.month not in month_set:
            continue
        if dow_set is not None and candidate.weekday() not in dow_set:
            continue
        return candidate
    return None
