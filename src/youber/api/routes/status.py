"""Ruta ``status`` — estado general de Youber para el dashboard.

Solo devuelve **presencia** de credenciales (booleanos), nunca los valores.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from youber.api.routes.jobs import count_active
from youber.api.routes.music import resolve_library_dir
from youber.music.library import MusicLibrary
from youber.scheduler.storage import JobStorage

DEFAULT_LIBRARY = Path("music")


def _env_set(*names: str) -> bool:
    return any(bool(os.environ.get(name, "").strip()) for name in names)


def _music_track_count(library_dir: str | Path) -> int:
    try:
        library = MusicLibrary(library_dir)
        try:
            return library.count()
        finally:
            library.close()
    except Exception:
        return 0


async def get_status(params: dict[str, Any]) -> dict[str, Any]:
    """Estado agregado: catálogo, tareas programadas, jobs y credenciales."""
    library_dir = resolve_library_dir(params)

    schedule_jobs = 0
    schedule_enabled = 0
    try:
        for job in JobStorage().load():
            schedule_jobs += 1
            if job.enabled:
                schedule_enabled += 1
    except Exception:
        pass

    queued, running = count_active()

    return {
        "music": {
            "library": str(library_dir),
            "tracks": _music_track_count(library_dir),
        },
        "schedule": {"jobs": schedule_jobs, "enabled": schedule_enabled},
        "jobs": {"queued": queued, "running": running},
        "providers": {
            "pexels": _env_set("PEXELS_API_KEY"),
            "minimax": _env_set("MINIMAX_API_KEY"),
            "spotify": _env_set("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"),
            "youtube_research": _env_set("YOUTUBE_API_KEY"),
            "youtube_upload": _env_set("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
            "openmontage": _env_set("OPENMONTAGE_DIR"),
        },
        "system": {
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": shutil.which("ffprobe") is not None,
        },
    }
