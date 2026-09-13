"""Gestor del catálogo de música de BARF.

:class:`MusicLibrary` une las piezas del módulo: base de datos SQLite
(:mod:`youber.music.database`), escaneo de ficheros (:mod:`youber.music.scanner`)
y búsqueda por estado de ánimo (:mod:`youber.music.matcher`).

Uso típico:

.. code-block:: python

    library = MusicLibrary("~/musica")
    summary = await library.scan()
    sugerencias = library.suggest(mood=Mood.RELAXING, limit=3)
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from youber.music.database import MusicDatabase
from youber.music.lyrics_analyzer import LyricsAnalysis, LyricsAnalyzer
from youber.music.matcher import search_tracks, suggest_tracks
from youber.music.models import Mood, Track
from youber.music.scanner import scan_library


class MusicLibrary:
    """Catálogo local de música: escaneo, búsqueda y sugerencias."""

    def __init__(self, library_dir: str | Path, db_path: str | Path | None = None) -> None:
        """Crea el catálogo sobre un directorio de música.

        Args:
            library_dir: Directorio donde viven los ficheros de audio.
            db_path: Ruta de la base de datos SQLite. Por defecto se crea
                ``<library_dir>/.music.db``.
        """
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.db = MusicDatabase(db_path or self.library_dir / ".music.db")
        logger.debug(f"MusicLibrary lista: {self.library_dir}")

    # -- Escaneo ------------------------------------------------------------

    async def scan(self, lyrics_dir: str | Path | None = None) -> dict[str, int]:
        """Escanea el directorio y sincroniza el catálogo con la base de datos.

        Args:
            lyrics_dir: Directorio donde buscar archivos de letras para análisis temático (opcional).

        Returns:
            Resumen con contadores: ``added``, ``updated``, ``unchanged``,
            ``removed`` y ``errors``.
        """
        return await scan_library(self.library_dir, self.db, lyrics_dir=lyrics_dir)

    # -- Búsqueda -----------------------------------------------------------

    def search(
        self,
        mood: Mood | None = None,
        genre: str | None = None,
        text: str | None = None,
        favorite: bool | None = None,
        bpm_min: int | None = None,
        bpm_max: int | None = None,
        lyrical_theme: str | None = None,
        lyrical_sentiment: str | None = None,
    ) -> list[Track]:
        """Busca pistas en el catálogo por mood, género, texto, letra o favorito."""
        return search_tracks(
            self.db.list_tracks(),
            mood=mood,
            genre=genre,
            text=text,
            favorite=favorite,
            bpm_min=bpm_min,
            bpm_max=bpm_max,
            lyrical_theme=lyrical_theme,
            lyrical_sentiment=lyrical_sentiment,
        )

    def suggest(
        self,
        mood: Mood | None = None,
        text: str | None = None,
        limit: int = 5,
        lyrical_theme: str | None = None,
    ) -> list[Track]:
        """Sugiere pistas para un estado de ánimo/tema (favoritas y menos usadas primero)."""
        return suggest_tracks(
            self.db.list_tracks(),
            mood=mood,
            text=text,
            limit=limit,
            lyrical_theme=lyrical_theme,
        )

    def lyrics(self, track_id: str, lyrics_dir: str | Path) -> LyricsAnalysis | None:
        """Analiza la letra de una pista desde un directorio local (o ``None``)."""
        track = self.db.get_track(track_id)
        if track is None:
            return None
        return LyricsAnalyzer().analyze_track_lyrics(track, Path(lyrics_dir))

    # -- Acceso directo -----------------------------------------------------

    def get(self, track_id: str) -> Track | None:
        """Devuelve una pista por id."""
        return self.db.get_track(track_id)

    def all(self) -> list[Track]:
        """Devuelve todas las pistas del catálogo."""
        return self.db.list_tracks()

    def count(self) -> int:
        """Número de pistas del catálogo."""
        return self.db.count()

    # -- Estado de uso ------------------------------------------------------

    def mark_favorite(self, track_id: str, favorite: bool = True) -> bool:
        """Marca/desmarca una pista como favorita."""
        return self.db.set_favorite(track_id, favorite)

    def record_usage(self, track_id: str) -> bool:
        """Registra un uso de la pista (incrementa contador y ``last_used``)."""
        return self.db.record_usage(track_id)

    def remove(self, track_id: str) -> bool:
        """Elimina una pista del catálogo."""
        return self.db.delete_track(track_id)

    def close(self) -> None:
        """Cierra el catálogo (no-op; las conexiones se abren por operación)."""
        self.db.close()


def find_track(library: MusicLibrary, query: str) -> Track | None:
    """Resuelve una pista del catálogo por ID exacto o por texto libre.

    Args:
        library: catálogo abierto (:class:`MusicLibrary`).
        query: ID de pista o texto (título/artista/género).

    Returns:
        La pista encontrada, o ``None`` si no hay coincidencias.
    """
    query = (query or "").strip()
    if not query:
        return None
    exact = library.get(query)
    if exact is not None:
        return exact
    matches = library.search(text=query)
    return matches[0] if matches else None
