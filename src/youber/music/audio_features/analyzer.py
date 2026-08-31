"""Obtiene características de audio de una canción (Spotify o estimación local).

:class:`AudioAnalyzer` es la puerta de entrada del módulo: intenta primero
la **API de Spotify** (datos reales, ``confidence=1.0``) y, si no hay
credenciales o no encuentra la canción, cae al **estimador local**
(heurística educativa, ``confidence=0.5``).

Ética: los datos de Spotify proceden de la API oficial (conforme a ToS);
la estimación local está marcada explícitamente como estimación y nunca se
presenta como dato real. No se descargan ficheros.
"""

from __future__ import annotations

from loguru import logger

from youber.music.audio_features.estimator import LocalEstimator
from youber.music.audio_features.matcher import TrackMatcher
from youber.music.audio_features.models import AudioFeatures, AudioProfile, build_profile
from youber.music.audio_features.spotify import SpotifyClient


class AudioAnalyzer:
    """Analiza una canción y devuelve su perfil de audio.

    Args:
        spotify: Cliente de Spotify (opcional; se crea uno por defecto).
        estimator: Estimador local (opcional; se crea uno por defecto).
        matcher: Emparejador de canciones (opcional).
    """

    def __init__(
        self,
        spotify: SpotifyClient | None = None,
        estimator: LocalEstimator | None = None,
        matcher: TrackMatcher | None = None,
    ) -> None:
        self.spotify = spotify if spotify is not None else SpotifyClient()
        self.estimator = estimator if estimator is not None else LocalEstimator()
        self.matcher = matcher if matcher is not None else TrackMatcher()

    async def analyze(
        self,
        title: str,
        artist: str | None = None,
        genre: str | None = None,
        bpm: int | None = None,
        duration_ms: int | None = None,
        moods: list[str] | None = None,
        track_id: str = "unknown",
    ) -> AudioProfile:
        """Obtiene el perfil de audio de una canción.

        Estrategia: Spotify primero (si hay credenciales y la canción
        encaja), estimador local como fallback.

        Args:
            title: Título de la canción.
            artist: Artista (opcional).
            genre: Género (usa el estimador local).
            bpm: Tempo conocido (usa el estimador local).
            duration_ms: Duración en milisegundos.
            moods: Estados de ánimo conocidos (usa el estimador local).
            track_id: Identificador de la pista en el catálogo local.

        Returns:
            :class:`AudioProfile` con features y buckets calculados.
        """
        if self.spotify.available:
            features = await self._analyze_via_spotify(title, artist)
            if features is not None:
                logger.debug(f"Audio features de Spotify para «{title}»")
                return build_profile(track_id, title, artist or "", features)

        features = self.estimator.estimate(
            genre=genre,
            bpm=bpm,
            duration_ms=duration_ms,
            moods=moods,
        )
        logger.debug(f"Audio features estimados localmente para «{title}»")
        return build_profile(track_id, title, artist or "", features)

    async def _analyze_via_spotify(self, title: str, artist: str | None) -> AudioFeatures | None:
        """Busca en Spotify y devuelve los features reales (o ``None``)."""
        try:
            candidates = await self.spotify.search_track(title, artist)
        except Exception as exc:  # red, rate-limit, etc.
            logger.warning(f"No se pudo consultar Spotify para «{title}»: {exc}")
            return None
        if not candidates:
            return None
        match = self.matcher.best_match(
            title,
            artist,
            [candidates] if isinstance(candidates, dict) else candidates,
        )
        if match is None:
            logger.debug(f"Sin emparejamiento claro en Spotify para «{title}»")
            return None
        return await self.spotify.get_audio_features(match["track_id"])
