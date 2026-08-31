"""Análisis musical: características de audio del catálogo (Fase 14).

Enriquece el catálogo local de música con **audio features** usando la
**API oficial de Spotify** como fuente primaria (``confidence=1.0``) y un
**estimador local** heurístico como fallback (``confidence=0.5``). Incluye
emparejamiento de canciones, perfiles para recomendación, enriquecido del
catálogo y recomendaciones por similitud de características.

Límites éticos (igual que el resto del framework):

- Solo metadatos públicos vía API oficial (conforme a ToS); sin descargar
  ficheros.
- El estimador local es una estimación educativa, siempre marcada con
  ``confidence < 1.0`` y nunca presentada como dato real.
- Sin manipulación de métricas: esto es análisis descriptivo.
"""

from youber.music.audio_features.analyzer import AudioAnalyzer
from youber.music.audio_features.enricher import (
    DEFAULT_STORE_PATH,
    AudioFeatureStore,
    CatalogEnricher,
    EnrichResult,
)
from youber.music.audio_features.estimator import DEFAULT_CONFIDENCE, LocalEstimator
from youber.music.audio_features.matcher import (
    TrackMatcher,
    artist_score,
    match_score,
    normalize,
    title_score,
)
from youber.music.audio_features.models import (
    AudioFeatures,
    AudioProfile,
    build_profile,
    dance_bucket_for,
    energy_level_for,
    suggest_moods,
    suggest_tags,
    tempo_bucket_for,
    valence_bucket_for,
)
from youber.music.audio_features.recommender import (
    FeatureRecommender,
    RecommendedTrack,
    feature_vector,
    similarity_score,
    weighted_distance,
)
from youber.music.audio_features.spotify import SpotifyClient

__all__ = [
    "AudioAnalyzer",
    "AudioFeatureStore",
    "AudioFeatures",
    "AudioProfile",
    "CatalogEnricher",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_STORE_PATH",
    "EnrichResult",
    "FeatureRecommender",
    "LocalEstimator",
    "RecommendedTrack",
    "SpotifyClient",
    "TrackMatcher",
    "artist_score",
    "build_profile",
    "dance_bucket_for",
    "energy_level_for",
    "feature_vector",
    "match_score",
    "normalize",
    "similarity_score",
    "suggest_moods",
    "suggest_tags",
    "tempo_bucket_for",
    "title_score",
    "valence_bucket_for",
    "weighted_distance",
]
