"""Registro de rutas del bridge ``youber.api``.

Cada ruta canónica (``"music.list"``, ``"jobs.submit"``, ...) apunta a un
handler ``async (params: dict) -> Any`` que devuelve datos JSON-safe
(pydantic ``model_dump(mode="json")`` o dicts/listas simples).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from youber.api.routes import discovery, jobs, music, research, schedule, status, uploads

Handler = Callable[[dict[str, Any]], Awaitable[Any]]

ROUTES: dict[str, Handler] = {
    "status": status.get_status,
    "music.list": music.list_tracks,
    "music.search": music.search_tracks,
    "music.lyrics": music.get_lyrics,
    "discovery.search": discovery.search_channels,
    "research.channel": research.channel_info,
    "schedule.list": schedule.list_schedule,
    "jobs.submit": jobs.submit,
    "jobs.status": jobs.status,
    "jobs.history": jobs.history,
    "uploads.status": uploads.uploads_status,
}

__all__ = ["Handler", "ROUTES"]
