"""Cliente de YouTube Music (catálogo en la nube) para BARF.

Usa ``ytmusicapi`` para buscar canciones, obtener su información y añadirlas
a la biblioteca (playlist "Me gusta") del usuario. **No descarga archivos**:
solo consulta metadatos públicos y opera sobre la propia cuenta del usuario,
lo que permite usar música de forma legal y ética en los vídeos editados.

Autenticación: se puede pasar un fichero de headers (generado con
``ytmusicapi``) o dejar que use ``~/.youber/ytmusic_headers.json`` si existe.
Sin autenticación, la búsqueda funciona en modo anónimo.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ytmusicapi import YTMusic

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
