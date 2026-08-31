"""Similitud entre canales (uso educativo).

Calcula qué canales descubiertos se parecen entre sí a partir de la
categoría, los temas coincidentes y la cercanía de sus métricas públicas.

Límites éticos: análisis descriptivo de datos públicos; no hay seguimiento
de usuarios ni manipulación de métricas.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from youber.discovery.search import ChannelHit


class SimilarChannel(BaseModel):
    """Canal con su grado de similitud respecto al objetivo."""

    rank: int
    channel: ChannelHit
    score: float
    shared_topics: list[str] = Field(default_factory=list)
    same_category: bool = False


def _topic_overlap(a: ChannelHit, b: ChannelHit) -> float:
    """Jaccard de los temas coincidentes (0 si ambos están vacíos)."""
    set_a = set(a.matched_topics)
    set_b = set(b.matched_topics)
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _metric_proximity(a: ChannelHit, b: ChannelHit) -> float:
    """Proximidad de tamaño (escala log de suscriptores), 0..1."""
    subs_a = a.subscriber_count or 0
    subs_b = b.subscriber_count or 0
    if subs_a <= 0 and subs_b <= 0:
        return 0.5  # ambos sin datos: neutro
    log_a = math.log10(max(subs_a, 1))
    log_b = math.log10(max(subs_b, 1))
    delta = abs(log_a - log_b)
    return max(0.0, 1.0 - delta / 3.0)  # 3 órdenes de magnitud → 0


def similarity_score(a: ChannelHit, b: ChannelHit) -> tuple[float, dict[str, float]]:
    """Puntuación de similitud (0..1) entre dos canales.

    Combina: 40 % temas compartidos, 30 % misma categoría y 30 % proximidad
    de tamaño. Devuelve la puntuación y el desglose (para depurar/CLI).
    """
    topics = _topic_overlap(a, b)
    same_category = bool(
        a.category is not None and a.category == b.category
    )
    proximity = _metric_proximity(a, b)
    score = 0.4 * topics + 0.3 * float(same_category) + 0.3 * proximity
    return round(score, 4), {
        "topics": round(topics, 4),
        "category": 1.0 if same_category else 0.0,
        "proximity": round(proximity, 4),
    }


def shared_topics(a: ChannelHit, b: ChannelHit) -> list[str]:
    """Temas que comparten dos canales."""
    return sorted(set(a.matched_topics) & set(b.matched_topics))


def find_similar(
    target: ChannelHit,
    pool: list[ChannelHit],
    limit: int = 5,
    min_score: float = 0.0,
) -> list[SimilarChannel]:
    """Busca canales del pool más parecidos al objetivo.

    Args:
        target: Canal de referencia.
        pool: Canales candidatos (no se incluye el propio objetivo).
        limit: Número máximo de resultados.
        min_score: Umbral mínimo de similitud (0..1).

    Returns:
        Lista ordenada de :class:`SimilarChannel`.
    """
    candidates: list[SimilarChannel] = []
    for channel in pool:
        if channel.channel_id == target.channel_id:
            continue
        score, _ = similarity_score(target, channel)
        if score < min_score:
            continue
        same_category = bool(
            target.category is not None and target.category == channel.category
        )
        candidates.append(
            SimilarChannel(
                rank=0,
                channel=channel,
                score=score,
                shared_topics=shared_topics(target, channel),
                same_category=same_category,
            )
        )
    candidates.sort(key=lambda item: item.score, reverse=True)
    for index, item in enumerate(candidates[:limit], start=1):
        item.rank = index
    return candidates[:limit]
