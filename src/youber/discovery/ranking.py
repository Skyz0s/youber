"""Ranking de canales por métricas (uso educativo).

Ordena canales descubiertos por distintas métricas públicas: suscriptores,
vistas, vídeos, engagement (vistas por suscriptor) o vistas por vídeo.

Límites éticos: las métricas se **leen** de datos públicos; este módulo no
manipula ni infla nada. Es análisis descriptivo para investigación.
"""

from __future__ import annotations

from enum import StrEnum
from statistics import median

from pydantic import BaseModel, Field

from youber.discovery.search import ChannelHit


class RankingMetric(StrEnum):
    """Métricas de ordenación disponibles."""

    SUBSCRIBERS = "subscribers"
    VIEWS = "views"
    VIDEOS = "videos"
    ENGAGEMENT = "engagement"  # vistas por suscriptor
    VIEWS_PER_VIDEO = "views_per_video"


class RankedChannel(BaseModel):
    """Canal con su posición, métrica y puntuación."""

    rank: int
    channel: ChannelHit
    metric: RankingMetric
    score: float
    details: dict[str, float] = Field(default_factory=dict)


def metric_value(channel: ChannelHit, metric: RankingMetric) -> float:
    """Devuelve el valor numérico de una métrica para un canal.

    Los valores ausentes se tratan como 0 (mejor esfuerzo).
    """
    if metric == RankingMetric.SUBSCRIBERS:
        return float(channel.subscriber_count or 0)
    if metric == RankingMetric.VIEWS:
        return float(channel.view_count or 0)
    if metric == RankingMetric.VIDEOS:
        return float(channel.video_count or 0)
    if metric == RankingMetric.ENGAGEMENT:
        return engagement_score(channel)
    if metric == RankingMetric.VIEWS_PER_VIDEO:
        return views_per_video(channel)
    raise ValueError(f"Métrica desconocida: {metric!r}")


def engagement_score(channel: ChannelHit) -> float:
    """Vistas por suscriptor (proxy de interacción; 0 si no hay datos)."""
    subs = channel.subscriber_count or 0
    views = channel.view_count or 0
    if subs <= 0:
        return 0.0
    return views / subs


def views_per_video(channel: ChannelHit) -> float:
    """Vistas por vídeo publicado (0 si no hay datos)."""
    videos = channel.video_count or 0
    views = channel.view_count or 0
    if videos <= 0:
        return 0.0
    return views / videos


def rank_channels(
    channels: list[ChannelHit],
    metric: RankingMetric | str = RankingMetric.ENGAGEMENT,
    limit: int | None = None,
) -> list[RankedChannel]:
    """Ordena canales por una métrica, de mayor a menor.

    Args:
        channels: Canales descubiertos.
        metric: Métrica de ordenación (por defecto: engagement).
        limit: Número máximo de resultados (opcional).

    Returns:
        Lista de :class:`RankedChannel` ordenada, con empates resueltos por
        suscriptores (desempate determinista).
    """
    resolved = RankingMetric(metric)
    ordered = sorted(
        channels,
        key=lambda ch: (metric_value(ch, resolved), ch.subscriber_count or 0),
        reverse=True,
    )
    if limit is not None:
        ordered = ordered[:limit]
    return [
        RankedChannel(
            rank=index + 1,
            channel=channel,
            metric=resolved,
            score=metric_value(channel, resolved),
            details=_metric_details(channel),
        )
        for index, channel in enumerate(ordered)
    ]


def _metric_details(channel: ChannelHit) -> dict[str, float]:
    """Desglose de métricas de un canal (para la tabla del CLI)."""
    return {
        RankingMetric.SUBSCRIBERS.value: float(channel.subscriber_count or 0),
        RankingMetric.VIEWS.value: float(channel.view_count or 0),
        RankingMetric.VIDEOS.value: float(channel.video_count or 0),
        RankingMetric.ENGAGEMENT.value: engagement_score(channel),
        RankingMetric.VIEWS_PER_VIDEO.value: views_per_video(channel),
    }


def summarize(channels: list[ChannelHit]) -> dict[str, float | int]:
    """Resumen estadístico de un conjunto de canales (análisis descriptivo)."""
    subs = [ch.subscriber_count or 0 for ch in channels]
    views = [ch.view_count or 0 for ch in channels]
    return {
        "canales": len(channels),
        "suscriptores_medio": round(_mean(subs), 1),
        "suscriptores_mediana": median(subs) if subs else 0,
        "vistas_medio": round(_mean(views), 1),
        "vistas_mediana": median(views) if views else 0,
        "con_categoria": sum(1 for ch in channels if ch.category is not None),
    }


def _mean(values: list[int]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
