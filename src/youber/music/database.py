"""Persistencia del catálogo de música en SQLite.

:class:`MusicDatabase` guarda las pistas (:class:`~youber.music.models.Track`)
en una base de datos SQLite local. Cada operación abre su propia conexión
(volcados pequeños), evitando problemas de concurrencia y de hilos.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from youber.music.models import Mood, Track, TrackSource

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    file_path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    artist TEXT,
    duration REAL NOT NULL,
    genre TEXT,
    moods TEXT NOT NULL DEFAULT '[]',
    bpm INTEGER,
    key TEXT,
    favorite INTEGER NOT NULL DEFAULT 0,
    usage_count INTEGER NOT NULL DEFAULT 0,
    last_used TEXT,
    added_at TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'local',
    external_id TEXT,
    album TEXT,
    artwork_url TEXT,
    preview_url TEXT
);
"""

# Columnas añadidas en versiones posteriores (migración con ALTER TABLE).
_MIGRATIONS: list[tuple[str, str]] = [
    ("source", "TEXT NOT NULL DEFAULT 'local'"),
    ("external_id", "TEXT"),
    ("album", "TEXT"),
    ("artwork_url", "TEXT"),
    ("preview_url", "TEXT"),
]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class MusicDatabase:
    """Base de datos SQLite del catálogo de música."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connections: list[sqlite3.Connection] = []
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Añade las columnas nuevas a bases de datos creadas con esquemas viejos."""
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(tracks)").fetchall()
        }
        for column, definition in _MIGRATIONS:
            if column not in existing:
                conn.execute(f"ALTER TABLE tracks ADD COLUMN {column} {definition}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._connections.append(conn)
        return conn

    # -- Conversión ---------------------------------------------------------

    @staticmethod
    def _to_row(track: Track) -> tuple:
        return (
            track.id,
            str(track.file_path),
            track.title,
            track.artist,
            track.duration,
            track.genre,
            json.dumps([mood.name for mood in track.moods]),
            track.bpm,
            track.key,
            int(track.favorite),
            track.usage_count,
            _iso(track.last_used),
            _iso(track.added_at),
            track.file_hash,
            track.source.value,
            track.external_id,
            track.album,
            track.artwork_url,
            track.preview_url,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Track:
        return Track(
            id=row["id"],
            file_path=Path(row["file_path"]),
            title=row["title"],
            artist=row["artist"],
            duration=row["duration"],
            genre=row["genre"],
            moods=[Mood[name] for name in json.loads(row["moods"])],
            bpm=row["bpm"],
            key=row["key"],
            favorite=bool(row["favorite"]),
            usage_count=row["usage_count"],
            last_used=_parse_iso(row["last_used"]),
            added_at=_parse_iso(row["added_at"]) or datetime.now(),
            file_hash=row["file_hash"],
            source=TrackSource(row["source"] or "local"),
            external_id=row["external_id"],
            album=row["album"],
            artwork_url=row["artwork_url"],
            preview_url=row["preview_url"],
        )

    # -- CRUD ---------------------------------------------------------------

    def add_track(self, track: Track) -> None:
        """Añade una pista al catálogo (ignora si el id ya existe)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tracks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                self._to_row(track),
            )

    def update_track(self, track: Track) -> None:
        """Actualiza una pista existente (por id)."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tracks SET file_path=?, title=?, artist=?, duration=?,
                    genre=?, moods=?, bpm=?, key=?, favorite=?, usage_count=?,
                    last_used=?, added_at=?, file_hash=?, source=?, external_id=?,
                    album=?, artwork_url=?, preview_url=?
                WHERE id=?
                """,
                (
                    str(track.file_path),
                    track.title,
                    track.artist,
                    track.duration,
                    track.genre,
                    json.dumps([mood.name for mood in track.moods]),
                    track.bpm,
                    track.key,
                    int(track.favorite),
                    track.usage_count,
                    _iso(track.last_used),
                    _iso(track.added_at),
                    track.file_hash,
                    track.source.value,
                    track.external_id,
                    track.album,
                    track.artwork_url,
                    track.preview_url,
                    track.id,
                ),
            )

    def get_track(self, track_id: str) -> Track | None:
        """Devuelve una pista por id, o ``None`` si no existe."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        return self._from_row(row) if row else None

    def get_by_path(self, path: str | Path) -> Track | None:
        """Devuelve la pista asociada a una ruta de fichero, o ``None``.

        La ruta se normaliza con :class:`pathlib.Path` para que coincida
        con la almacenada (importante en Windows, donde las barras se
        convierten).
        """
        normalized = str(Path(path))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tracks WHERE file_path=?", (normalized,)
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_external_id(self, source: TrackSource | str, external_id: str) -> Track | None:
        """Devuelve la pista importada de una plataforma por su id externo."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tracks WHERE source=? AND external_id=?",
                (TrackSource(source).value, external_id),
            ).fetchone()
        return self._from_row(row) if row else None

    def delete_track(self, track_id: str) -> bool:
        """Elimina una pista; devuelve ``True`` si existía."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM tracks WHERE id=?", (track_id,))
        return cursor.rowcount > 0

    def list_tracks(self) -> list[Track]:
        """Devuelve todas las pistas del catálogo."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tracks ORDER BY title COLLATE NOCASE"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def count(self) -> int:
        """Número de pistas en el catálogo."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()
        return int(row[0])

    # -- Estado de uso ------------------------------------------------------

    def set_favorite(self, track_id: str, favorite: bool) -> bool:
        """Marca/desmarca una pista como favorita; ``True`` si existía."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE tracks SET favorite=? WHERE id=?", (int(favorite), track_id)
            )
        return cursor.rowcount > 0

    def set_genre(self, track_id: str, genre: str | None) -> bool:
        """Actualiza el género de una pista; ``True`` si existía."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE tracks SET genre=? WHERE id=?", (genre, track_id)
            )
        return cursor.rowcount > 0

    def record_usage(self, track_id: str) -> bool:
        """Incrementa el contador de uso y actualiza ``last_used``."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE tracks SET usage_count=usage_count+1, last_used=? WHERE id=?",
                (_iso(datetime.now()), track_id),
            )
        return cursor.rowcount > 0

    @staticmethod
    def new_id() -> str:
        """Genera un id único para una pista nueva."""
        return uuid.uuid4().hex[:12]

    def close(self) -> None:
        """Cierra todas las conexiones abiertas de la base de datos."""
        for conn in self._connections:
            conn.close()
        self._connections.clear()
