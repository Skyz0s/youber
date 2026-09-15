"""Registro de decisiones (decision journal) de BARF.

:class:`DecisionJournal` es la fachada del módulo: guarda la decisión completa
de cada vídeo (metadatos → atributos → canción → prompt → vídeo), le cuelga
después la subida y las métricas de rendimiento, y expone el conjunto como
**dataset** para el análisis.

Uso típico:

.. code-block:: python

    from youber.journal import DecisionJournal

    journal = DecisionJournal()                  # ~/.youber/journal.db
    journal.record(record)                       # guarda una decisión
    journal.attach_upload(record.id, video_id="abc123")
    journal.record_performance(record.id, PerformanceSnapshot(window="7d", views=1200, ctr=4.5))
    filas = journal.dataset(window="7d")         # features + resultados
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from youber.journal.models import (
    DecisionRecord,
    PerformanceSnapshot,
    UploadRecord,
)
from youber.journal.storage import JournalStorage

#: Ruta por defecto del journal (``~/.youber/journal.db``).
DEFAULT_JOURNAL_DIR = Path.home() / ".youber"
DEFAULT_JOURNAL_DB = DEFAULT_JOURNAL_DIR / "journal.db"


def default_journal_path() -> Path:
    """Ruta del journal: ``YOUBER_JOURNAL_DB`` si existe, si no ``~/.youber``.

    La variable de entorno permite aislar los tests (y usar varios journals
    por proyecto) sin tocar el fichero del usuario.
    """
    from_env = os.getenv("YOUBER_JOURNAL_DB")
    return Path(from_env).expanduser() if from_env else DEFAULT_JOURNAL_DB


class DecisionJournal:
    """Cuaderno de laboratorio: decisiones, subidas y rendimiento."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Abre (o crea) el journal.

        Args:
            db_path: Ruta del SQLite. Por defecto
                :func:`default_journal_path` (``YOUBER_JOURNAL_DB`` o
                ``~/.youber/journal.db``).
        """
        self.path = Path(db_path) if db_path is not None else default_journal_path()
        self.storage = JournalStorage(self.path)
        logger.debug(f"Journal listo: {self.path}")

    # -- Decisiones ---------------------------------------------------------

    def record(self, record: DecisionRecord) -> DecisionRecord:
        """Guarda una decisión (y devuelve el registro tal cual)."""
        self.storage.save_decision(record)
        logger.debug(f"Decisión registrada: {record.id} · {record.topic!r}")
        return record

    def get(self, decision_id: str) -> DecisionRecord | None:
        """Devuelve una decisión por id (o por id de vídeo subido)."""
        record = self.storage.get_decision(decision_id)
        if record is not None:
            return record
        return self.storage.find_by_video_id(decision_id)

    def find_by_video(self, video_id: str) -> DecisionRecord | None:
        """Devuelve la decisión asociada a un vídeo subido."""
        return self.storage.find_by_video_id(video_id)

    def list_decisions(
        self,
        *,
        limit: int | None = None,
        source_channel: str | None = None,
        since: datetime | None = None,
    ) -> list[DecisionRecord]:
        """Lista decisiones (las más recientes primero)."""
        return self.storage.list_decisions(
            limit=limit, source_channel=source_channel, since=since
        )

    def remove(self, decision_id: str) -> bool:
        """Elimina una decisión y sus métricas."""
        return self.storage.delete_decision(decision_id)

    def count(self) -> int:
        """Número de decisiones registradas."""
        return self.storage.count_decisions()

    # -- Subida y rendimiento ----------------------------------------------

    def attach_upload(
        self,
        decision_id: str,
        *,
        video_id: str,
        url: str | None = None,
        title: str | None = None,
        privacy: str | None = None,
        published_at: datetime | None = None,
    ) -> DecisionRecord:
        """Asocia el vídeo subido a una decisión (para cruzar métricas luego).

        Raises:
            KeyError: si la decisión no existe.
        """
        record = self.storage.get_decision(decision_id)
        if record is None:
            raise KeyError(f"Decisión no encontrada: {decision_id!r}")
        record.upload = UploadRecord(
            video_id=video_id,
            url=url,
            title=title,
            privacy=privacy,
            published_at=published_at,
        )
        return self.storage.save_decision(record)

    def record_performance(
        self, decision_id: str, snapshot: PerformanceSnapshot
    ) -> PerformanceSnapshot:
        """Añade métricas a una decisión (por id de decisión o de vídeo).

        Raises:
            KeyError: si no se encuentra la decisión.
        """
        record = self.get(decision_id)
        if record is None:
            raise KeyError(f"Decisión no encontrada: {decision_id!r}")
        return self.storage.add_performance(record.id, snapshot)

    def performance(
        self, decision_id: str, *, window: str | None = None
    ) -> list[PerformanceSnapshot]:
        """Histórico de métricas de una decisión."""
        record = self.get(decision_id)
        if record is None:
            return []
        return self.storage.list_performance(record.id, window=window)

    def latest_performance(
        self, decision_id: str, *, window: str | None = None
    ) -> PerformanceSnapshot | None:
        """Última medición disponible de una decisión."""
        return self.storage.latest_performance(decision_id, window=window)

    # -- Dataset y exportación ---------------------------------------------

    def dataset(self, *, window: str | None = None) -> list[Any]:
        """Dataset **features → resultados** para el análisis.

        Cada fila une los atributos y decisiones de un vídeo con las métricas
        de su última ventana medida.

        Args:
            window: Ventana de métricas (``7d``, ``28d``, ``lifetime``...).
                ``None`` usa la última medición sea cual sea la ventana.
        """
        from youber.journal.analytics import build_dataset

        return build_dataset(self, window=window)

    def stats(self) -> dict[str, object]:
        """Resumen del journal (decisiones, mediciones, subidas)."""
        return self.storage.stats()

    def export(
        self,
        path: str | Path,
        *,
        fmt: str | None = None,
        window: str | None = None,
    ) -> Path:
        """Exporta el journal a JSON, JSONL o CSV.

        Args:
            path: Fichero de destino.
            fmt: ``json`` (anidado), ``jsonl`` (una decisión por línea) o
                ``csv`` (dataset plano: features + resultados).
            window: Ventana de métricas para el CSV (``None`` = la última).

        Returns:
            La ruta escrita.

        Raises:
            ValueError: si el formato no se reconoce.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved = (fmt or target.suffix.lstrip(".") or "json").lower()
        if resolved == "json":
            payload = [
                json.loads(record.model_dump_json()) for record in self.list_decisions()
            ]
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        elif resolved in {"jsonl", "ndjson"}:
            lines = [record.model_dump_json() for record in self.list_decisions()]
            target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        elif resolved == "csv":
            from youber.journal.analytics import dataset_rows, rows_to_csv

            rows = dataset_rows(self.dataset(window=window))
            target.write_text(rows_to_csv(rows), encoding="utf-8")
        else:
            raise ValueError(
                f"Formato no soportado: {fmt!r} (usa json, jsonl o csv)"
            )
        logger.debug(f"Journal exportado: {target}")
        return target

    def iter_records(self) -> Iterable[DecisionRecord]:
        """Itera las decisiones de la más antigua a la más reciente."""
        return iter(self.list_natural())

    def list_natural(self) -> list[DecisionRecord]:
        """Decisiones en orden cronológico natural (más antigua primero)."""
        return self.storage.list_decisions(newest_first=False)

    def close(self) -> None:
        """Cierra el journal (las conexiones se abren por operación)."""
        logger.debug("Journal cerrado")

    def __enter__(self) -> DecisionJournal:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = [
    "DEFAULT_JOURNAL_DB",
    "DecisionJournal",
    "default_journal_path",
]


def row_dicts(records: Iterable[DecisionRecord]) -> list[dict[str, Any]]:
    """Convierte decisiones en diccionarios serializables (json-ready)."""
    return [json.loads(record.model_dump_json()) for record in records]


# ``csv`` se importa para que las CLIs/exportadores que lo usan a través de
# este módulo no dependan del detalle de implementación.
_ = csv
