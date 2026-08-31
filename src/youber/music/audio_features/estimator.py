"""Modelo de estimación local de características de audio (fallback).

Cuando no hay credenciales de Spotify (o la API no encuentra la canción),
este módulo **estima** las características de audio a partir de los
metadatos del catálogo local (género, BPM, mood, duración) usando
heurísticas deterministas y documentadas.

Ética: es una **estimación educativa** (``confidence=0.5``), nunca se
presenta como dato real de la API. No se manipulan métricas: se infieren
valores plausibles para que el sistema funcione sin conexión.
"""

from __future__ import annotations

from youber.music.audio_features.models import AudioFeatures

# Perfiles por género: (tempo, energy, valence, danceability, acousticness,
# instrumentalness, liveness, speechiness) — heurísticas razonables.
_GENRE_PROFILES: dict[str, tuple[float, float, float, float, float, float, float, float]] = {
    "electronic": (125.0, 0.85, 0.55, 0.80, 0.10, 0.60, 0.30, 0.05),
    "dance": (128.0, 0.90, 0.65, 0.85, 0.08, 0.50, 0.35, 0.05),
    "pop": (105.0, 0.75, 0.70, 0.70, 0.25, 0.05, 0.30, 0.08),
    "rock": (115.0, 0.80, 0.50, 0.45, 0.15, 0.05, 0.60, 0.05),
    "metal": (140.0, 0.90, 0.30, 0.35, 0.05, 0.03, 0.55, 0.05),
    "jazz": (95.0, 0.50, 0.55, 0.60, 0.70, 0.30, 0.80, 0.10),
    "blues": (90.0, 0.55, 0.40, 0.55, 0.60, 0.15, 0.85, 0.10),
    "classical": (90.0, 0.25, 0.35, 0.25, 0.85, 0.90, 0.70, 0.03),
    "acoustic": (95.0, 0.35, 0.55, 0.45, 0.80, 0.20, 0.50, 0.05),
    "lofi": (80.0, 0.30, 0.45, 0.55, 0.60, 0.70, 0.20, 0.10),
    "reggaeton": (95.0, 0.80, 0.65, 0.85, 0.10, 0.05, 0.30, 0.15),
    "hip hop": (92.0, 0.75, 0.60, 0.80, 0.15, 0.05, 0.40, 0.30),
    "rap": (90.0, 0.70, 0.50, 0.75, 0.10, 0.03, 0.35, 0.60),
    "ambient": (70.0, 0.20, 0.30, 0.25, 0.80, 0.85, 0.15, 0.03),
    "podcast": (100.0, 0.40, 0.50, 0.40, 0.30, 0.10, 0.60, 0.70),
}

# Ajustes por mood (multiplicadores sobre el perfil de género).
_MOOD_ENERGY: dict[str, float] = {
    "energética": 1.2,
    "épica": 1.15,
    "relajante": 0.6,
    "triste": 0.7,
    "productiva": 0.95,
}
_MOOD_VALENCE: dict[str, float] = {
    "alegre": 1.3,
    "triste": 0.5,
    "relajante": 0.85,
}

DEFAULT_CONFIDENCE = 0.5  # Estimación local (no dato real de API).


class LocalEstimator:
    """Estima características de audio a partir de metadatos (fallback).

    Método principal: :meth:`estimate`. La salida lleva
    ``confidence=0.5`` para distinguirla de los datos reales de la API.
    """

    def estimate(
        self,
        genre: str | None = None,
        bpm: int | None = None,
        duration_ms: int | None = None,
        moods: list[str] | None = None,
    ) -> AudioFeatures:
        """Estima las características de audio de una canción.

        Args:
            genre: Género de la pista (perfil base).
            bpm: Tempo conocido (anula el tempo del perfil de género).
            duration_ms: Duración en milisegundos.
            moods: Estados de ánimo conocidos (ajustan energía/valencia).

        Returns:
            :class:`AudioFeatures` con ``confidence=0.5`` (estimación).
        """
        profile = self._profile_for(genre)
        tempo, energy, valence, danceability, acousticness = profile[:5]
        instrumentalness, liveness, speechiness = profile[5:]

        if bpm is not None and bpm > 0:
            tempo = float(bpm)

        energy = self._adjust_energy(energy, moods)
        valence = self._adjust_valence(valence, moods)

        # La bailabilidad sube con el tempo (heurística simple).
        if tempo >= 110:
            danceability = min(1.0, danceability + 0.15)

        return AudioFeatures(
            danceability=round(min(max(danceability, 0.0), 1.0), 3),
            energy=round(min(max(energy, 0.0), 1.0), 3),
            valence=round(min(max(valence, 0.0), 1.0), 3),
            acousticness=round(min(max(acousticness, 0.0), 1.0), 3),
            instrumentalness=round(min(max(instrumentalness, 0.0), 1.0), 3),
            liveness=round(min(max(liveness, 0.0), 1.0), 3),
            speechiness=round(min(max(speechiness, 0.0), 1.0), 3),
            tempo=round(tempo, 1),
            duration_ms=duration_ms or 0,
            key=-1,
            mode=1,
            time_signature=4,
            confidence=DEFAULT_CONFIDENCE,
        )

    # -- Internos -----------------------------------------------------------

    @staticmethod
    def _profile_for(genre: str | None) -> tuple[float, float, float, float, float, float, float, float]:
        """Devuelve el perfil base del género (o uno neutro si se desconoce)."""
        if not genre:
            return (105.0, 0.6, 0.5, 0.6, 0.4, 0.3, 0.35, 0.08)
        for key, profile in _GENRE_PROFILES.items():
            if key in genre.lower():
                return profile
        return (105.0, 0.6, 0.5, 0.6, 0.4, 0.3, 0.35, 0.08)

    @staticmethod
    def _adjust_energy(energy: float, moods: list[str] | None) -> float:
        """Ajusta la energía según los moods conocidos."""
        if not moods:
            return energy
        factor = 1.0
        for mood in moods:
            factor *= _MOOD_ENERGY.get(mood.lower(), 1.0)
        return min(1.0, energy * factor)

    @staticmethod
    def _adjust_valence(valence: float, moods: list[str] | None) -> float:
        """Ajusta la valencia (positividad) según los moods conocidos."""
        if not moods:
            return valence
        factor = 1.0
        for mood in moods:
            factor *= _MOOD_VALENCE.get(mood.lower(), 1.0)
        return min(1.0, valence * factor)
