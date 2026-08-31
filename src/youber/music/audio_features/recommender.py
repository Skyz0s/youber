"""Recomendación de música basada en características de audio.

:class:`FeatureRecommender` compara perfiles de audio (:class:`AudioProfile`)
mediante una distancia euclídea **ponderada** sobre el vector de
características normalizado y sugiere las pistas más parecidas a una de
referencia (o a un perfil objetivo).

Ética: es análisis descriptivo sobre features de audio; no manipula
métricas ni descarga contenido.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from youber.music.audio_features.models import AudioFeatures, AudioProfile

# Peso de cada característica en la distancia (los más perceptivos pesan más).
_FEATURE_WEIGHTS: dict[str, float] = {
    "energy": 1.5,
    "danceability": 1.3,
    "valence": 1.2,
    "acousticness": 1.0,
    "instrumentalness": 1.0,
    "liveness": 0.5,
    "speechiness": 0.5,
    "tempo": 0.8,  # normalizado a 0..1
}

_DEFAULT_DURATION_MS = 180_000  # para normalizar tempo (BPM máx. ~240)


class RecommendedTrack(BaseModel):
    """Pista recomendada con su puntuación de similitud."""

    rank: int
    track_id: str
    track_title: str
    artist: str
    score: float
    shared_moods: list[str] = Field(default_factory=list)
    features: AudioFeatures


def feature_vector(features: AudioFeatures) -> dict[str, float]:
    """Vector de características normalizado a 0..1 (para distancias)."""
    return {
        "danceability": features.danceability,
        "energy": features.energy,
        "valence": features.valence,
        "acousticness": features.acousticness,
        "instrumentalness": features.instrumentalness,
        "liveness": features.liveness,
        "speechiness": features.speechiness,
        "tempo": min(features.tempo / _DEFAULT_DURATION_MS, 1.0),
    }


def weighted_distance(a: AudioFeatures, b: AudioFeatures) -> float:
    """Distancia euclídea ponderada entre dos conjuntos de features."""
    va, vb = feature_vector(a), feature_vector(b)
    total = 0.0
    for key, weight in _FEATURE_WEIGHTS.items():
        total += weight * (va[key] - vb[key]) ** 2
    return math.sqrt(total / sum(_FEATURE_WEIGHTS.values()))


def similarity_score(a: AudioFeatures, b: AudioFeatures) -> float:
    """Similitud 0..1 a partir de la distancia ponderada."""
    return round(max(0.0, 1.0 - weighted_distance(a, b)), 4)


def _shared_moods(a: AudioProfile, b: AudioProfile) -> list[str]:
    return sorted(set(a.moods) & set(b.moods))


class FeatureRecommender:
    """Recomienda pistas por similitud de características de audio.

    Args:
        limit: Número de recomendaciones por defecto.
        min_score: Umbral mínimo de similitud (0..1).
    """

    def __init__(self, limit: int = 5, min_score: float = 0.0) -> None:
        self.limit = limit
        self.min_score = min_score

    def recommend(
        self,
        target: AudioProfile,
        catalog: list[AudioProfile],
        limit: int | None = None,
    ) -> list[RecommendedTrack]:
        """Recomienda las pistas del catálogo más parecidas a ``target``.

        Args:
            target: Perfil de referencia.
            catalog: Perfiles candidatos (se excluye el propio ``target``).
            limit: Máximo de recomendaciones (por defecto el de la clase).

        Returns:
            Lista ordenada de :class:`RecommendedTrack`.
        """
        max_results = limit if limit is not None else self.limit
        candidates: list[RecommendedTrack] = []
        for profile in catalog:
            if profile.track_id == target.track_id:
                continue
            score = similarity_score(target.features, profile.features)
            if score < self.min_score:
                continue
            candidates.append(
                RecommendedTrack(
                    rank=0,
                    track_id=profile.track_id,
                    track_title=profile.track_title,
                    artist=profile.artist,
                    score=score,
                    shared_moods=_shared_moods(target, profile),
                    features=profile.features,
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        for index, item in enumerate(candidates[:max_results], start=1):
            item.rank = index
        return candidates[:max_results]
