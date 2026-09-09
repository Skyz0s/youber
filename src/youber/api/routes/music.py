"""Ruta ``music`` — catálogo local: listado, búsqueda y letras."""

from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path
from typing import Any

from youber.api.models import ApiError
from youber.music.library import MusicLibrary, find_track
from youber.music.models import Track
from youber.sync.pipeline import find_sidecar_lyrics
from youber.sync.timestamps import parse_lyrics_file

DEFAULT_LIBRARY = Path("music")
MAX_LIMIT = 200

_LYRICS_SUFFIXES = (".txt", ".lrc", ".srt")


def _limit(params: dict[str, Any], default: int = 50) -> int:
    raw = params.get("limit", default)
    try:
        return max(1, min(int(raw), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _user_config() -> dict[str, Any]:
    """Configuración opcional de usuario en ``~/.youber/config.json``.

    Permite fijar el catálogo de música y la carpeta de letras del
    dashboard sin tocar el código (rutas locales de cada despliegue):

    .. code-block:: json

        {
          "music_dir": "C:/Users/.../Music",
          "lyrics_dir": "C:/Users/.../suno_letras"
        }

    La ruta del fichero se puede redirigir con ``YOUBER_CONFIG``.
    """
    path = Path(
        os.environ.get("YOUBER_CONFIG") or (Path.home() / ".youber" / "config.json")
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _env_or_config(key: str, env: str) -> str | None:
    value = os.environ.get(env, "").strip()
    if value:
        return value
    raw = _user_config().get(key)
    return str(raw) if raw else None


def resolve_library_dir(params: dict[str, Any]) -> Path:
    """Directorio del catálogo: parámetro ``library`` → env → config → ``music``."""
    raw = params.get("library")
    if raw:
        return Path(str(raw))
    override = _env_or_config("music_dir", "YOUBER_MUSIC_DIR")
    return Path(override) if override else DEFAULT_LIBRARY


def resolve_lyrics_dir(params: dict[str, Any]) -> Path | None:
    """Carpeta de letras: parámetro ``lyrics_dir`` → env → config (opcional)."""
    raw = params.get("lyrics_dir")
    if raw:
        return Path(str(raw))
    override = _env_or_config("lyrics_dir", "YOUBER_LYRICS_DIR")
    return Path(override) if override else None


def _normalize(text: str) -> str:
    """Normaliza un título para comparar sin acentos/espacios/símbolos."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in folded.lower() if ch.isalnum())


def _find_lyrics_in_dir(track: Track, lyrics_dir: Path) -> Path | None:
    """Busca la letra de una pista en una carpeta por título normalizado.

    Compara el título/fichero de la pista contra el nombre (sin extensión)
    de los ficheros de letra: ``Caos.wav`` ↔ ``Caos.txt``,
    ``Justodelante.wav`` ↔ ``Justo delante.txt``. Si no hay coincidencia
    exacta, acepta prefijos (``HALLWAY.wav`` ↔ ``HALLWAY (KEEP IT CLEAN).txt``).
    """
    if not lyrics_dir.is_dir():
        return None
    title_norm = _normalize(track.title)
    wanted = {title_norm, _normalize(Path(track.file_path).stem)}
    wanted.discard("")
    candidates: list[Path] = []
    for suffix in _LYRICS_SUFFIXES:
        candidates.extend(sorted(lyrics_dir.glob(f"*{suffix}")))
    candidates.sort(key=lambda p: (len(p.stem), p.stem))
    for candidate in candidates:
        stem_norm = _normalize(candidate.stem)
        if stem_norm in wanted:
            return candidate
    # Prefijo: el título normalizado es prefijo del nombre de la letra
    # (variantes tipo ``(Remix)``, ``(Edit)``, ``(CAT)``).
    if len(title_norm) >= 4:
        for candidate in candidates:
            if _normalize(candidate.stem).startswith(title_norm):
                return candidate
    return None


async def list_tracks(params: dict[str, Any]) -> dict[str, Any]:
    """Lista las pistas del catálogo (hasta 50 por defecto)."""
    library = MusicLibrary(resolve_library_dir(params))
    try:
        tracks = library.all()[:_limit(params)]
    finally:
        library.close()
    return {
        "library": str(resolve_library_dir(params)),
        "count": len(tracks),
        "tracks": [track.model_dump(mode="json") for track in tracks],
    }


async def search_tracks(params: dict[str, Any]) -> dict[str, Any]:
    """Busca pistas por texto libre (título/artista/género)."""
    query = str(params.get("query", "")).strip()
    if not query:
        raise ApiError("Falta el parámetro 'query' (texto a buscar)")
    library = MusicLibrary(resolve_library_dir(params))
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
    """Letra de una pista (ID exacto o texto).

    Fuentes, por orden: sidecar junto al audio (``.lrc``/``.srt``/``.txt``),
    fichero de la carpeta de letras configurada (``lyrics_dir``) que
    coincida por título normalizado, o hint explicativo.
    """
    query = str(params.get("query", "")).strip()
    if not query:
        raise ApiError("Falta el parámetro 'query' (ID o título de la pista)")

    library = MusicLibrary(resolve_library_dir(params))
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
        lyrics_dir = resolve_lyrics_dir(params)
        if lyrics_dir is not None:
            match = _find_lyrics_in_dir(track, lyrics_dir)
            if match is not None:
                document = parse_lyrics_file(match)
                return {
                    "track": track.model_dump(mode="json"),
                    "lyrics": document.model_dump(mode="json"),
                    "source_file": str(match),
                }
        searched = f" (tampoco en {lyrics_dir})" if lyrics_dir else ""
        return {
            "track": track.model_dump(mode="json"),
            "lyrics": None,
            "hint": (
                f"No hay fichero de letra junto a {audio.name}{searched}. Coloca "
                f"{audio.stem}.lrc/.txt/.srt, añádela a la carpeta de letras "
                "(config lyrics_dir) o usa youber-sync align --whisper."
            ),
        }
    document = parse_lyrics_file(sidecar)
    return {
        "track": track.model_dump(mode="json"),
        "lyrics": document.model_dump(mode="json"),
        "source_file": str(sidecar),
    }
