"""Fuentes de datos del dashboard de BARF.

Conecta el dashboard con el resto del ecosistema Youber: catálogo de música
(SQLite), scheduler (JSON de trabajos), reportes de investigación (JSON/MD)
e historial de subidas. Cada fuente devuelve datos ya tipados o dicts
listos para las funciones de métricas.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from youber.music.library import MusicLibrary
from youber.music.models import Track
from youber.scheduler.models import ScheduledJob
from youber.scheduler.storage import JobStorage

DEFAULT_REPORTS_DIR = Path("reports")
UPLOAD_HISTORY_FILE = Path.home() / ".youber" / "upload_history.json"


def load_music_tracks(music_dir: str | Path = "music") -> list[Track]:
    """Carga las pistas del catálogo de música (lista vacía si no existe)."""
    library = MusicLibrary(music_dir)
    try:
        return library.all()
    finally:
        library.close()


def load_scheduled_jobs(store_file: str | Path | None = None) -> list[ScheduledJob]:
    """Carga los trabajos programados del scheduler."""
    storage = JobStorage(store_file) if store_file else JobStorage()
    return storage.load()


def load_upload_history(path: str | Path = UPLOAD_HISTORY_FILE) -> list[dict[str, Any]]:
    """Carga el historial de subidas a YouTube (lista vacía si no existe).

    El historial es un JSON opcional que la CLI de subida puede escribir;
    si no existe, el dashboard muestra "sin datos".
    """
    file = Path(path)
    if not file.exists():
        return []
    raw = json.loads(file.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def list_reports(reports_dir: str | Path = DEFAULT_REPORTS_DIR) -> list[dict[str, Any]]:
    """Lista los reportes del directorio (JSON/MD), ordenados por modificación.

    Returns:
        Lista de dicts con ``path``, ``name`` y ``modified`` (datetime).
    """
    directory = Path(reports_dir)
    if not directory.is_dir():
        return []
    files = sorted(
        directory.glob("*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    reports: list[dict[str, Any]] = []
    for path in files:
        if path.is_file() and path.suffix.lower() in {".json", ".md", ".csv"}:
            reports.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "modified": datetime.fromtimestamp(path.stat().st_mtime),
                }
            )
    return reports
