"""Persistencia del registro de decisiones en SQLite.

:class:`JournalStorage` guarda las decisiones (:class:`DecisionRecord`) y sus
métricas posteriores (:class:`PerformanceSnapshot`) en una base de datos
SQLite local. Cada operación abre su propia conexión (volcados pequeños), igual
que hace :class:`youber.music.database.MusicDatabase`, para no tener problemas
de hilos ni de concurrencia.

Las filas guardan el modelo completo serializado en JSON (para no perder
ningún campo) **y** unas pocas columnas «calientes» (``created_at``,
``video_id``, ``views``, ``ctr``...) para poder filtrar sin deserializar.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from youber.journal.models import DecisionRecord, PerformanceSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    source_channel TEXT,
    video_id TEXT,
    algorithm_version TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_video ON decisions(video_id);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);

CREATE TABLE IF NOT EXISTS performance (
    decision_id TEXT NOT NULL,
    window TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    views INTEGER,
    impressions INTEGER,
    ctr REAL,
    avg_view_percentage REAL,
    subscribers_gained INTEGER,
    data TEXT NOT NULL,
    PRIMARY KEY (decision_id, window, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_performance_decision ON performance(decision_id);
"""


def _iso(value: datetime | None) -> str | None:
    """Serializa una fecha a ISO-8601 (o ``None``)."""
    return value.isoformat() if value is not None else None


class JournalStorage:
    """Almacén SQLite de decisiones y métricas de rendimiento."""

    def __init__(self, db_path: str | Path) -> None:
        """Crea (si hace falta) la base de datos del journal.

        Args:
            db_path: Ruta del fichero SQLite.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Abre una conexión, la confirma y la cierra siempre."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- Decisiones ---------------------------------------------------------

    def save_decision(self, record: DecisionRecord) -> DecisionRecord:
        """Inserta o actualiza una decisión (la clave es ``record.id``)."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO decisions
                    (id, created_at, topic, source_channel, video_id,
                     algorithm_version, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    created_at = excluded.created_at,
                    topic = excluded.topic,
                    source_channel = excluded.source_channel,
                    video_id = excluded.video_id,
                    algorithm_version = excluded.algorithm_version,
                    data = excluded.data
                """,
                (
                    record.id,
                    record.created_at.isoformat(),
                    record.topic,
                    record.source_channel,
                    record.video_id,
                    record.algorithm_version,
                    record.model_dump_json(),
                ),
            )
        return record

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        """Devuelve una decisión por id (o ``None``)."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT data FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        return DecisionRecord.model_validate_json(row["data"]) if row else None

    def find_by_video_id(self, video_id: str) -> DecisionRecord | None:
        """Busca la decisión asociada a un vídeo subido (la más reciente)."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT data FROM decisions WHERE video_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (video_id,),
            ).fetchone()
        return DecisionRecord.model_validate_json(row["data"]) if row else None

    def list_decisions(
        self,
        *,
        limit: int | None = None,
        source_channel: str | None = None,
        since: datetime | None = None,
        newest_first: bool = True,
    ) -> list[DecisionRecord]:
        """Lista decisiones con filtros opcionales (canal y fecha)."""
        query = "SELECT data FROM decisions"
        clauses: list[str] = []
        params: list[object] = []
        if source_channel:
            clauses.append("source_channel = ?")
            params.append(source_channel)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since.isoformat())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at " + ("DESC" if newest_first else "ASC")
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [DecisionRecord.model_validate_json(row["data"]) for row in rows]

    def delete_decision(self, decision_id: str) -> bool:
        """Borra una decisión y sus métricas. Devuelve si existía."""
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM decisions WHERE id = ?", (decision_id,))
            conn.execute("DELETE FROM performance WHERE decision_id = ?", (decision_id,))
        return cursor.rowcount > 0

    def count_decisions(self) -> int:
        """Número total de decisiones registradas."""
        with self._connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()
        return int(row["n"])

    # -- Métricas de rendimiento -------------------------------------------

    def add_performance(
        self, decision_id: str, snapshot: PerformanceSnapshot
    ) -> PerformanceSnapshot:
        """Guarda una medición (misma ventana y fecha ⇒ se reemplaza)."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO performance
                    (decision_id, window, captured_at, views, impressions, ctr,
                     avg_view_percentage, subscribers_gained, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id, window, captured_at) DO UPDATE SET
                    views = excluded.views,
                    impressions = excluded.impressions,
                    ctr = excluded.ctr,
                    avg_view_percentage = excluded.avg_view_percentage,
                    subscribers_gained = excluded.subscribers_gained,
                    data = excluded.data
                """,
                (
                    decision_id,
                    snapshot.window,
                    snapshot.captured_at.isoformat(),
                    snapshot.views,
                    snapshot.impressions,
                    snapshot.ctr,
                    snapshot.avg_view_percentage,
                    snapshot.subscribers_gained,
                    snapshot.model_dump_json(),
                ),
            )
        return snapshot

    def list_performance(
        self, decision_id: str, *, window: str | None = None
    ) -> list[PerformanceSnapshot]:
        """Métricas de una decisión, de la más antigua a la más reciente."""
        query = "SELECT data, captured_at FROM performance WHERE decision_id = ?"
        params: list[object] = [decision_id]
        if window:
            query += " AND window = ?"
            params.append(window)
        query += " ORDER BY captured_at ASC"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [PerformanceSnapshot.model_validate_json(row["data"]) for row in rows]

    def latest_performance(
        self, decision_id: str, *, window: str | None = None
    ) -> PerformanceSnapshot | None:
        """Última medición de una decisión (opcionalmente de una ventana)."""
        snapshots = self.list_performance(decision_id, window=window)
        return snapshots[-1] if snapshots else None

    def all_performance(self) -> dict[str, list[PerformanceSnapshot]]:
        """Todas las métricas, agrupadas por id de decisión."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT decision_id, data FROM performance ORDER BY captured_at ASC"
            ).fetchall()
        grouped: dict[str, list[PerformanceSnapshot]] = {}
        for row in rows:
            grouped.setdefault(row["decision_id"], []).append(
                PerformanceSnapshot.model_validate_json(row["data"])
            )
        return grouped

    def decisions_with_performance(self) -> set[str]:
        """Ids de decisión que ya tienen alguna métrica registrada."""
        with self._connection() as conn:
            rows = conn.execute("SELECT DISTINCT decision_id FROM performance").fetchall()
        return {row["decision_id"] for row in rows}

    def stats(self) -> dict[str, object]:
        """Resumen del contenido del journal (para ``youber-journal stats``)."""
        with self._connection() as conn:
            decisions = conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
            snapshots = conn.execute("SELECT COUNT(*) AS n FROM performance").fetchone()["n"]
            measured = conn.execute(
                "SELECT COUNT(DISTINCT decision_id) AS n FROM performance"
            ).fetchone()["n"]
            uploaded = conn.execute(
                "SELECT COUNT(*) AS n FROM decisions WHERE video_id IS NOT NULL"
            ).fetchone()["n"]
        return {
            "db_path": str(self.db_path),
            "decisions": int(decisions),
            "with_performance": int(measured),
            "snapshots": int(snapshots),
            "uploaded": int(uploaded),
        }

    @staticmethod
    def dumps_decision(record: DecisionRecord) -> str:
        """Serializa una decisión a JSON legible (para exportaciones)."""
        return json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2)
