"""Ruta ``music`` — catálogo local: listado, búsqueda y letras."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from youber.api.models import ApiError
from youber.music.library import MusicLibrary, find_track
from youber.sync.pipeline import find_sidecar_lyrics
from youber.sync.timestamps import parse_lyrics_file

DEFAULT_LIBRARY = Path("music")
MAX_LIMIT = 200


def _limit(params: dict[str, Any], default: int = 50) -> int:
    raw = params.get("limit", default)
    try:
        return max(1, min(int(raw), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _library_dir(params: dict[str, Any]) -> Path:
    return Path(str(params.get("library", DEFAULT_LIBRARY)))


async def list_tracks(params: dict[str, Any]) -> dict[str, Any]:
    """Lista las pistas del catálogo (hasta 50 por defecto)."""
    library = MusicLibrary(_library_dir(params))
    try:
        tracks = library.all()[:_limit(params)]
    finally:
        library.close()
    return {
        "library": str(_library_dir(params)),
        "count": len(tracks),
        "tracks": [track.model_dump(mode="json") for track in tracks],
    }


async def search_tracks(params: dict[str, Any]) -> dict[str, Any]:
    """Busca pistas por texto libre (título/artista/género)."""
    query = str(params.get("query", "")).strip()
    if not query:
        raise ApiError("Falta el parámetro 'query' (texto a buscar)")
    library = MusicLibrary(_library_dir(params))
    try:
        tracks = library.search(text=query)[:_limit(params)]
    finally:
        library.close()
    return {
        "query": query,
        "count": len(tracks),
        "tracks": [track.model_dump(mode="json") for track in tracks],
    }


async def get_lyrics(params: dict[str, Any]) -> dict[str, Any]:
    """Letra de una pista (ID exacto o texto). Busca un sidecar junto al audio."""
    query = str(params.get("query", "")).strip()
    if not query:
        raise ApiError("Falta el parámetro 'query' (ID o título de la pista)")

    library = MusicLibrary(_library_dir(params))
    try:
        track = find_track(library, query)
    finally:
        library.close()
    if track is None:
        raise ApiError(
            f"Pista no encontrada en el catálogo: {query!r} "
            "(revisa 'library'; escanea con youber-music scan)"
        )

    audio = Path(track.file_path)
    sidecar = find_sidecar_lyrics(audio)
    if sidecar is None:
        return {
            "track": track.model_dump(mode="json"),
            "lyrics": None,
            "hint": (
                f"No hay fichero de letra junto a {audio.name}. Coloca "
                f"{audio.stem}.lrc/.txt/.srt o usa youber-sync align --whisper."
            ),
        }
    document = parse_lyrics_file(sidecar)
    return {
        "track": track.model_dump(mode="json"),
        "lyrics": document.model_dump(mode="json"),
        "source_file": str(sidecar),
    }
