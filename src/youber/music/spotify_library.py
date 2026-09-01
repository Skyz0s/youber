"""Acceso a la biblioteca personal de Spotify (canciones guardadas y playlists).

Usa el flujo **OAuth 2.0 Authorization Code** con la API oficial de
Spotify para leer la biblioteca del usuario (scope ``user-library-read``
y ``playlist-read-private``). **Solo metadatos públicos de la propia
cuenta: nunca se descarga audio** (legal/ético, conforme a ToS).

Credenciales: variables de entorno ``SPOTIFY_CLIENT_ID`` /
``SPOTIFY_CLIENT_SECRET`` o el fichero ``~/.youber/spotify_credentials.json``
(igual que :mod:`youber.music.audio_features.spotify`). El token de acceso
se guarda en ``~/.youber/spotify_token.json`` y se refresca solo.

La Redirect URI debe estar registrada en la app de Spotify y apuntar al
dashboard (por defecto ``http://127.0.0.1:8787/callback``).
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from youber.music.audio_features.spotify import (
    API_URL,
    TOKEN_URL,
    _env_or_file,
)
from youber.music.database import MusicDatabase
from youber.music.models import Track, TrackSource

TOKEN_FILE = Path.home() / ".youber" / "spotify_token.json"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8787/callback"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SCOPES = "user-library-read playlist-read-private"

_PAGE_SIZE = 50


class SpotifyOAuthError(RuntimeError):
    """Error del flujo OAuth o de la API de Spotify."""


class SpotifyLibraryClient:
    """Cliente async de la biblioteca personal de Spotify (OAuth)."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
        token_file: str | Path = TOKEN_FILE,
        timeout: float = 15.0,
    ) -> None:
        self.client_id = client_id or _env_or_file("SPOTIFY_CLIENT_ID", "client_id")
        self.client_secret = client_secret or _env_or_file(
            "SPOTIFY_CLIENT_SECRET", "client_secret"
        )
        self.redirect_uri = redirect_uri
        self.token_file = Path(token_file)
        self.timeout = timeout
        self._token: dict[str, Any] | None = self._load_token()

    # -- Propiedades --------------------------------------------------------

    @property
    def available(self) -> bool:
        """``True`` si hay credenciales de la app configuradas."""
        return bool(self.client_id and self.client_secret)

    @property
    def connected(self) -> bool:
        """``True`` si hay un token de usuario guardado (aunque expire)."""
        return self._token is not None

    # -- Flujo OAuth --------------------------------------------------------

    def authorization_url(self, state: str | None = None) -> str:
        """URL de autorización para abrir en el navegador del usuario."""
        if not self.available:
            raise SpotifyOAuthError(
                "Spotify sin credenciales: define SPOTIFY_CLIENT_ID/SECRET "
                "o crea ~/.youber/spotify_credentials.json"
            )
        state = state or secrets.token_urlsafe(16)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "state": state,
        }
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Intercambia el código de autorización por un token de acceso."""
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        data = await self._token_request(payload)
        self._token = data
        self._save_token(data)
        logger.info("Token de Spotify (autorización de usuario) obtenido")
        return data

    async def refresh(self) -> dict[str, Any]:
        """Refresca el token de acceso usando el refresh_token guardado."""
        if not self._token or not self._token.get("refresh_token"):
            raise SpotifyOAuthError("Sin refresh_token guardado: vuelve a conectar Spotify")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._token["refresh_token"],
        }
        data = await self._token_request(payload)
        # El refresh puede no devolver refresh_token nuevo; conservar el viejo.
        if "refresh_token" not in data:
            data["refresh_token"] = self._token["refresh_token"]
        self._token.update(data)
        self._save_token(self._token)
        logger.debug("Token de Spotify refrescado")
        return self._token

    async def _token_request(self, payload: dict[str, str]) -> dict[str, Any]:
        """Hace una petición al endpoint de tokens con Basic auth."""
        if not self.available:
            raise SpotifyOAuthError(
                "Spotify sin credenciales: define SPOTIFY_CLIENT_ID/SECRET "
                "o crea ~/.youber/spotify_credentials.json"
            )
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(TOKEN_URL, headers=headers, data=payload)
            response.raise_for_status()
            return response.json()

    # -- API (con token) ----------------------------------------------------

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET autenticado con la API de Spotify (refresca si expiró)."""
        token = await self._valid_access_token()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            headers = {"Authorization": f"Bearer {token}"}
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 401:
                await self.refresh()
                token = await self._valid_access_token()
                headers = {"Authorization": f"Bearer {token}"}
                response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    async def _valid_access_token(self) -> str:
        """Devuelve un access_token válido (refrescándolo si hace falta)."""
        if not self._token or not self._token.get("access_token"):
            raise SpotifyOAuthError("No hay sesión de Spotify: conecta primero")
        expires_at = self._token.get("expires_at", 0)
        if expires_at and time.time() > expires_at - 60:
            await self.refresh()
        return str(self._token["access_token"])

    async def saved_tracks(self, limit: int = _PAGE_SIZE) -> list[dict[str, Any]]:
        """Devuelve todas las canciones guardadas (Liked Songs), paginando."""
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await self._get(
                f"{API_URL}/me/tracks",
                params={"limit": limit, "offset": offset},
            )
            batch = data.get("items", [])
            for entry in batch:
                track = entry.get("track") or {}
                if track.get("id"):
                    items.append(track)
            total = int(data.get("total", 0))
            offset += len(batch)
            if not batch or offset >= total:
                break
        logger.debug(f"Spotify saved_tracks: {len(items)} canciones")
        return items

    async def playlists(self) -> list[dict[str, Any]]:
        """Devuelve las playlists del usuario (propias y privadas)."""
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await self._get(
                f"{API_URL}/me/playlists",
                params={"limit": 50, "offset": offset},
            )
            batch = data.get("items", [])
            items.extend(
                item for item in batch if item.get("id") and item.get("owner")
            )
            total = int(data.get("total", 0))
            offset += len(batch)
            if not batch or offset >= total:
                break
        logger.debug(f"Spotify playlists: {len(items)} playlists")
        return items

    async def playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        """Devuelve las canciones de una playlist (paginando)."""
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await self._get(
                f"{API_URL}/playlists/{playlist_id}/tracks",
                params={"limit": 100, "offset": offset},
            )
            batch = data.get("items", [])
            for entry in batch:
                track = entry.get("track") or {}
                if track.get("id"):
                    items.append(track)
            offset += len(batch)
            if not batch or offset >= int(data.get("total", 0)):
                break
        return items

    # -- Persistencia del token --------------------------------------------

    def _save_token(self, token: dict[str, Any]) -> None:
        token = dict(token)
        token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(
            json.dumps(token, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_token(self) -> dict[str, Any] | None:
        if not self.token_file.exists():
            return None
        try:
            return json.loads(self.token_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def logout(self) -> None:
        """Borra el token guardado (desconecta la cuenta)."""
        self._token = None
        if self.token_file.exists():
            self.token_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Conversión e importación
# ---------------------------------------------------------------------------


def track_from_api(track: dict[str, Any]) -> Track:
    """Convierte un track de la API de Spotify en una pista del catálogo."""
    track_id = str(track.get("id", ""))
    artists = ", ".join(
        item.get("name", "") for item in track.get("artists", []) or []
    )
    duration_ms = track.get("duration_ms") or 0
    return Track(
        id="",
        file_path=Path(f"cloud:spotify:{track_id}"),
        title=track.get("name", "") or "Sin título",
        artist=artists or None,
        album=(track.get("album") or {}).get("name"),
        duration=duration_ms / 1000,
        genre=None,
        source=TrackSource.SPOTIFY,
        external_id=track_id,
        file_hash=f"cloud:spotify:{track_id}",
    )


async def import_spotify_library(
    client: SpotifyLibraryClient | None = None,
    db: MusicDatabase | None = None,
    include_playlists: bool = False,
) -> dict[str, Any]:
    """Importa la biblioteca de Spotify (Liked Songs + playlists opcionales).

    Idempotente: las canciones ya importadas (mismo ``external_id`` y
    ``source``) se omiten.

    Args:
        client: Cliente OAuth (si es ``None``, uno nuevo con las
            credenciales configuradas).
        db: Base de datos del catálogo (si es ``None``, temporal).
        include_playlists: Si ``True``, también importa las canciones de
            las playlists del usuario.

    Returns:
        Resumen: ``added``, ``skipped``, ``total`` y ``sources`` (qué se
        importó: ``saved`` y/o ``playlists``).
    """
    client = client or SpotifyLibraryClient()
    if not client.connected:
        raise SpotifyOAuthError("No hay sesión de Spotify: conecta primero (youber-music spotify-auth)")

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

    def _import(track: dict[str, Any]) -> tuple[int, int]:
        track_id = str(track.get("id", ""))
        if not track_id:
            return 0, 0
        if database.get_by_external_id(TrackSource.SPOTIFY, track_id):
            return 0, 1
        item = track_from_api(track)
        item.id = database.new_id()
        database.add_track(item)
        return 1, 0

    try:
        added = skipped = 0
        sources: list[str] = []
        for track in await client.saved_tracks():
            add, skip = _import(track)
            added += add
            skipped += skip
        sources.append("saved")

        if include_playlists:
            for playlist in await client.playlists():
                for track in await client.playlist_tracks(str(playlist.get("id"))):
                    add, skip = _import(track)
                    added += add
                    skipped += skip
            sources.append("playlists")

        logger.info(
            f"import_spotify_library: +{added} nuevas, {skipped} ya existentes "
            f"(fuentes: {', '.join(sources)})"
        )
        return {
            "added": added,
            "skipped": skipped,
            "total": added + skipped,
            "sources": sources,
        }
    finally:
        if own_db:
            database.close()
            temp_path.unlink(missing_ok=True)
