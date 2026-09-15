"""Dataset y análisis del registro de decisiones.

Convierte el journal en un **dataset features → resultados**: cada fila es un
vídeo con los atributos que el algoritmo usó para decidir (tema, señales del
matching, procedencia de los clips, duración...) y las métricas con las que
rindió (impresiones, CTR, retención, visualizaciones, suscripciones...).

Con eso se estudia, de forma **descriptiva**, qué características del matching
parecen predecir que un vídeo funcione: correlaciones de Pearson y medias por
grupo, siempre con el tamaño de muestra a la vista (con pocos vídeos, cualquier
correlación es ruido — el informe lo avisa).

No hay aquí nada de manipulación de métricas: se analizan datos propios.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from youber.journal.models import DecisionRecord, PerformanceSnapshot

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from youber.journal.journal import DecisionJournal

#: Features que el algoritmo conoce **en el momento de decidir**.
#: (La clave es que ninguna dependa del resultado: sirven para predecir.)
FEATURE_LABELS: dict[str, str] = {
    "chosen_score": "Puntuación de la canción elegida",
    "theme_score": "Afinidad temática canción↔contenido",
    "matched_theme_count": "Nº de temas compartidos",
    "dominant_theme_weight": "Peso del tema dominante",
    "sentiment_match": "Sentimiento de la letra coincide",
    "mood_match": "Mood coincide",
    "favorite": "Canción favorita",
    "usage_count": "Usos previos de la canción",
    "keyword_hits": "Keywords del vídeo en la canción",
    "candidate_margin": "Ventaja sobre la 2ª candidata",
    "catalog_size": "Tamaño del catálogo",
    "theme_count": "Nº de temas detectados",
    "hashtag_count": "Nº de hashtags",
    "keyword_count": "Nº de keywords de B-roll",
    "videos_analyzed": "Vídeos analizados del canal",
    "target_duration": "Duración objetivo (s)",
    "track_duration": "Duración de la canción (s)",
    "scene_count": "Nº de escenas",
    "clip_count": "Nº de clips",
    "video_duration": "Duración del vídeo (s)",
    "forced": "Canción forzada a mano",
}

#: Métricas de resultado (lo que se quiere predecir).
OUTCOME_LABELS: dict[str, str] = {
    "views": "Visualizaciones",
    "impressions": "Impresiones",
    "ctr": "CTR de impresiones (%)",
    "retention": "Retención (% medio visto)",
    "avg_view_duration_seconds": "Duración media vista (s)",
    "watch_time_minutes": "Tiempo de visualización (min)",
    "likes": "Me gusta",
    "comments": "Comentarios",
    "shares": "Compartidos",
    "subscribers_gained": "Suscriptores ganados",
    "net_subscribers": "Suscriptores netos",
    "engagement_rate": "Interacciones por visualización (%)",
}


class DatasetRow(BaseModel):
    """Una decisión con sus features y los resultados medidos."""

    decision_id: str
    created_at: datetime
    topic: str = ""
    video_id: str | None = None
    window: str | None = None
    dominant_theme: str | None = None
    clip_source: str = "none"
    sentiment: str = "neutral"
    sentiment_match: bool = False
    mood_match: bool = False
    forced: bool = False
    features: dict[str, float | None] = Field(default_factory=dict)
    outcomes: dict[str, float | None] = Field(default_factory=dict)

    @property
    def measured(self) -> bool:
        """``True`` si la fila tiene algún resultado medido."""
        return any(value is not None for value in self.outcomes.values())


class FeatureCorrelation(BaseModel):
    """Correlación de Pearson entre una feature y una métrica de resultado."""

    feature: str
    metric: str
    r: float
    n: int
    mean_feature: float
    mean_metric: float

    @property
    def direction(self) -> str:
        """``positiva``, ``negativa`` o ``plana`` (según el signo de ``r``)."""
        if self.r > 0.05:
            return "positiva"
        if self.r < -0.05:
            return "negativa"
        return "plana"


class GroupStat(BaseModel):
    """Media de una métrica para un grupo (p. ej. por tema dominante)."""

    group: str
    n: int
    mean: float


class DatasetSummary(BaseModel):
    """Resumen del dataset: cuántas decisiones y cuántas con resultados."""

    decisions: int = 0
    measured: int = 0
    metrics: dict[str, int] = Field(default_factory=dict)
    windows: dict[str, int] = Field(default_factory=dict)
    themes: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Extracción de features y resultados
# ---------------------------------------------------------------------------


def extract_features(record: DecisionRecord) -> dict[str, float | None]:
    """Features de una decisión (todo lo que el algoritmo sabía al decidir)."""
    attributes = record.attributes
    track = record.track
    video = record.video
    dominant_weight = (
        attributes.themes.get(attributes.dominant_theme)
        if attributes.dominant_theme
        else None
    )
    return {
        "chosen_score": track.score if track.chosen_id else None,
        "theme_score": track.theme_score if track.chosen_id else None,
        "matched_theme_count": float(len(track.matched_themes)) if track.chosen_id else None,
        "dominant_theme_weight": dominant_weight,
        "sentiment_match": 1.0 if track.sentiment_match else 0.0,
        "mood_match": 1.0 if track.mood_match else 0.0,
        "favorite": 1.0 if track.favorite else 0.0,
        "usage_count": float(track.usage_count) if track.chosen_id else None,
        "keyword_hits": float(track.keyword_hits) if track.chosen_id else None,
        "candidate_margin": track.margin,
        "catalog_size": float(track.catalog_size) if track.catalog_size else None,
        "theme_count": float(len(attributes.themes)),
        "hashtag_count": float(len(attributes.hashtags)),
        "keyword_count": float(len(attributes.keywords)),
        "videos_analyzed": float(attributes.videos_analyzed),
        "target_duration": attributes.target_duration or None,
        "track_duration": track.duration_seconds,
        "scene_count": float(video.scene_count) if video.scene_count else None,
        "clip_count": float(video.clip_count) if video.clip_count else None,
        "video_duration": video.duration_seconds,
        "forced": 1.0 if track.forced else 0.0,
    }


def extract_outcomes(snapshot: PerformanceSnapshot) -> dict[str, float | None]:
    """Métricas de resultado de una medición (todo lo observado después)."""
    return {
        "views": _as_float(snapshot.views),
        "impressions": _as_float(snapshot.impressions),
        "ctr": snapshot.ctr,
        "retention": snapshot.retention,
        "avg_view_duration_seconds": snapshot.avg_view_duration_seconds,
        "watch_time_minutes": snapshot.watch_time_minutes,
        "likes": _as_float(snapshot.likes),
        "comments": _as_float(snapshot.comments),
        "shares": _as_float(snapshot.shares),
        "subscribers_gained": _as_float(snapshot.subscribers_gained),
        "net_subscribers": _as_float(snapshot.net_subscribers),
        "engagement_rate": snapshot.engagement_rate,
    }


def _as_float(value: int | None) -> float | None:
    """Convierte un entero (o ``None``) en ``float`` para el dataset."""
    return float(value) if value is not None else None


def build_dataset(journal: DecisionJournal, *, window: str | None = None) -> list[DatasetRow]:
    """Construye el dataset completo a partir del journal.

    Args:
        journal: Journal abierto.
        window: Ventana de métricas (``7d``, ``28d``...). ``None`` usa la
            última medición disponible de cada vídeo.

    Returns:
        Una fila por decisión, en orden cronológico.
    """
    rows: list[DatasetRow] = []
    for record in journal.list_natural():
        snapshot = journal.latest_performance(record.id, window=window)
        rows.append(
            DatasetRow(
                decision_id=record.id,
                created_at=record.created_at,
                topic=record.topic,
                video_id=record.video_id,
                window=snapshot.window if snapshot else None,
                dominant_theme=record.attributes.dominant_theme,
                clip_source=record.video.clip_source,
                sentiment=record.attributes.sentiment,
                sentiment_match=record.track.sentiment_match,
                mood_match=record.track.mood_match,
                forced=record.track.forced,
                features=extract_features(record),
                outcomes=extract_outcomes(snapshot) if snapshot else {},
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Estadística descriptiva
# ---------------------------------------------------------------------------


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Correlación de Pearson entre dos series (``None`` si no es calculable).

    Devuelve ``None`` si hay menos de dos pares o si alguna serie no tiene
    varianza (una constante no correlaciona con nada).
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return round(cov / (var_x**0.5 * var_y**0.5), 4)


def _pairs(
    rows: Iterable[DatasetRow], feature: str, metric: str
) -> tuple[list[float], list[float]]:
    """Pares (feature, métrica) presentes en las filas."""
    xs: list[float] = []
    ys: list[float] = []
    for row in rows:
        feature_value = row.features.get(feature)
        metric_value = row.outcomes.get(metric)
        if feature_value is None or metric_value is None:
            continue
        xs.append(float(feature_value))
        ys.append(float(metric_value))
    return xs, ys


def feature_correlations(
    rows: Sequence[DatasetRow], metric: str, *, min_n: int = 3
) -> list[FeatureCorrelation]:
    """Correlaciones feature → métrica, ordenadas por fuerza absoluta.

    Args:
        rows: Filas del dataset.
        metric: Métrica de resultado (``ctr``, ``views``, ``retention``...).
        min_n: Pares mínimos para aceptar una correlación (evita ruido).

    Returns:
        Lista de :class:`FeatureCorrelation` (vacía si no hay datos).
    """
    correlations: list[FeatureCorrelation] = []
    for feature in FEATURE_LABELS:
        xs, ys = _pairs(rows, feature, metric)
        if len(xs) < min_n:
            continue
        r = pearson(xs, ys)
        if r is None:
            continue
        correlations.append(
            FeatureCorrelation(
                feature=feature,
                metric=metric,
                r=r,
                n=len(xs),
                mean_feature=round(sum(xs) / len(xs), 4),
                mean_metric=round(sum(ys) / len(ys), 4),
            )
        )
    correlations.sort(key=lambda item: abs(item.r), reverse=True)
    return correlations


def compare_groups(
    rows: Sequence[DatasetRow], key: str, metric: str, *, min_n: int = 2
) -> list[GroupStat]:
    """Media de una métrica por grupo (``dominant_theme``, ``clip_source``...).

    Args:
        rows: Filas del dataset.
        key: Campo categórico de :class:`DatasetRow`
            (``dominant_theme``, ``clip_source``, ``sentiment``...).
        metric: Métrica de resultado.
        min_n: Vídeos mínimos para mostrar un grupo.

    Returns:
        Grupos con su media, ordenados de mejor a peor.
    """
    buckets: dict[str, list[float]] = {}
    for row in rows:
        group = getattr(row, key, None)
        value = row.outcomes.get(metric)
        if group is None or value is None:
            continue
        buckets.setdefault(str(group), []).append(float(value))
    stats = [
        GroupStat(group=group, n=len(values), mean=round(sum(values) / len(values), 4))
        for group, values in buckets.items()
        if len(values) >= min_n
    ]
    stats.sort(key=lambda item: item.mean, reverse=True)
    return stats


def summarize(rows: Sequence[DatasetRow]) -> DatasetSummary:
    """Resumen del dataset: decisiones, mediciones y cobertura por métrica."""
    summary = DatasetSummary(decisions=len(rows))
    for row in rows:
        available = {
            name: value for name, value in row.outcomes.items() if value is not None
        }
        if available:
            summary.measured += 1
        for name in available:
            summary.metrics[name] = summary.metrics.get(name, 0) + 1
        if row.window:
            summary.windows[row.window] = summary.windows.get(row.window, 0) + 1
        theme = row.dominant_theme or "sin tema"
        summary.themes[theme] = summary.themes.get(theme, 0) + 1
    return summary


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------


def build_report(
    rows: Sequence[DatasetRow], *, metric: str = "ctr", min_n: int = 3
) -> str:
    """Informe en Markdown: correlaciones y medias por grupo.

    Args:
        rows: Filas del dataset.
        metric: Métrica de resultado a estudiar.
        min_n: Pares mínimos para calcular correlaciones.

    Returns:
        Markdown listo para guardar o imprimir.
    """
    summary = summarize(rows)
    label = OUTCOME_LABELS.get(metric, metric)
    lines: list[str] = [
        f"# Informe del registro de decisiones — {label}",
        "",
        f"- Decisiones registradas: **{summary.decisions}** "
        f"({summary.measured} con métricas)",
    ]
    if summary.windows:
        windows = ", ".join(f"{name} ×{count}" for name, count in sorted(summary.windows.items()))
        lines.append(f"- Ventanas medidas: {windows}")
    if summary.metrics:
        metrics = ", ".join(
            f"{OUTCOME_LABELS.get(name, name)} ({count})"
            for name, count in sorted(summary.metrics.items())
        )
        lines.append(f"- Cobertura de métricas: {metrics}")
    lines.append("")

    correlations = feature_correlations(rows, metric, min_n=min_n)
    lines.append(f"## Qué correlaciona con {label.lower()}")
    lines.append("")
    if not correlations:
        lines.append(
            f"_Sin datos suficientes_: hacen falta al menos {min_n} vídeos con "
            f"«{label}» medido y con variación en las features."
        )
    else:
        lines.append("| Feature | r (Pearson) | n | media feature | media " + label + " |")
        lines.append("|---|---:|---:|---:|---:|")
        for item in correlations:
            name = FEATURE_LABELS.get(item.feature, item.feature)
            lines.append(
                f"| {name} | {item.r:+.3f} | {item.n} | {item.mean_feature:g} "
                f"| {item.mean_metric:g} |"
            )
    lines.append("")

    for key, title in (
        ("dominant_theme", "Tema dominante"),
        ("clip_source", "Origen de los clips"),
        ("sentiment", "Sentimiento del contenido"),
    ):
        stats = compare_groups(rows, key, metric, min_n=min_n - 1 if min_n > 1 else 1)
        if not stats:
            continue
        lines.append(f"## {title} ({label.lower()})")
        lines.append("")
        lines.append("| Grupo | Vídeos | Media |")
        lines.append("|---|---:|---:|")
        for group in stats:
            lines.append(f"| {group.group} | {group.n} | {group.mean:g} |")
        lines.append("")

    lines.append("## Cómo leerlo")
    lines.append("")
    lines.append(
        "- Correlación **no** implica causalidad: son datos observacionales de tus "
        "propios vídeos, no un experimento controlado."
    )
    lines.append(
        f"- Con pocos vídeos (n < {max(10, min_n * 3)}) cualquier correlación es "
        "ruido: el signo cambia solo con añadir un caso."
    )
    lines.append(
        "- El margen de mejora está en **acumular**: registra cada vídeo y pega las "
        "métricas de YouTube Studio a los 7 y a los 28 días."
    )
    lines.append(
        "- Esto es análisis descriptivo de datos propios; no se manipula ninguna "
        "métrica de plataforma."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Exportación tabular
# ---------------------------------------------------------------------------


def dataset_rows(rows: Sequence[DatasetRow]) -> list[dict[str, Any]]:
    """Aplana el dataset a filas planas (dicts) para CSV/JSON."""
    flat: list[dict[str, Any]] = []
    for row in rows:
        base: dict[str, Any] = {
            "decision_id": row.decision_id,
            "created_at": row.created_at.isoformat(),
            "topic": row.topic,
            "video_id": row.video_id or "",
            "window": row.window or "",
            "dominant_theme": row.dominant_theme or "",
            "sentiment": row.sentiment,
            "clip_source": row.clip_source,
            "sentiment_match": int(row.sentiment_match),
            "mood_match": int(row.mood_match),
            "forced": int(row.forced),
        }
        for feature in FEATURE_LABELS:
            base[feature] = row.features.get(feature)
        for outcome in OUTCOME_LABELS:
            base[outcome] = row.outcomes.get(outcome)
        flat.append(base)
    return flat


def rows_to_csv(rows: Sequence[dict[str, Any]]) -> str:
    """Serializa filas planas a CSV (con BOM para Excel, como el resto de BARF)."""
    import csv
    import io

    if not rows:
        return "\ufeffdecision_id,created_at\n"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + buffer.getvalue()
