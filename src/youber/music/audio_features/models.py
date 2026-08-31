"""Modelos de características de audio (spec Fase 14).

Define :class:`AudioFeatures` (los 13 atributos de audio que expone la API
de Spotify, con sus rangos de validación) y :class:`AudioProfile` (perfil
completo de una canción para recomendación: features + moods sugeridos,
tags de búsqueda y buckets descriptivos).

Límites éticos: los features se obtienen de la API oficial de Spotify
(conforme a ToS) o de un **estimador local** (heurística educativa marcada
con ``confidence`` baja). No se descargan ficheros y no se manipulan
métricas: esto es análisis descriptivo.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from youber.music.models import Mood


class AudioFeatures(BaseModel):
    """Características de audio de una canción (rango 0-1 salvo indicación)."""

    danceability: float = Field(ge=0.0, le=1.0, description="Bailabilidad (0-1)")
    energy: float = Field(ge=0.0, le=1.0, description="Energía (0-1)")
    valence: float = Field(ge=0.0, le=1.0, description="Positividad/alegría (0-1)")
    acousticness: float = Field(ge=0.0, le=1.0, description="Acusticidad (0-1)")
    instrumentalness: float = Field(ge=0.0, le=1.0, description="Instrumentalidad (0-1)")
    liveness: float = Field(ge=0.0, le=1.0, description="En vivo (0-1)")
    speechiness: float = Field(ge=0.0, le=1.0, description="Habla (0-1)")
    tempo: float = Field(ge=0.0, description="Tempo en BPM")
    duration_ms: int = Field(ge=0, description="Duración en milisegundos")
    key: int = Field(ge=-1, le=11, description="Tonalidad (-1 = sin tonalidad)")
    mode: int = Field(ge=0, le=1, description="Mayor (1) o Menor (0)")
    time_signature: int = Field(ge=3, le=7, description="Compás")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=1.0,
        description="Confianza en los datos (1.0 = API, <1.0 = estimación local)",
    )

    @property
    def source(self) -> str:
        """Origen de los datos: ``api`` si confianza total, si no ``estimator``."""
        return "api" if self.confidence >= 1.0 else "estimator"


class AudioProfile(BaseModel):
    """Perfil completo de una canción para recomendación."""

    track_id: str
    track_title: str
    artist: str
    features: AudioFeatures
    moods: list[str] = Field(
        default_factory=list,
        description="Estados de ánimo sugeridos por los features",
    )
    recommendation_tags: list[str] = Field(
        default_factory=list,
        description="Tags para búsqueda",
    )
    energy_level: str = "media"  # "baja", "media", "alta"
    valence_bucket: str = "neutral"  # "triste", "neutral", "alegre"
    tempo_bucket: str = "medio"  # "lento", "medio", "rápido"
    dance_bucket: str = "media"  # "baja", "media", "alta"


# ---------------------------------------------------------------------------
# Buckets descriptivos (funciones puras, offline-testables)
# ---------------------------------------------------------------------------


def energy_level_for(energy: float) -> str:
    """Clasifica la energía en baja/media/alta."""
    if energy < 0.4:
        return "baja"
    if energy < 0.7:
        return "media"
    return "alta"


def valence_bucket_for(valence: float) -> str:
    """Clasifica la positividad en triste/neutral/alegre."""
    if valence < 0.35:
        return "triste"
    if valence < 0.65:
        return "neutral"
    return "alegre"


def tempo_bucket_for(tempo: float) -> str:
    """Clasifica el tempo en lento/medio/rápido (BPM)."""
    if tempo < 90:
        return "lento"
    if tempo < 130:
        return "medio"
    return "rápido"


def dance_bucket_for(danceability: float) -> str:
    """Clasifica la bailabilidad en baja/media/alta."""
    if danceability < 0.4:
        return "baja"
    if danceability < 0.7:
        return "media"
    return "alta"


def suggest_moods(features: AudioFeatures) -> list[str]:
    """Estados de ánimo sugeridos por los features (valores de :class:`Mood`).

    Reglas simples basadas en energía, positividad y tempo; devuelve
    valores del catálogo (``Mood.value``) para que encajen con las
    búsquedas existentes.
    """
    moods: list[str] = []
    if features.energy >= 0.7:
        moods.append(Mood.ENERGETIC.value)
    elif features.energy <= 0.3:
        moods.append(Mood.RELAXING.value)
    if features.valence >= 0.65:
        moods.append(Mood.HAPPY.value)
    elif features.valence <= 0.35:
        moods.append(Mood.SAD.value)
    if features.instrumentalness >= 0.5:
        moods.append(Mood.FOCUSED.value)
    if not moods:
        moods.append(Mood.CUSTOM.value)
    return moods


def suggest_tags(features: AudioFeatures) -> list[str]:
    """Tags de búsqueda sugeridos a partir de los features."""
    tags: list[str] = []
    if features.danceability >= 0.7:
        tags.append("bailable")
    if features.acousticness >= 0.6:
        tags.append("acústico")
    if features.instrumentalness >= 0.5:
        tags.append("instrumental")
    if features.liveness >= 0.7:
        tags.append("en vivo")
    if features.speechiness >= 0.6:
        tags.append("hablado")
    tags.append(tempo_bucket_for(features.tempo))
    tags.append(energy_level_for(features.energy))
    return tags


def build_profile(
    track_id: str,
    track_title: str,
    artist: str,
    features: AudioFeatures,
) -> AudioProfile:
    """Construye un :class:`AudioProfile` completo desde los features."""
    return AudioProfile(
        track_id=track_id,
        track_title=track_title,
        artist=artist,
        features=features,
        moods=suggest_moods(features),
        recommendation_tags=suggest_tags(features),
        energy_level=energy_level_for(features.energy),
        valence_bucket=valence_bucket_for(features.valence),
        tempo_bucket=tempo_bucket_for(features.tempo),
        dance_bucket=dance_bucket_for(features.danceability),
    )
