"""Selección de la canción «que hace falta» para un vídeo (por su letra).

Dado el texto de los metadatos de un vídeo (título, descripción, hashtags),
se extrae un perfil temático con el **mismo léxico** que usa el análisis de
letras (:mod:`youber.music.lyrics_analyzer`) y se puntúa cada pista del
catálogo por la afinidad de su letra (temas + sentimiento) con ese perfil.

Así el flujo «metadatos → letras → vídeo» elige la canción que encaja con el
contenido en lugar de una cualquiera por estado de ánimo.

Todo es offline y determinista: sin llamadas externas ni descargas.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from youber.music.lyrics_analyzer import LyricsAnalysis, LyricsAnalyzer
from youber.music.models import Mood, Track, TrackSource
from youber.music.weights import DEFAULT_WEIGHTS, SelectionWeights

# Pesos del scoring (ajustables; documentados para que la elección sea auditable).
# Valen como *prior*: :class:`~youber.music.weights.SelectionWeights` puede
# reescalarlos con lo aprendido del decision journal (``youber-journal learn``).
THEME_WEIGHT = DEFAULT_WEIGHTS["theme"]  # por tema compartido (× peso del vídeo × peso de la letra)
SENTIMENT_WEIGHT = DEFAULT_WEIGHTS["sentiment"]  # sentimiento de la letra == sentimiento del vídeo
MOOD_WEIGHT = DEFAULT_WEIGHTS["mood"]  # mood etiquetado en la pista == mood del vídeo
KEYWORD_WEIGHT = DEFAULT_WEIGHTS["keyword"]  # por palabra del vídeo presente en título/artista/género
FAVORITE_BONUS = DEFAULT_WEIGHTS["favorite"]  # las favoritas del usuario pesan un poco más
USAGE_PENALTY = DEFAULT_WEIGHTS["usage"]  # por uso previo (rota las canciones entre vídeos)


class TrackMatch(BaseModel):
    """Pista candidata con su puntuación y el motivo de la elección."""

    track_id: str
    title: str
    artist: str | None = None
    score: float = 0.0
    #: Temas emocionales compartidos con el vídeo (ordenados por peso).
    matched_themes: list[str] = Field(default_factory=list)
    #: Explicación legible de por qué se eligió (o no) esta pista.
    reason: str = ""


class TrackBreakdown(BaseModel):
    """Desglose del scoring de una pista: cada señal y cuánto aportó.

    Permite auditar *por qué* ganó una canción y —registrado en el
    decision journal— estudiar después qué señal predice mejor el resultado.
    """

    total: float = 0.0
    theme_score: float = 0.0
    sentiment_score: float = 0.0
    mood_score: float = 0.0
    keyword_score: float = 0.0
    favorite_bonus: float = 0.0
    usage_penalty: float = 0.0
    matched_themes: list[str] = Field(default_factory=list)
    keyword_hits: int = 0

    @property
    def sentiment_match(self) -> bool:
        """``True`` si el sentimiento de la letra coincide con el del vídeo."""
        return self.sentiment_score > 0

    @property
    def mood_match(self) -> bool:
        """``True`` si el mood etiquetado coincide con el objetivo."""
        return self.mood_score > 0


def theme_profile(text: str, analyzer: LyricsAnalyzer | None = None) -> LyricsAnalysis:
    """Perfil temático del texto de los metadatos (temas + sentimiento).

    Reutiliza el analizador de letras: el léxico emocional es el mismo, así
    que los temas del vídeo y los de las letras son directamente comparables.
    """
    return (analyzer or LyricsAnalyzer()).analyze_lyrics(text or "")


def _text_score(track: Track, keywords: Sequence[str]) -> float:
    """Coincidencias de las palabras del vídeo en título/artista/género."""
    haystack = " ".join(
        part.lower()
        for part in (track.title, track.artist or "", track.genre or "")
        if part
    )
    return float(
        sum(1.0 for word in keywords if word and word.lower() in haystack)
    )


def score_breakdown(
    track: Track,
    *,
    themes: dict[str, float] | None = None,
    sentiment: str = "neutral",
    mood: Mood | None = None,
    keywords: Sequence[str] = (),
    weights: SelectionWeights | None = None,
) -> TrackBreakdown:
    """Desglosa la puntuación de una pista señal a señal.

    Es la versión auditable de :func:`score_track_for_profile`: devuelve la
    aportación de cada señal (tema, sentimiento, mood, keywords, favorita y
    penalización por uso) además del total.

    Args:
        track: Pista del catálogo.
        themes: Temas del vídeo → peso (0..1).
        sentiment: Sentimiento del vídeo (``positive``/``negative``/``neutral``).
        mood: Mood objetivo (opcional).
        keywords: Palabras clave del vídeo (opcional).
        weights: Pesos a usar (p. ej. los aprendidos del journal). Si es
            ``None``, se usan los de por defecto.

    Returns:
        El :class:`TrackBreakdown` con el total y cada aportación.
    """
    profile = themes or {}
    active = weights.as_dict() if weights is not None else DEFAULT_WEIGHTS
    breakdown = TrackBreakdown()

    for theme, video_weight in sorted(
        profile.items(), key=lambda item: item[1], reverse=True
    ):
        track_weight = track.lyrical_themes.get(theme)
        if track_weight:
            breakdown.theme_score += (
                active["theme"] * float(video_weight) * float(track_weight)
            )
            breakdown.matched_themes.append(theme)

    if sentiment != "neutral" and track.lyrical_sentiment == sentiment:
        breakdown.sentiment_score = active["sentiment"]
    if mood is not None and mood in track.moods:
        breakdown.mood_score = active["mood"]
    breakdown.keyword_hits = int(_text_score(track, keywords))
    breakdown.keyword_score = active["keyword"] * breakdown.keyword_hits
    if track.favorite:
        breakdown.favorite_bonus = active["favorite"]
    breakdown.usage_penalty = active["usage"] * track.usage_count
    breakdown.total = (
        breakdown.theme_score
        + breakdown.sentiment_score
        + breakdown.mood_score
        + breakdown.keyword_score
        + breakdown.favorite_bonus
        - breakdown.usage_penalty
    )
    return breakdown


def score_track_for_profile(
    track: Track,
    *,
    themes: dict[str, float] | None = None,
    sentiment: str = "neutral",
    mood: Mood | None = None,
    keywords: Sequence[str] = (),
    weights: SelectionWeights | None = None,
) -> tuple[float, list[str]]:
    """Puntúa una pista contra el perfil temático de un vídeo.

    Args:
        track: Pista del catálogo.
        themes: Temas del vídeo → peso (0..1).
        sentiment: Sentimiento del vídeo (``positive``/``negative``/``neutral``).
        mood: Mood objetivo (opcional).
        keywords: Palabras clave del vídeo (opcional).
        weights: Pesos a usar (por defecto, los del prior).

    Returns:
        ``(puntuación, temas_compartidos)`` con los temas ordenados por peso.
    """
    breakdown = score_breakdown(
        track,
        themes=themes,
        sentiment=sentiment,
        mood=mood,
        keywords=keywords,
        weights=weights,
    )
    return breakdown.total, list(breakdown.matched_themes)


def _reason(
    track: Track,
    matched: list[str],
    sentiment: str,
    mood: Mood | None,
) -> str:
    """Explica en una línea por qué la pista encaja con el vídeo."""
    parts: list[str] = []
    if matched:
        themes = ", ".join(
            f"{theme} ({track.lyrical_themes[theme]:.2f})" for theme in matched
        )
        parts.append(f"letra comparte tema {themes}")
    if sentiment != "neutral" and track.lyrical_sentiment == sentiment:
        parts.append(f"sentimiento {sentiment} coincide")
    if mood is not None and mood in track.moods:
        parts.append(f"mood «{mood.value}» coincide")
    if track.favorite:
        parts.append("favorita")
    return " · ".join(parts) if parts else "sin coincidencia temática (fallback)"


def select_tracks(
    tracks: Iterable[Track],
    profile: LyricsAnalysis | None = None,
    *,
    mood: Mood | None = None,
    keywords: Sequence[str] = (),
    limit: int = 5,
    require_lyrics: bool = False,
    require_local: bool = False,
    weights: SelectionWeights | None = None,
) -> list[TrackMatch]:
    """Ordena las pistas del catálogo por afinidad con el perfil del vídeo.

    Args:
        tracks: Pistas candidatas (normalmente de :class:`MusicLibrary`).
        profile: Perfil temático del vídeo (:func:`theme_profile`).
        mood: Mood objetivo (opcional; p. ej. el que sugiere el guion).
        keywords: Palabras clave del vídeo (opcional).
        limit: Número máximo de candidatas a devolver.
        require_lyrics: Si ``True``, ignora las pistas sin letra analizada.
        require_local: Si ``True``, ignora las pistas sin fichero de audio
            (importadas de plataformas): solo se puede montar audio propio.
        weights: Pesos a usar (los aprendidos del journal, si se quiere).

    Returns:
        Lista de :class:`TrackMatch` ordenada por puntuación (mayor primero).
    """
    themes = profile.themes if profile else {}
    sentiment = profile.sentiment if profile else "neutral"
    candidates = [
        track
        for track in tracks
        if (not require_lyrics or track.lyrical_themes)
        and (not require_local or track.source == TrackSource.LOCAL)
    ]
    matches: list[TrackMatch] = []
    for track in candidates:
        score, matched = score_track_for_profile(
            track,
            themes=themes,
            sentiment=sentiment,
            mood=mood,
            keywords=keywords,
            weights=weights,
        )
        matches.append(
            TrackMatch(
                track_id=track.id,
                title=track.title,
                artist=track.artist,
                score=round(score, 4),
                matched_themes=matched,
                reason=_reason(track, matched, sentiment, mood),
            )
        )
    matches.sort(key=lambda match: match.score, reverse=True)
    return matches[:limit]


def select_best_track(
    tracks: Iterable[Track],
    profile: LyricsAnalysis | None = None,
    *,
    mood: Mood | None = None,
    keywords: Sequence[str] = (),
    require_lyrics: bool = False,
    require_local: bool = False,
    weights: SelectionWeights | None = None,
) -> TrackMatch | None:
    """Devuelve la mejor candidata del catálogo (o ``None`` si no hay pistas)."""
    matches = select_tracks(
        tracks,
        profile,
        mood=mood,
        keywords=keywords,
        limit=1,
        require_lyrics=require_lyrics,
        require_local=require_local,
        weights=weights,
    )
    return matches[0] if matches else None
