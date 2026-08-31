"""Autenticación OAuth 2.0 con Google para la subida a YouTube.

Gestiona el flujo OAuth 2.0 (installed app) contra Google: genera la URL de
autorización, intercambia el código por tokens y refresca el access token
cuando caduca. Las credenciales se guardan en ``~/.youber/credentials/``.

Requisito previo: crear un OAuth Client ID en Google Cloud Console
(https://console.cloud.google.com/apis/credentials) con el scope de YouTube
y exportar ``GOOGLE_CLIENT_ID`` y ``GOOGLE_CLIENT_SECRET``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from loguru import logger

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/youtube"

DEFAULT_CREDENTIALS_DIR = Path.home() / ".youber" / "credentials"
TOKEN_FILENAME = "youtube_token.json"


class YouTubeAuth:
    """Cliente OAuth 2.0 para YouTube (installed app)."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        credentials_dir: str | Path | None = None,
        redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob",
    ) -> None:
        """Crea el cliente de autenticación.

        Args:
            client_id: OAuth Client ID (por defecto: ``GOOGLE_CLIENT_ID``).
            client_secret: OAuth Client Secret (por defecto:
                ``GOOGLE_CLIENT_SECRET``).
            credentials_dir: Directorio donde guardar el token.
            redirect_uri: URI de redirección (por defecto: out-of-band).
        """
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri
        self.credentials_dir = Path(credentials_dir or DEFAULT_CREDENTIALS_DIR)
        self.token_file = self.credentials_dir / TOKEN_FILENAME

    def _require_client(self) -> None:
        """Lanza un error claro si faltan las credenciales de la app."""
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Faltan GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET. Crea un OAuth "
                "Client ID en Google Cloud Console y exporta ambas variables."
            )

    # -- Flujo de autorización ----------------------------------------------

    def get_authorization_url(self, state: str | None = None) -> str:
        """Genera la URL que el usuario debe abrir en el navegador."""
        self._require_client()
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Intercambia el código de autorización por tokens y los guarda.

        Args:
            code: Código que Google muestra tras autorizar.

        Returns:
            Los tokens guardados (``access_token``, ``refresh_token``,
            ``expires_at``).
        """
        self._require_client()
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TOKEN_URL, data=data)
            response.raise_for_status()
            tokens = self._save_tokens(response.json())
        logger.info("Autenticación completada; token guardado")
        return tokens

    # -- Persistencia -------------------------------------------------------

    def has_token(self) -> bool:
        """Indica si existe un token guardado."""
        return self.token_file.exists()

    def load_tokens(self) -> dict:
        """Carga los tokens guardados (lanza ``ValueError`` si no existen)."""
        if not self.token_file.exists():
            raise ValueError(
                "No hay token guardado. Ejecuta primero: youber-upload auth"
            )
        return json.loads(self.token_file.read_text(encoding="utf-8"))

    def _save_tokens(self, payload: dict) -> dict:
        """Guarda los tokens (y la expiración) en el fichero de credenciales."""
        self.credentials_dir.mkdir(parents=True, exist_ok=True)
        tokens = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token"),
            "expires_at": time.time() + int(payload.get("expires_in", 3600)),
        }
        self.token_file.write_text(
            json.dumps(tokens, indent=2), encoding="utf-8"
        )
        return tokens

    # -- Access token -------------------------------------------------------

    async def get_access_token(self) -> str:
        """Devuelve un access token válido, refrescándolo si ha caducado.

        Raises:
            ValueError: si no hay token o no hay refresh token disponible.
        """
        tokens = self.load_tokens()
        if tokens.get("expires_at", 0) > time.time() + 60:
            return tokens["access_token"]

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise ValueError(
                "El token ha caducado y no hay refresh_token. "
                "Ejecuta de nuevo: youber-upload auth"
            )

        self._require_client()
        data = {
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TOKEN_URL, data=data)
            response.raise_for_status()
            payload = response.json()
            payload.setdefault("refresh_token", refresh_token)
            tokens = self._save_tokens(payload)
        logger.debug("Access token refrescado")
        return tokens["access_token"]
