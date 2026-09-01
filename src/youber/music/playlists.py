"""Playlists locales creadas desde el dashboard o el CLI.

:class:`PlaylistStore` guarda playlists en un JSON persistente
(``~/.youber/playlists.json``) con el mismo patrón que
:class:`AudioFeatureStore` (lock + load/save). Cada playlist es solo
metadatos: nombre, descripción, ids de pistas del catálogo y marca de
tiempo. No descarga ni almacena contenido.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

DEFAULT_STORE_PATH = Path.home() / ".youber" / "playlists.json"


class Playlist(BaseModel):
    """Una playlist local: nombre + ids de pistas del catálogo."""

    id: str
    name: str
    description: str = ""
    track_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PlaylistStore:
    """Almacén JSON persistente de playlists (por id)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_STORE_PATH
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = self._load()

    def all(self) -> list[Playlist]:
        """Devuelve todas las playlists (por orden de creación)."""
        with self._lock:
            playlists: list[Playlist] = []
            for raw in self._data.values():
                try:
                    playlists.append(Playlist.model_validate(raw))
                except Exception:
                    continue
            playlists.sort(key=lambda p: p.created_at)
            return playlists

    def get(self, playlist_id: str) -> Playlist | None:
        """Devuelve una playlist por id (o ``None``)."""
        with self._lock:
            raw = self._data.get(playlist_id)
            if raw is None:
                return None
            try:
                return Playlist.model_validate(raw)
            except Exception:
                return None

    def create(self, name: str, track_ids: list[str], description: str = "") -> Playlist:
        """Crea una playlist nueva (id derivado del nombre + timestamp)."""
        import hashlib

        seed = f"{name}|{datetime.now(UTC).isoformat()}"
        playlist_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
        playlist = Playlist(
            id=playlist_id,
            name=name.strip(),
            description=description.strip(),
            track_ids=list(dict.fromkeys(track_ids)),  # dedupe manteniendo orden
        )
        with self._lock:
            self._data[playlist.id] = playlist.model_dump(mode="json")
            self._save()
        return playlist

    def delete(self, playlist_id: str) -> bool:
        """Elimina una playlist. Devuelve ``True`` si existía."""
        with self._lock:
            if playlist_id not in self._data:
                return False
            del self._data[playlist_id]
            self._save()
            return True

    def stats(self) -> dict[str, int]:
        """Estadísticas del almacén (playlists y tamaño en bytes)."""
        with self._lock:
            size = self.path.stat().st_size if self.path.exists() else 0
            return {"playlists": len(self._data), "bytes": size}

    # -- Persistencia -------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"No se pudo leer el almacén de playlists ({exc})")
            return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(f"No se pudo escribir el almacén de playlists ({exc})")
