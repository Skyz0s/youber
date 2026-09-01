"""Proveedores de catálogo cloud (Apple/iTunes y Spotify) para BARF.

Importa **metadatos públicos** de canciones desde plataformas de streaming
para poblar el catálogo local: título, artista, álbum, duración, género,
carátula y URL de preview. **Nunca descarga audio** (legal/ético, conforme
a ToS): las pistas cloud sirven para estadísticas, búsqueda y mood del
dashboard, no para editar vídeo (eso requiere ficheros locales).

Fuentes:

- **Apple/iTunes Search API** (:func:`search_itunes`): pública, sin API key.
- **Spotify Web API** (:func:`search_spotify`): requiere credenciales de
  desarrollador (``SPOTIFY_CLIENT_ID``/``SPOTIFY_CLIENT_SECRET`` o
  ``~/.youber/spotify_credentials.json``), igual que
  :mod:`youber.music.audio_features.spotify`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger
from pydantic import BaseModel

from youber.music.audio_features.spotify import SpotifyClient
from youber.music.database import MusicDatabase
from youber.music.models import Track, TrackSource

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


class CloudHit(BaseModel):
    """Resultado de búsqueda en una plataforma (solo metadatos públicos)."""

    source: TrackSource
    external_id: str
    title: str
    artist: str | None = None
    album: str | None = None
    duration_s: float | None = None
    genre: str | None = None
    artwork_url: str | None = None
    preview_url: str | None = None


# ---------------------------------------------------------------------------
# Búsquedas
# ---------------------------------------------------------------------------


async def search_itunes(query: str, limit: int = 10) -> list[CloudHit]:
    """Busca canciones en la iTunes Search API de Apple (sin autenticación).

    Args:
        query: Texto de búsqueda (p. ej. ``"lofi beats"``).
        limit: Número máximo de resultados (1-50).

    Returns:
        Lista de :class:`CloudHit` con los metadatos públicos devueltos
        por la API.
    """
    params: dict[str, str | int] = {
        "term": query,
        "media": "music",
        "limit": max(1, min(limit, 50)),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(ITUNES_SEARCH_URL, params=params)
        response.raise_for_status()
        results = response.json().get("results", [])

    hits: list[CloudHit] = []
    for item in results:
        track_id = item.get("trackId")
        if not track_id:
            continue
        hits.append(
            CloudHit(
                source=TrackSource.APPLE,
                external_id=str(track_id),
                title=item.get("trackName", ""),
                artist=item.get("artistName"),
                album=item.get("collectionName"),
                duration_s=(
                    (item.get("trackTimeMillis") or 0) / 1000
                    if item.get("trackTimeMillis")
                    else None
                ),
                genre=item.get("primaryGenreName"),
                artwork_url=item.get("artworkUrl100"),
                preview_url=item.get("previewUrl"),
            )
        )
    logger.debug(f"search_itunes(«{query}»): {len(hits)} resultados")
    return hits


async def search_spotify(
    query: str,
    limit: int = 10,
    client: SpotifyClient | None = None,
) -> list[CloudHit]:
    """Busca canciones en la API de Spotify (requiere credenciales).

    Args:
        query: Texto de búsqueda (p. ej. ``"lofi beats"``).
        limit: Número máximo de resultados.
        client: Cliente de Spotify (por defecto, uno nuevo con las
            credenciales configuradas).

    Returns:
        Lista de :class:`CloudHit` (sin carátula/preview: la API de
        búsqueda de tracks no los incluye en este flujo).

    Raises:
        RuntimeError: si no hay credenciales de Spotify configuradas.
    """
    spotify = client or SpotifyClient()
    if not spotify.available:
        raise RuntimeError(
            "Spotify sin credenciales: define SPOTIFY_CLIENT_ID/SECRET "
            "o crea ~/.youber/spotify_credentials.json"
        )
    results = await spotify.search_tracks(query, limit=limit)
    hits: list[CloudHit] = []
    for item in results:
        track_id = item.get("track_id")
        if not track_id:
            continue
        hits.append(
            CloudHit(
                source=TrackSource.SPOTIFY,
                external_id=track_id,
                title=item.get("title", ""),
                artist=item.get("artist"),
                album=item.get("album"),
                duration_s=(
                    (item.get("duration_ms") or 0) / 1000
                    if item.get("duration_ms")
                    else None
                ),
            )
        )
    logger.debug(f"search_spotify(«{query}»): {len(hits)} resultados")
    return hits


async def search(
    source: TrackSource | str,
    query: str,
    limit: int = 10,
    spotify_client: SpotifyClient | None = None,
) -> list[CloudHit]:
    """Busca en la fuente indicada (``apple`` o ``spotify``)."""
    source = _coerce_source(source)
    if source == TrackSource.APPLE:
        return await search_itunes(query, limit)
    if source == TrackSource.SPOTIFY:
        return await search_spotify(query, limit, client=spotify_client)
    raise ValueError(f"Fuente no soportada: {source.value} (usa apple o spotify)")


def _coerce_source(source: TrackSource | str) -> TrackSource:
    """Convierte a :class:`TrackSource` con un mensaje de error claro."""
    try:
        return TrackSource(source)
    except ValueError as exc:
        raise ValueError(
            f"Fuente no soportada: {source!r} (usa apple o spotify)"
        ) from exc


# ---------------------------------------------------------------------------
# Conversión e importación
# ---------------------------------------------------------------------------


def cloud_path(source: TrackSource, external_id: str) -> Path:
    """Ruta sintética de una pista cloud (no es un fichero real)."""
    return Path(f"cloud:{source.value}:{external_id}")


def to_track(hit: CloudHit) -> Track:
    """Convierte un :class:`CloudHit` en una pista del catálogo.

    La pista queda marcada con su ``source`` y ``external_id``; la ruta
    sintética ``cloud:<source>:<id>`` la distingue de los ficheros locales.
    """
    return Track(
        id="",
        file_path=cloud_path(hit.source, hit.external_id),
        title=hit.title,
        artist=hit.artist,
        duration=hit.duration_s or 0.0,
        genre=hit.genre,
        source=hit.source,
        external_id=hit.external_id,
        album=hit.album,
        artwork_url=hit.artwork_url,
        preview_url=hit.preview_url,
        file_hash=f"cloud:{hit.source.value}:{hit.external_id}",
    )


async def import_cloud(
    query: str,
    source: TrackSource | str = TrackSource.APPLE,
    limit: int = 10,
    db: MusicDatabase | None = None,
    spotify_client: SpotifyClient | None = None,
) -> dict[str, int]:
    """Busca en una plataforma y añade las pistas al catálogo (idempotente).

    Las pistas ya importadas (mismo ``external_id`` y ``source``) se
    omiten, así que repetir la importación no duplica nada.

    Args:
        query: Texto de búsqueda.
        source: ``apple`` (iTunes, sin API key) o ``spotify`` (credenciales).
        limit: Número máximo de resultados.
        db: Base de datos del catálogo. Si es ``None``, se crea una
            temporal en memoria (solo para probar/validar).
        spotify_client: Cliente de Spotify (opcional).

    Returns:
        Resumen: ``added`` (nuevas), ``skipped`` (ya existentes) y ``total``.
    """
    source = _coerce_source(source)
    if db is None:
        # SQLite en memoria no funciona con conexiones por operación
        # (cada _connect() crearía una DB nueva): usamos un fichero temporal.
        import tempfile

        temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_path = Path(temp_file.name)
        temp_file.close()
        database = MusicDatabase(temp_path)
        own_db = True
    else:
        database = db
        own_db = False
    try:
        hits = await search(source, query, limit, spotify_client=spotify_client)
        added = skipped = 0
        for hit in hits:
            if database.get_by_external_id(hit.source, hit.external_id):
                skipped += 1
                continue
            track = to_track(hit)
            track.id = database.new_id()
            database.add_track(track)
            added += 1
        logger.info(
            f"import_cloud({source.value}, «{query}»): "
            f"+{added} nuevas, {skipped} ya existentes"
        )
        return {"added": added, "skipped": skipped, "total": len(hits)}
    finally:
        if own_db:
            database.close()
            temp_path.unlink(missing_ok=True)
