"""Cliente de YouTube Music (catálogo en la nube) para BARF.

Usa ``ytmusicapi`` para buscar canciones, obtener su información, añadirlas
a la biblioteca (playlist "Me gusta") e importar la biblioteca completa
del usuario (Me gusta, guardadas, playlists y subidas). **No descarga
archivos**: solo consulta metadatos públicos y opera sobre la propia
cuenta del usuario, lo que permite usar música de forma legal y ética en
los vídeos editados.

Autenticación: se puede pasar un fichero de headers (generado con
``ytmusicapi``) o dejar que use ``~/.youber/ytmusic_headers.json`` si
existe. Sin autenticación, la búsqueda funciona en modo anónimo, pero la
biblioteca personal requiere headers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger
from ytmusicapi import YTMusic

from youber.music.database import MusicDatabase
from youber.music.models import Track, TrackSource

DEFAULT_HEADERS_FILE = Path.home() / ".youber" / "ytmusic_headers.json"


class YouTubeMusicClient:
    """Cliente asíncrono de YouTube Music (envuelve ``ytmusicapi``)."""

    def __init__(self, headers_file: str | None = None) -> None:
        """Inicializa el cliente de YouTube Music.

        Args:
            headers_file: Ruta al archivo de headers de autenticación. Si es
                ``None``, intenta usar ``~/.youber/ytmusic_headers.json`` y,
                si no existe, opera en modo anónimo.
        """
        resolved = headers_file
        if resolved is None and DEFAULT_HEADERS_FILE.exists():
            resolved = str(DEFAULT_HEADERS_FILE)
        self.ytmusic = YTMusic(resolved) if resolved else YTMusic()
        self.authenticated = resolved is not None

    # -- Biblioteca personal (requiere autenticación) ----------------------

    async def library_songs(self, limit: int = 500) -> list[dict[str, Any]]:
        """Canciones guardadas en la biblioteca del usuario."""
        return await asyncio.to_thread(self.ytmusic.get_library_songs, limit)

    async def liked_songs(self, limit: int = 500) -> list[dict[str, Any]]:
        """Canciones marcadas como «Me gusta» (playlist LM).

        La API devuelve un dict con la lista en ``tracks`` (o directamente
        una lista según la versión); normalizamos a lista.
        """
        data = await asyncio.to_thread(self.ytmusic.get_liked_songs, limit)
        if isinstance(data, dict):
            return list(data.get("tracks", []))
        return list(data)

    async def upload_songs(self, limit: int = 500) -> list[dict[str, Any]]:
        """Canciones SUBIDAS por el usuario (sección «Subidas» de YT Music).

        La biblioteca personal de muchos usuarios vive aquí (música propia
        subida a la nube), así que es clave para importar el catálogo
        completo. Requiere autenticación.
        """
        return await asyncio.to_thread(self.ytmusic.get_library_upload_songs, limit)

    # -- Catálogo público de artistas/canales ------------------------------

    async def search_artist(self, query: str) -> dict[str, Any] | None:
        """Busca un artista por nombre/handle y devuelve su canal.

        Args:
            query: Nombre o handle del artista (p. ej. ``"Knight Princess"``
                o ``"@KnightPrincessReal"``), o un channelId (``UC...``).

        Returns:
            Dict con ``channel_id`` y ``name``, o ``None`` si no hay
            resultados.
        """
        # Si es un channelId directo, no hace falta buscar.
        stripped = query.strip()
        if stripped.startswith("UC") and len(stripped) == 24:
            return {"channel_id": stripped, "name": stripped}
        # ytmusicapi no busca con la @ del handle: probamos ambas variantes.
        candidates = [stripped, stripped.lstrip("@")]
        for candidate in candidates:
            if not candidate:
                continue
            results = await asyncio.to_thread(self.ytmusic.search, candidate, "artists")
            if not results:
                continue
            artist = results[0]
            return {
                "channel_id": artist.get("browseId", ""),
                "name": artist.get("artist", "") or artist.get("title", ""),
            }
        return None

    async def artist_catalog(self, channel_id: str) -> dict[str, Any]:
        """Catálogo público de un artista: álbumes, singles y canciones."""
        return await asyncio.to_thread(self.ytmusic.get_artist, channel_id)

    async def album_tracks(self, browse_id: str) -> list[dict[str, Any]]:
        """Canciones de un álbum/single (metadatos públicos)."""
        album = await asyncio.to_thread(self.ytmusic.get_album, browse_id)
        return album.get("tracks", [])

    async def library_playlists(self, limit: int = 100) -> list[dict[str, Any]]:
        """Playlists del usuario (propias y guardadas)."""
        return await asyncio.to_thread(self.ytmusic.get_library_playlists, limit)

    async def playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        """Canciones de una playlist concreta."""
        playlist = await asyncio.to_thread(self.ytmusic.get_playlist, playlist_id)
        return playlist.get("tracks", [])

    async def search_song(self, title: str, artist: str) -> dict[str, Any] | None:
        """Busca una canción en YouTube Music por título y artista.

        Args:
            title: Título de la canción.
            artist: Nombre del artista.

        Returns:
            Dict con ``id``, ``title``, ``artist``, ``duration``, ``album``
            y ``thumbnail``, o ``None`` si no hay resultados.
        """
        query = f"{title} {artist}".strip()
        results = await asyncio.to_thread(
            self.ytmusic.search, query, "songs"
        )
        if not results:
            return None

        # Tomar el primer resultado.
        song = results[0]
        return {
            "id": song.get("videoId", ""),
            "title": song.get("title", title),
            "artist": (song.get("artists") or [{}])[0].get("name", "Desconocido"),
            "duration": song.get("duration", 0),
            "album": (song.get("album") or {}).get("name", ""),
            "thumbnail": (song.get("thumbnails") or [{}])[-1].get("url", ""),
        }

    async def add_to_library(self, song_id: str) -> bool:
        """Añade una canción a la biblioteca de YouTube Music.

        Añade la canción a la playlist "Me gusta" (``LM``) de la cuenta
        autenticada.

        Args:
            song_id: Id del vídeo/canción en YouTube Music.

        Returns:
            ``True`` si se añadió correctamente.
        """
        try:
            await asyncio.to_thread(
                self.ytmusic.add_playlist_items, "LM", [song_id]
            )
            return True
        except Exception:
            return False

    async def get_song_info(self, song_id: str) -> dict[str, Any]:
        """Obtiene información detallada de una canción por su ID.

        Args:
            song_id: Id del vídeo/canción en YouTube Music.

        Returns:
            Dict con ``id``, ``title``, ``artist``, ``duration`` y ``album``.
        """
        song = await asyncio.to_thread(self.ytmusic.get_song, song_id)
        artist = song.get("artist") or {}
        return {
            "id": song_id,
            "title": song.get("title", ""),
            "artist": artist.get("name", "Desconocido"),
            "duration": song.get("duration", 0),
            "album": (song.get("album") or {}).get("name", ""),
        }


# ---------------------------------------------------------------------------
# Importación de la biblioteca personal
# ---------------------------------------------------------------------------


def _parse_duration(value: Any) -> float | None:
    """Convierte la duración de ytmusicapi (int segundos o ``"3:45"``) a segundos."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    parts = text.split(":")
    try:
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
        return seconds
    except ValueError:
        return None


def _track_from_ytmusic(item: dict[str, Any]) -> Track:
    """Convierte un item de la biblioteca de ytmusicapi en una pista del catálogo."""
    video_id = str(item.get("videoId", "")).strip()
    artists = item.get("artists") or []
    album = item.get("album") or {}
    return Track(
        id="",
        file_path=Path(f"cloud:youtube:{video_id}"),
        title=item.get("title", "") or "Sin título",
        artist=(artists[0].get("name") if artists else None),
        duration=_parse_duration(item.get("duration")) or 0.0,
        genre=None,
        source=TrackSource.YOUTUBE,
        external_id=video_id,
        album=album.get("name") if isinstance(album, dict) else (album or None),
        file_hash=f"cloud:youtube:{video_id}",
    )


async def import_ytmusic_library(
    client: YouTubeMusicClient | None = None,
    db: MusicDatabase | None = None,
    include_playlists: bool = True,
) -> dict[str, Any]:
    """Importa la biblioteca personal de YouTube Music al catálogo.

    Recoge «Me gusta», canciones guardadas y (opcionalmente) playlists del
    usuario, y las añade como pistas ``source=youtube`` con su ``videoId``
    como ``external_id``. Idempotente: reimportar no duplica nada.

    Args:
        client: Cliente autenticado (si es ``None``, uno nuevo).
        db: Base de datos del catálogo (si es ``None``, temporal).
        include_playlists: Si ``True``, también importa las playlists.

    Returns:
        Resumen: ``added``, ``skipped``, ``total`` y ``sources``.

    Raises:
        RuntimeError: si el cliente no está autenticado (sin headers).
    """
    client = client or YouTubeMusicClient()
    if not client.authenticated:
        raise RuntimeError(
            "YouTube Music sin autenticar: crea ~/.youber/ytmusic_headers.json "
            "(instrucciones en docs/MUSIC.md o con ytmusicapi.setup())"
        )

    if db is None:
        import tempfile

        temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_path = Path(temp_file.name)
        temp_file.close()
        database = MusicDatabase(temp_path)
        own_db = True
    else:
        database = db
        own_db = False

    async def _import(items: list[dict[str, Any]]) -> tuple[int, int]:
        added = skipped = 0
        for item in items:
            video_id = str(item.get("videoId", "")).strip()
            if not video_id:
                continue
            if database.get_by_external_id(TrackSource.YOUTUBE, video_id):
                skipped += 1
                continue
            track = _track_from_ytmusic(item)
            track.id = database.new_id()
            database.add_track(track)
            added += 1
        return added, skipped

    try:
        added = skipped = 0
        sources: list[str] = []
        errors: list[str] = []

        async def _collect(label: str, coro) -> list[dict[str, Any]]:
            """Recolecta una fuente; si falla, lo registra y sigue con las demás."""
            try:
                return await coro
            except Exception as exc:
                logger.warning(f"Fuente '{label}' de YouTube Music no disponible: {exc}")
                errors.append(label)
                return []

        for label, coro in (
            ("liked", client.liked_songs()),
            ("library", client.library_songs()),
            ("uploads", client.upload_songs()),
        ):
            items = await _collect(label, coro)
            if not items:
                errors.append(label)
                continue
            add, skip = await _import(items)
            added += add
            skipped += skip
            sources.append(label)

        if include_playlists:
            playlists = await _collect("playlists", client.library_playlists())
            if not playlists:
                errors.append("playlists")
            else:
                for playlist in playlists:
                    playlist_id = str(playlist.get("playlistId", "")).strip()
                    if not playlist_id:
                        continue
                    items = await _collect(
                        f"playlist:{playlist_id}", client.playlist_tracks(playlist_id)
                    )
                    add, skip = await _import(items)
                    added += add
                    skipped += skip
                sources.append("playlists")

        if not sources and errors:
            raise RuntimeError(
                "No se pudo leer ninguna fuente de YouTube Music "
                f"({', '.join(errors)}). La sesión puede haber caducado: "
                "regenera ~/.youber/ytmusic_headers.json "
                "(python examples/ytmusic_headers_from_chrome.py) y reintenta."
            )

        logger.info(
            f"import_ytmusic_library: +{added} nuevas, {skipped} ya existentes "
            f"(fuentes: {', '.join(sources)})"
        )
        return {"added": added, "skipped": skipped, "total": added + skipped, "sources": sources}
    finally:
        if own_db:
            database.close()
            temp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Catálogo público de un artista/canal
# ---------------------------------------------------------------------------


def _artist_section(catalog: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Extrae los resultados de una sección del catálogo de artista.

    ``get_artist`` devuelve secciones (``songs``, ``albums``, ``singles``…)
    que pueden ser un dict con ``results`` o una lista directa según la
    versión; normalizamos a lista.
    """
    section = catalog.get(key)
    if isinstance(section, dict):
        return section.get("results", []) or []
    return section or []


async def import_channel(
    handle: str,
    db: MusicDatabase | None = None,
    client: YouTubeMusicClient | None = None,
    include_albums: bool = True,
    include_singles: bool = True,
) -> dict[str, Any]:
    """Importa el catálogo público de un artista/canal al catálogo local.

    Resuelve el handle (p. ej. ``"@KnightPrincessReal"``) al canal del
    artista, lee sus álbumes, singles y canciones destacadas (metadatos
    públicos vía ytmusicapi, **sin descargar audio**) y añade todas las
    pistas como ``source=youtube`` con su ``videoId``. Idempotente: no
    duplica canciones ya importadas.

    Args:
        handle: Nombre o handle del artista (p. ej. ``"Knight Princess"``
            o ``"@KnightPrincessReal"``).
        db: Base de datos del catálogo (si es ``None``, temporal).
        client: Cliente de YouTube Music (por defecto, uno nuevo).
        include_albums: Importar las canciones de los álbumes.
        include_singles: Importar las canciones de los singles.

    Returns:
        Resumen: ``artist``, ``added``, ``skipped``, ``total`` y
        ``sources`` (``songs``, ``albums``, ``singles``).

    Raises:
        ValueError: si no se encuentra el artista/canal.
    """
    client = client or YouTubeMusicClient()
    artist = await client.search_artist(handle)
    if artist is None or not artist.get("channel_id"):
        raise ValueError(f"No se encontró el artista/canal: {handle!r}")

    catalog = await client.artist_catalog(str(artist["channel_id"]))

    if db is None:
        import tempfile

        temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_path = Path(temp_file.name)
        temp_file.close()
        database = MusicDatabase(temp_path)
        own_db = True
    else:
        database = db
        own_db = False

    async def _import(items: list[dict[str, Any]]) -> tuple[int, int]:
        added = skipped = 0
        for item in items:
            video_id = str(item.get("videoId", "")).strip()
            if not video_id:
                continue
            if database.get_by_external_id(TrackSource.YOUTUBE, video_id):
                skipped += 1
                continue
            track = _track_from_ytmusic(item)
            track.id = database.new_id()
            database.add_track(track)
            added += 1
        return added, skipped

    try:
        added = skipped = 0
        sources: list[str] = []

        # Canciones destacadas del artista (con videoId directo).
        songs = _artist_section(catalog, "songs")
        add, skip = await _import(songs)
        added += add
        skipped += skip
        if songs:
            sources.append("songs")

        # Álbumes y singles: cada resultado tiene browseId -> get_album.
        for label, include in (("albums", include_albums), ("singles", include_singles)):
            if not include:
                continue
            for release in _artist_section(catalog, label):
                browse_id = str(release.get("browseId", "")).strip()
                if not browse_id:
                    continue
                try:
                    items = await client.album_tracks(browse_id)
                except Exception as exc:
                    logger.warning(f"No se pudo leer {label[:-1]} {release.get('title', '?')}: {exc}")
                    continue
                add, skip = await _import(items)
                added += add
                skipped += skip
            if _artist_section(catalog, label):
                sources.append(label)

        logger.info(
            f"import_channel({artist['name']}): +{added} nuevas, {skipped} ya existentes "
            f"(fuentes: {', '.join(sources)})"
        )
        return {
            "artist": artist["name"],
            "added": added,
            "skipped": skipped,
            "total": added + skipped,
            "sources": sources,
        }
    finally:
        if own_db:
            database.close()
            temp_path.unlink(missing_ok=True)

