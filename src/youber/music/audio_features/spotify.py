"""Cliente de la API de Spotify (características de audio, uso educativo).

Accede a la **API oficial de Spotify** (Web API, flujo Client Credentials)
para buscar canciones y obtener sus características de audio. Solo
metadatos públicos: **no descarga ficheros** (legal/ético, conforme a ToS).

Credenciales: variables de entorno ``SPOTIFY_CLIENT_ID`` /
``SPOTIFY_CLIENT_SECRET``, o un fichero JSON en
``~/.youber/spotify_credentials.json`` con esas dos claves. Sin
credenciales, ``available`` es ``False`` y el framework cae al estimador
local (:mod:`youber.music.audio_features.estimator`).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from youber.music.audio_features.models import AudioFeatures

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
CREDENTIALS_FILE = Path.home() / ".youber" / "spotify_credentials.json"


class SpotifyClient:
    """Cliente async de la API de Spotify (búsqueda + audio features).

    Args:
        client_id: Client ID de la app de Spotify. Por defecto se lee de
            ``SPOTIFY_CLIENT_ID`` o del fichero de credenciales.
        client_secret: Client Secret. Por defecto se lee de
            ``SPOTIFY_CLIENT_SECRET`` o del fichero de credenciales.
        timeout: Timeout HTTP en segundos.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.client_id = client_id or _env_or_file("SPOTIFY_CLIENT_ID", "client_id")
        self.client_secret = client_secret or _env_or_file(
            "SPOTIFY_CLIENT_SECRET", "client_secret"
        )
        self.timeout = timeout
        self._token: str | None = None

    @property
    def available(self) -> bool:
        """``True`` si hay credenciales para hablar con la API."""
        return bool(self.client_id and self.client_secret)

    # -- API pública --------------------------------------------------------

    async def search_track(self, title: str, artist: str | None = None) -> dict[str, Any] | None:
        """Busca una canción por título y artista (primer resultado).

        Returns:
            Dict con ``track_id``, ``title``, ``artist``, ``album``,
            ``duration_ms`` y ``popularity``; o ``None`` si no hay resultados.
        """
        results = await self.search_tracks(title, artist=artist, limit=5)
        return results[0] if results else None

    async def search_tracks(
        self,
        title: str,
        artist: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Busca canciones por título (y artista opcional) y devuelve varias.

        Returns:
            Lista de dicts con ``track_id``, ``title``, ``artist``, ``album``,
            ``duration_ms`` y ``popularity`` (vacía si no hay resultados).
        """
        if not self.available:
            raise RuntimeError("SpotifyClient sin credenciales (SPOTIFY_CLIENT_ID/SECRET)")
        query = f'track:"{title}"'
        if artist:
            query += f' artist:"{artist}"'
        params: dict[str, Any] = {
            "q": query,
            "type": "track",
            "limit": max(1, min(limit, 50)),
            "market": "ES",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            token = await self._get_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            response = await client.get(f"{API_URL}/search", params=params, headers=headers)
            response.raise_for_status()
            items = response.json().get("tracks", {}).get("items", [])
        results: list[dict[str, Any]] = []
        for track in items:
            artists = ", ".join(
                item.get("name", "") for item in track.get("artists", [])
            )
            results.append(
                {
                    "track_id": track.get("id", ""),
                    "title": track.get("name", ""),
                    "artist": artists,
                    "album": track.get("album", {}).get("name", ""),
                    "duration_ms": track.get("duration_ms", 0),
                    "popularity": track.get("popularity", 0),
                }
            )
        return results

    async def get_audio_features(self, track_id: str) -> AudioFeatures | None:
        """Obtiene las características de audio de una canción.

        Returns:
            :class:`AudioFeatures` con ``confidence=1.0`` (datos reales de
            la API), o ``None`` si la API no devuelve features.
        """
        if not self.available:
            raise RuntimeError("SpotifyClient sin credenciales (SPOTIFY_CLIENT_ID/SECRET)")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            token = await self._get_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            response = await client.get(
                f"{API_URL}/audio-features/{track_id}", headers=headers
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            if not data or not data.get("id"):
                return None
            return AudioFeatures(
                danceability=float(data.get("danceability", 0.0)),
                energy=float(data.get("energy", 0.0)),
                valence=float(data.get("valence", 0.0)),
                acousticness=float(data.get("acousticness", 0.0)),
                instrumentalness=float(data.get("instrumentalness", 0.0)),
                liveness=float(data.get("liveness", 0.0)),
                speechiness=float(data.get("speechiness", 0.0)),
                tempo=float(data.get("tempo", 0.0)),
                duration_ms=int(data.get("duration_ms", 0)),
                key=int(data.get("key", -1)),
                mode=int(data.get("mode", 1)),
                time_signature=int(data.get("time_signature", 4)),
                confidence=1.0,
            )

    # -- Internos -----------------------------------------------------------

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        """Obtiene (y cachea) un token de acceso Client Credentials."""
        if self._token:
            return self._token
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}
        response = await client.post(TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()
        self._token = response.json().get("access_token", "")
        logger.debug("Token de Spotify obtenido (Client Credentials)")
        return self._token


def _env_or_file(env_name: str, file_key: str) -> str | None:
    """Lee una credencial de una variable de entorno o del fichero JSON."""
    import os

    value = os.getenv(env_name)
    if value:
        return value
    try:
        if CREDENTIALS_FILE.exists():
            payload = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get(file_key):
                return str(payload[file_key])
    except (json.JSONDecodeError, OSError):
        pass
    return None


async def check_credentials() -> bool:
    """Comprueba si las credenciales de Spotify están configuradas."""
    return SpotifyClient().available
