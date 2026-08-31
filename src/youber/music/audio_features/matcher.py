"""Emparejamiento de canciones locales con resultados de Spotify.

Normaliza títulos/artistas (minúsculas, sin acentos ni puntuación) y
puntúa candidatos para elegir el track de Spotify correcto a partir de la
pista local del catálogo (que puede venir de YouTube Music, archivos, etc.).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Normaliza un texto: minúsculas, sin acentos, sin puntuación.

    Ejemplo: ``"Café del Mar"`` → ``"cafe del mar"``.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_ALNUM_RE.sub(" ", ascii_text.lower()).strip()


def title_score(title_a: str, title_b: str) -> float:
    """Puntuación de coincidencia entre dos títulos normalizados (0..1)."""
    norm_a, norm_b = normalize(title_a), normalize(title_b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    if norm_a in norm_b or norm_b in norm_a:
        shorter = min(len(norm_a), len(norm_b))
        return 0.7 if shorter >= 4 else 0.4
    return 0.0


def artist_score(artist_a: str | None, artist_b: str | None) -> float:
    """Puntuación de coincidencia entre artistas (1.0, 0.5 o 0.0)."""
    if not artist_a or not artist_b:
        return 0.5  # artista desconocido: neutral
    norm_a, norm_b = normalize(artist_a), normalize(artist_b)
    if not norm_a or not norm_b:
        return 0.5
    if norm_a == norm_b:
        return 1.0
    if norm_a in norm_b or norm_b in norm_a:
        return 0.8
    return 0.0


def match_score(title_a: str, artist_a: str | None, title_b: str, artist_b: str | None) -> float:
    """Puntuación global de emparejamiento (0..1): título 70 %, artista 30 %."""
    return round(0.7 * title_score(title_a, title_b) + 0.3 * artist_score(artist_a, artist_b), 3)


class TrackMatcher:
    """Elige el mejor candidato de Spotify para una canción local.

    Args:
        threshold: Puntuación mínima para aceptar un emparejamiento.
    """

    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    def best_match(
        self,
        title: str,
        artist: str | None,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Devuelve el candidato con mejor puntuación (o ``None``).

        Args:
            title: Título de la pista local.
            artist: Artista local (puede ser ``None``).
            candidates: Resultados de ``SpotifyClient.search_track``
                (lista de dicts con ``title`` y ``artist``).

        Returns:
            El candidato elegido con su ``score`` añadido, o ``None`` si
            ninguno supera el umbral.
        """
        best: dict[str, Any] | None = None
        best_score = 0.0
        for candidate in candidates:
            score = match_score(
                title,
                artist,
                candidate.get("title", ""),
                candidate.get("artist"),
            )
            if score > best_score:
                best = dict(candidate)
                best["score"] = score
                best_score = score
        if best is not None and best_score >= self.threshold:
            return best
        return None
