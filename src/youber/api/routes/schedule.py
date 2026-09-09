"""Ruta ``schedule`` — tareas programadas de youber-schedule."""

from __future__ import annotations

from typing import Any

from youber.scheduler.storage import JobStorage


async def list_schedule(params: dict[str, Any]) -> dict[str, Any]:
    """Lista las tareas programadas (youber-schedule)."""
    try:
        jobs = JobStorage().load()
    except Exception:
        jobs = []
    return {
        "count": len(jobs),
        "jobs": [job.model_dump(mode="json") for job in jobs],
    }
