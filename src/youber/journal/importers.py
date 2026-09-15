"""Importación de métricas de YouTube Studio (CSV) al registro de decisiones.

YouTube Studio permite exportar la tabla de Analytics a CSV («Modo avanzado»).
Aquí se lee ese CSV, se detectan las columnas por sus nombres (español o
inglés) y se pegan las métricas a la decisión correspondiente, cruzando por
**id del vídeo** y, si no lo hay, por el título.

Es tu propio panel de Analytics: datos propios, sin scraping ni automatismos
que toquen la plataforma.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import BaseModel, Field

from youber.journal.models import DecisionRecord, PerformanceSnapshot

#: Nombres de columna aceptados para el id del vídeo.
VIDEO_ID_ALIASES: tuple[str, ...] = (
    "id del video",
    "id de video",
    "video id",
    "id",
)
#: Nombres de columna aceptados para el título del vídeo.
TITLE_ALIASES: tuple[str, ...] = (
    "titulo del video",
    "video title",
    "titulo",
    "title",
    "contenido",
    "content",
)
#: Alias por métrica → columnas del CSV que la contienen.
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "views": ("visualizaciones", "views"),
    "impressions": ("impresiones", "impressions"),
    "ctr": (
        "ctr de las impresiones (%)",
        "ctr de las impresiones",
        "impressions click-through rate (%)",
        "ctr",
    ),
    "watch_time_minutes": (
        "tiempo de visualizacion (horas)",
        "watch time (hours)",
        "tiempo de visualizacion (minutos)",
        "watch time (minutes)",
    ),
    "avg_view_duration_seconds": (
        "duracion media de la visualizacion",
        "duracion media de visualizacion",
        "average view duration",
    ),
    "avg_view_percentage": (
        "porcentaje medio visto (%)",
        "porcentaje medio reproducido (%)",
        "average percentage viewed (%)",
    ),
    "likes": ("me gusta", "likes"),
    "comments": ("comentarios", "comments"),
    "shares": ("compartidos", "shares", "veces compartido"),
    "subscribers_gained": ("suscriptores ganados", "subscribers gained"),
    "subscribers_lost": ("suscriptores perdidos", "subscribers lost"),
    "revenue": (
        "ingresos estimados (eur)",
        "ingresos estimados (usd)",
        "estimated revenue (eur)",
        "estimated revenue (usd)",
        "ingresos (eur)",
        "revenue",
    ),
}

#: Columnas que vienen en **horas** y hay que pasar a minutos.
HOURS_COLUMNS = ("horas", "hours")

SRT_TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d+))?$")
#: Número con puntos de millar ("1.000", "1.234.567").
THOUSANDS_RE = re.compile(r"\d{1,3}(\.\d{3})+")


def normalize_header(value: str) -> str:
    """Normaliza el nombre de una columna (minúsculas, sin acentos ni espacios extra)."""
    decomposed = unicodedata.normalize("NFKD", (value or "").strip().lower())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.split())


def parse_number(value: Any) -> float | None:
    """Convierte un número de Studio a ``float`` ("1.234", "1,2", "4,5 %").

    Returns:
        El valor, o ``None`` si la celda está vacía o no es numérica.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text or text in {"-", "—", "n/a", "N/A"}:
        return None
    text = text.rstrip("%")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif THOUSANDS_RE.fullmatch(text):
        # "1.000" en un CSV en español es mil, no uno con tres decimales.
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_duration(value: Any) -> float | None:
    """Convierte "12:34", "1:02:03" o "754" en segundos (o ``None``)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    match = SRT_TIME_RE.match(text)
    if match:
        hours, minutes, seconds, fraction = match.groups()
        total = float(hours or 0) * 3600 + float(minutes) * 60 + float(seconds)
        if fraction:
            total += float(f"0.{fraction}")
        return round(total, 3)
    return parse_number(text)


def detect_columns(fieldnames: Sequence[str]) -> dict[str, str]:
    """Mapea métricas → columnas reales del CSV (por nombre normalizado).

    Returns:
        Diccionario ``clave`` → ``columna``. Contiene ``video_id`` y ``title``
        si se detectaron, más una entrada por métrica reconocida.
    """
    normalized = {normalize_header(name): name for name in fieldnames if name}
    mapping: dict[str, str] = {}
    for alias in VIDEO_ID_ALIASES:
        if alias in normalized:
            mapping["video_id"] = normalized[alias]
            break
    for alias in TITLE_ALIASES:
        if alias in normalized:
            mapping["title"] = normalized[alias]
            break
    for metric, aliases in METRIC_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[metric] = normalized[alias]
                break
    return mapping


class AnalyticsRow(BaseModel):
    """Una fila del CSV de Studio ya normalizada."""

    video_id: str | None = None
    title: str | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    raw: dict[str, str] = Field(default_factory=dict)


class AnalyticsTable(BaseModel):
    """Resultado de leer un CSV de Analytics: filas + mapeo de columnas."""

    rows: list[AnalyticsRow] = Field(default_factory=list)
    columns: dict[str, str] = Field(default_factory=dict)
    unmapped: list[str] = Field(default_factory=list)


def _detect_delimiter(sample: str) -> str:
    """Detecta el separador del CSV (Excel español usa ``;``)."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


def read_analytics_csv(source: str | Path | TextIO) -> AnalyticsTable:
    """Lee un CSV de YouTube Studio (ruta o fichero abierto).

    Args:
        source: Ruta del CSV (se prueban ``utf-8-sig`` y ``latin-1``) o un
            fichero de texto ya abierto.

    Returns:
        El :class:`AnalyticsTable` con las filas y el mapeo de columnas.

    Raises:
        ValueError: si el CSV no tiene cabecera reconocible.
    """
    if isinstance(source, str | Path):
        path = Path(source)
        text = _read_text(path)
        origin = str(path)
    else:
        text = source.read()
        origin = getattr(source, "name", "<fichero>")

    delimiter = _detect_delimiter(text[:2048])
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fieldnames = [name for name in (reader.fieldnames or []) if name]
    if not fieldnames:
        raise ValueError(f"CSV sin cabecera: {origin}")
    columns = detect_columns(fieldnames)
    if "video_id" not in columns and "title" not in columns:
        raise ValueError(
            "No se reconoce el CSV de Studio: falta la columna de id o de título "
            f"({origin}). Columnas: {', '.join(fieldnames[:8])}..."
        )
    unmapped = [
        name
        for name in fieldnames
        if name not in set(columns.values())
    ]
    rows: list[AnalyticsRow] = []
    for raw_row in reader:
        row = _build_row(raw_row, columns)
        if row is not None:
            rows.append(row)
    return AnalyticsTable(rows=rows, columns=columns, unmapped=unmapped)


def _read_text(path: Path) -> str:
    """Lee un CSV probando codificaciones habituales de Studio."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _build_row(raw_row: dict[str, str], columns: dict[str, str]) -> AnalyticsRow | None:
    """Normaliza una fila cruda del CSV (números, porcentajes y duraciones)."""
    if not any((value or "").strip() for value in raw_row.values()):
        return None
    metrics: dict[str, float | None] = {}
    for key, column in columns.items():
        if key in {"video_id", "title"}:
            continue
        value = raw_row.get(column)
        if key == "avg_view_duration_seconds":
            parsed = parse_duration(value)
        else:
            parsed = parse_number(value)
            if parsed is not None and key == "watch_time_minutes":
                lowered = normalize_header(column)
                if any(marker in lowered for marker in HOURS_COLUMNS):
                    parsed = round(parsed * 60, 3)
        metrics[key] = parsed
    video_id = (raw_row.get(columns.get("video_id", ""), "") or "").strip() or None
    title = (raw_row.get(columns.get("title", ""), "") or "").strip() or None
    return AnalyticsRow(
        video_id=video_id,
        title=title,
        metrics=metrics,
        raw={str(key): str(value) for key, value in raw_row.items() if key},
    )


# ---------------------------------------------------------------------------
# Cruce con el journal
# ---------------------------------------------------------------------------


def normalize_title(value: str | None) -> str:
    """Normaliza un título para emparejar (minúsculas, sin signos ni acentos)."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return " ".join(
        "".join(
            char if char.isalnum() or char.isspace() else " "
            for char in decomposed
            if not unicodedata.combining(char)
        ).split()
    )


class MatchedRow(BaseModel):
    """Fila del CSV que se ha cruzado con una decisión del journal."""

    decision_id: str
    matched_by: str  # "video_id" | "title"
    label: str
    metrics: dict[str, float | None] = Field(default_factory=dict)


class UnmatchedRow(BaseModel):
    """Fila del CSV que no correspondía a ninguna decisión registrada."""

    video_id: str | None = None
    title: str | None = None
    reason: str = "sin decisión registrada"


class ImportResult(BaseModel):
    """Resumen de una importación de métricas."""

    window: str = "28d"
    parsed: int = 0
    applied: int = 0
    matched: list[MatchedRow] = Field(default_factory=list)
    unmatched: list[UnmatchedRow] = Field(default_factory=list)
    dry_run: bool = False


def match_record(
    record: DecisionRecord, row: AnalyticsRow, *, by_title: dict[str, DecisionRecord]
) -> str | None:
    """Determina si una fila corresponde a una decisión (``video_id``/``title``)."""
    if row.video_id and record.video_id and row.video_id.strip() == record.video_id.strip():
        return "video_id"
    normalized = normalize_title(row.title)
    if normalized and by_title.get(normalized) is not None:
        candidate = by_title[normalized]
        if candidate.id == record.id:
            return "title"
    return None


def _as_int(value: float | None) -> int | None:
    """Convierte un valor numérico del CSV en entero (o ``None``)."""
    return int(round(value)) if value is not None else None


def _build_indexes(
    records: Iterable[DecisionRecord],
) -> tuple[dict[str, DecisionRecord], dict[str, DecisionRecord]]:
    """Índices por id de vídeo y por título normalizado (subida o tema)."""
    by_video: dict[str, DecisionRecord] = {}
    by_title: dict[str, DecisionRecord] = {}
    for record in records:
        if record.video_id:
            by_video[record.video_id.strip()] = record
        for candidate in (
            record.upload.title if record.upload is not None else None,
            record.topic,
        ):
            normalized = normalize_title(candidate)
            if normalized:
                by_title.setdefault(normalized, record)
    return by_video, by_title


def import_analytics_csv(
    records: Sequence[DecisionRecord],
    source: str | Path | TextIO,
    *,
    window: str = "28d",
    dry_run: bool = False,
    captured_at: datetime | None = None,
) -> tuple[ImportResult, list[tuple[str, PerformanceSnapshot]]]:
    """Cruza un CSV de Studio con las decisiones registradas.

    Args:
        records: Decisiones del journal.
        source: Ruta del CSV exportado de YouTube Studio.
        window: Ventana temporal que representan las métricas (``7d``, ``28d``...).
        dry_run: Si ``True``, no se aplica nada (solo se informa).
        captured_at: Momento de la captura (por defecto, ahora).

    Returns:
        ``(resultado, [(decision_id, snapshot), ...])``: el resumen de la
        importación y los pares a guardar (vacíos si ``dry_run``).
    """
    table = read_analytics_csv(source)
    by_video, by_title = _build_indexes(records)
    result = ImportResult(window=window, parsed=len(table.rows), dry_run=dry_run)
    pending: list[tuple[str, PerformanceSnapshot]] = []

    for row in table.rows:
        record: DecisionRecord | None = None
        matched_by: str | None = None
        if row.video_id and row.video_id in by_video:
            record, matched_by = by_video[row.video_id], "video_id"
        else:
            normalized = normalize_title(row.title)
            if normalized and normalized in by_title:
                record, matched_by = by_title[normalized], "title"
        if record is None or matched_by is None:
            result.unmatched.append(
                UnmatchedRow(video_id=row.video_id, title=row.title)
            )
            continue

        snapshot = PerformanceSnapshot(
            window=window,
            captured_at=captured_at or datetime.now(),
            impressions=_as_int(row.metrics.get("impressions")),
            views=_as_int(row.metrics.get("views")),
            ctr=row.metrics.get("ctr"),
            watch_time_minutes=row.metrics.get("watch_time_minutes"),
            avg_view_duration_seconds=row.metrics.get("avg_view_duration_seconds"),
            avg_view_percentage=row.metrics.get("avg_view_percentage"),
            likes=_as_int(row.metrics.get("likes")),
            comments=_as_int(row.metrics.get("comments")),
            shares=_as_int(row.metrics.get("shares")),
            subscribers_gained=_as_int(row.metrics.get("subscribers_gained")),
            subscribers_lost=_as_int(row.metrics.get("subscribers_lost")),
            revenue=row.metrics.get("revenue"),
            raw=dict(row.raw),
        )
        result.matched.append(
            MatchedRow(
                decision_id=record.id,
                matched_by=matched_by,
                label=row.title or row.video_id or record.topic,
                metrics=dict(row.metrics),
            )
        )
        if not dry_run:
            pending.append((record.id, snapshot))
    result.applied = len(pending)
    return result, pending
