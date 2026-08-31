"""Caché de resultados de búsqueda (JSON con TTL, uso educativo).

Guarda los resultados de :class:`ChannelSearcher` en un fichero JSON bajo
``~/.youber/cache/discovery.json`` con tiempo de expiración por entrada,
para no repetir peticiones a YouTube al investigar el mismo nicho.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

DEFAULT_CACHE_PATH = Path.home() / ".youber" / "cache" / "discovery.json"
DEFAULT_TTL = 3600  # 1 hora


class DiscoveryCache:
    """Caché JSON simple con TTL por entrada y acceso thread-safe.

    Args:
        path: Ruta del fichero de caché (por defecto
            ``~/.youber/cache/discovery.json``).
        default_ttl: Segundos de validez por defecto.
    """

    def __init__(
        self,
        path: Path | None = None,
        default_ttl: int = DEFAULT_TTL,
    ) -> None:
        self.path = path or DEFAULT_CACHE_PATH
        self.default_ttl = default_ttl
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = self._load()

    # -- API pública -------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Devuelve el valor almacenado si existe y no ha expirado."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at = entry.get("expires_at", 0)
            if time.time() > expires_at:
                self._data.pop(key, None)
                return None
            return entry.get("value")

    def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Almacena un valor con TTL en segundos (por defecto el de la clase)."""
        with self._lock:
            self._data[key] = {
                "value": value,
                "expires_at": time.time() + (ttl if ttl is not None else self.default_ttl),
            }
            self._save()

    def delete(self, key: str) -> bool:
        """Elimina una clave. Devuelve ``True`` si existía."""
        with self._lock:
            existed = self._data.pop(key, None) is not None
            if existed:
                self._save()
            return existed

    def clear(self) -> None:
        """Vacía la caché completa."""
        with self._lock:
            self._data.clear()
            self._save()

    def stats(self) -> dict[str, int]:
        """Estadísticas: entradas totales, válidas, expiradas y tamaño (bytes)."""
        with self._lock:
            now = time.time()
            expired = sum(
                1 for entry in self._data.values() if entry.get("expires_at", 0) <= now
            )
            size = self.path.stat().st_size if self.path.exists() else 0
            return {
                "entradas": len(self._data),
                "validas": len(self._data) - expired,
                "expiradas": expired,
                "bytes": size,
            }

    # -- Persistencia ------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        """Carga el fichero JSON (o devuelve vacío si no existe/corrupto)."""
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
            logger.warning(f"Caché de discovery con formato inesperado: {self.path}")
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"No se pudo leer la caché de discovery ({exc})")
            return {}

    def _save(self) -> None:
        """Persiste la caché (crea directorios si hace falta)."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(f"No se pudo escribir la caché de discovery ({exc})")
