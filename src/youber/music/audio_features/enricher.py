"""Enriquece el catálogo local de música con características de audio.

:class:`CatalogEnricher` recorre el catálogo (:class:`MusicLibrary`), analiza
cada pista con :class:`AudioAnalyzer` (Spotify o estimación local) y guarda
los perfiles en un almacén JSON persistente
(``~/.youber/audio_features.json``) para su uso posterior en
recomendaciones, búsquedas y el dashboard.

Ética: solo metadatos (features de audio), sin descargar ficheros; los
perfiles estimados localmente llevan ``confidence < 1.0``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from youber.music.audio_features.analyzer import AudioAnalyzer
from youber.music.audio_features.models import AudioProfile
from youber.music.library import MusicLibrary
from youber.music.models import Track

DEFAULT_STORE_PATH = Path.home() / ".youber" / "audio_features.json"


class AudioFeatureStore:
    """Almacén JSON persistente de perfiles de audio (por track_id)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_STORE_PATH
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = self._load()

    def get(self, track_id: str) -> AudioProfile | None:
        """Devuelve el perfil de una pista (o ``None`` si no existe)."""
        with self._lock:
            raw = self._data.get(track_id)
            if raw is None:
                return None
            try:
                return AudioProfile.model_validate(raw)
            except Exception:
                return None

    def set(self, profile: AudioProfile) -> None:
        """Guarda el perfil de una pista."""
        with self._lock:
            self._data[profile.track_id] = profile.model_dump(mode="json")
            self._save()

    def all(self) -> list[AudioProfile]:
        """Devuelve todos los perfiles almacenados."""
        with self._lock:
            profiles: list[AudioProfile] = []
            for raw in self._data.values():
                try:
                    profiles.append(AudioProfile.model_validate(raw))
                except Exception:
                    continue
            return profiles

    def has(self, track_id: str) -> bool:
        """Comprueba si existe un perfil para una pista."""
        with self._lock:
            return track_id in self._data

    def clear(self) -> None:
        """Vacía el almacén."""
        with self._lock:
            self._data.clear()
            self._save()

    def stats(self) -> dict[str, int]:
        """Estadísticas del almacén (entradas y tamaño en bytes)."""
        with self._lock:
            size = self.path.stat().st_size if self.path.exists() else 0
            return {"entradas": len(self._data), "bytes": size}

    # -- Persistencia -------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"No se pudo leer el almacén de audio features ({exc})")
            return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(f"No se pudo escribir el almacén de audio features ({exc})")


class EnrichResult:
    """Resumen de una operación de enriquecido del catálogo."""

    def __init__(self) -> None:
        self.total = 0
        self.enriched = 0
        self.errors: list[tuple[str, str]] = []

    def to_dict(self) -> dict[str, Any]:
        """Resumen como dict (para el CLI)."""
        return {
            "total": self.total,
            "enriched": self.enriched,
            "errors": len(self.errors),
        }


class CatalogEnricher:
    """Analiza las pistas del catálogo y guarda sus perfiles de audio.

    Args:
        library: Catálogo local de música.
        analyzer: Analizador de audio (opcional; se crea uno por defecto).
        store: Almacén de perfiles (opcional; JSON en ``~/.youber``).
    """

    def __init__(
        self,
        library: MusicLibrary,
        analyzer: AudioAnalyzer | None = None,
        store: AudioFeatureStore | None = None,
    ) -> None:
        self.library = library
        self.analyzer = analyzer if analyzer is not None else AudioAnalyzer()
        self.store = store if store is not None else AudioFeatureStore()

    async def enrich(self, track: Track) -> AudioProfile | None:
        """Analiza una pista y guarda su perfil. Devuelve el perfil o ``None``."""
        try:
            profile = await self.analyzer.analyze(
                title=track.title,
                artist=track.artist,
                genre=track.genre,
                bpm=track.bpm,
                duration_ms=int(track.duration * 1000) if track.duration else None,
                moods=[mood.value for mood in track.moods],
                track_id=track.id,
            )
            self.store.set(profile)
            return profile
        except Exception as exc:
            logger.warning(f"No se pudo analizar «{track.title}»: {exc}")
            return None

    async def enrich_all(self) -> EnrichResult:
        """Analiza todas las pistas del catálogo (las ya guardadas se saltan).

        Returns:
            Resumen con total, analizadas y errores.
        """
        result = EnrichResult()
        tracks = self.library.all()
        result.total = len(tracks)
        for track in tracks:
            if self.store.has(track.id):
                continue
            profile = await self.enrich(track)
            if profile is not None:
                result.enriched += 1
            else:
                result.errors.append((track.id, track.title))
        return result
