"""Búsqueda y sugerencias por estado de ánimo/tema del catálogo de música.

Funciones puras para filtrar pistas por mood, género, texto o favoritos, y
para sugerir pistas según el estado de ánimo deseado (con scoring simple:
mood coincidente, favoritas primero, menos usadas antes).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from youber.music.models import Mood, Track

_WORD_RE = re.compile(r"\w+")


def _text_score(track: Track, text: str | None) -> float:
    """Puntuación por coincidencia de texto en título/artista/género."""
    if not text:
        return 0.0
    haystack = " ".join(
        part.lower()
        for part in (track.title, track.artist or "", track.genre or "")
        if part
    )
    words = [w.lower() for w in _WORD_RE.findall(text)]
    return sum(1.0 for word in words if word in haystack)


def search_tracks(
    tracks: Iterable[Track],
    mood: Mood | None = None,
    genre: str | None = None,
    text: str | None = None,
    favorite: bool | None = None,
    bpm_min: int | None = None,
    bpm_max: int | None = None,
    lyrical_theme: str | None = None,
    lyrical_sentiment: str | None = None,
) -> list[Track]:
    """Filtra las pistas según los criterios indicados (todos opcionales).

    Args:
        tracks: Pistas candidatas.
        mood: Estado de ánimo requerido (la pista debe tenerlo etiquetado).
        genre: Género (coincidencia parcial, sin distinguir mayúsculas).
        text: Texto libre contra título/artista/género.
        favorite: ``True`` solo favoritas, ``False`` solo no favoritas.
        bpm_min / bpm_max: Rango de BPM (inclusivo).
        lyrical_theme: Tema detectado en la letra (p. ej. ``tristeza``).
        lyrical_sentiment: Sentimiento de la letra (``positive``/``negative``/``neutral``).

    Returns:
        Lista de pistas que cumplen todos los filtros.
    """
    results: list[Track] = []
    for track in tracks:
        if mood is not None and mood not in track.moods:
            continue
        if genre and genre.lower() not in (track.genre or "").lower():
            continue
        if text and _text_score(track, text) == 0.0:
            continue
        if favorite is not None and track.favorite != favorite:
            continue
        if bpm_min is not None and (track.bpm or 0) < bpm_min:
            continue
        if bpm_max is not None and (track.bpm or 0) > bpm_max:
            continue
        if lyrical_theme and lyrical_theme not in track.lyrical_themes:
            continue
        if lyrical_sentiment and track.lyrical_sentiment != lyrical_sentiment:
            continue
        results.append(track)
    return results


def score_track(
    track: Track,
    mood: Mood | None = None,
    text: str | None = None,
    lyrical_theme: str | None = None,
) -> float:
    """Puntuación de una pista para sugerencias (mayor = mejor).

    Puntos: mood coincidente +5, favorita +2, texto +1 por palabra,
    tema lírico coincidente +1.5 (escalado por su peso),
    descuento por uso (0.1 por uso, para rotar las sugerencias).
    """
    score = 0.0
    if mood is not None and mood in track.moods:
        score += 5.0
    if track.favorite:
        score += 2.0
    score += _text_score(track, text)
    if lyrical_theme and lyrical_theme in track.lyrical_themes:
        score += 1.5 * track.lyrical_themes[lyrical_theme]
    score -= 0.1 * track.usage_count
    return score


def suggest_tracks(
    tracks: Iterable[Track],
    mood: Mood | None = None,
    text: str | None = None,
    limit: int = 5,
    lyrical_theme: str | None = None,
) -> list[Track]:
    """Sugiere las mejores pistas para un estado de ánimo/tema.

    Ordena por :func:`score_track` descendente y devuelve las ``limit``
    primeras (favoritas y menos usadas primero, mood coincidente arriba).

    Args:
        tracks: Pistas candidatas.
        mood: Estado de ánimo deseado (opcional).
        text: Tema o texto libre (opcional).
        limit: Número máximo de sugerencias.
        lyrical_theme: Tema presente en la letra (opcional).

    Returns:
        Lista ordenada de pistas sugeridas.
    """
    ranked = sorted(
        tracks,
        key=lambda track: score_track(
            track, mood=mood, text=text, lyrical_theme=lyrical_theme
        ),
        reverse=True,
    )
    return ranked[:limit]
