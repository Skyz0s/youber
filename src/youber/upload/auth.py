"""Autenticación OAuth 2.0 con Google para la subida a YouTube.

Gestiona el flujo OAuth 2.0 (installed app) contra Google: genera la URL de
autorización, intercambia el código por tokens y refresca el access token
cuando caduca. Las credenciales se guardan en ``~/.youber/credentials/``.

Requisito previo: crear un OAuth Client ID **de tipo "App de escritorio"** en
Google Cloud Console (https://console.cloud.google.com/apis/credentials) y
hacerlo llegar a la app de una de estas dos formas:

- variables de entorno ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET``
- fichero ``~/.youber/credentials/oauth_client.json``::

      {"client_id": "...", "client_secret": "..."}

  (también acepta el JSON que descarga Google, con la clave ``installed``)

El flujo out-of-band (``urn:ietf:wg:oauth:2.0:oob``) está obsoleto y Google lo
rechaza en clientes nuevos, así que por defecto se usa **loopback**: se levanta
un servidor en ``127.0.0.1`` y el navegador devuelve el código ahí.
"""

from __future__ import annotations

import http.server
import json
import os
import secrets
import time
import webbrowser
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from loguru import logger

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

#: URI de redirección para el flujo manual (obsoleto en Google, pero se sigue
#: aceptando por si se usa un cliente antiguo).
OOB_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

#: Plantilla del redirect loopback; el puerto se elige al abrir el servidor.
LOOPBACK_TEMPLATE = "http://127.0.0.1:{port}/callback"

#: Scopes de la app: ``youtube`` (subida de vídeo y miniatura) y
#: ``youtube.force-ssl`` (pistas de subtítulos: ``captions.insert`` **no**
#: acepta el scope de solo subida). Ver:
#: https://developers.google.com/youtube/v3/docs/captions/insert
SCOPES = (
    "https://www.googleapis.com/auth/youtube "
    "https://www.googleapis.com/auth/youtube.force-ssl"
)

DEFAULT_CREDENTIALS_DIR = Path.home() / ".youber" / "credentials"
TOKEN_FILENAME = "youtube_token.json"
CLIENT_FILENAME = "oauth_client.json"


class _CallbackServer(http.server.HTTPServer):
    """Servidor local que guarda el resultado de la redirección de Google."""

    result: dict[str, str] | None = None
    expected_state: str | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Atiende ``GET /callback?code=...&state=...`` del navegador."""

    def do_GET(self) -> None:  # noqa: N802 (nombre impuesto por http.server)
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        srv = cast(_CallbackServer, self.server)
        srv.result = params
        ok = "code" in params
        body = (
            "<h2>Listo</h2><p>Ya puedes cerrar esta pestaña y volver a la "
            "terminal.</p>"
            if ok
            else f"<h2>Error</h2><p>{params.get('error', 'sin código')}</p>"
        ).encode("utf-8")
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silencia el log por defecto del servidor."""


def parse_callback_path(path: str) -> dict[str, str]:
    """Extrae los parámetros de la URL de vuelta de Google.

    Args:
        path: Ruta completa con query (``/callback?code=...&state=...``).

    Returns:
        Diccionario con ``code``, ``state`` y/o ``error``.
    """
    parsed = urlparse(path)
    return {k: v[0] for k, v in parse_qs(parsed.query).items()}


class YouTubeAuth:
    """Cliente OAuth 2.0 para YouTube (installed app)."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        credentials_dir: str | Path | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        """Crea el cliente de autenticación.

        Args:
            client_id: OAuth Client ID (por defecto: ``GOOGLE_CLIENT_ID``).
            client_secret: OAuth Client Secret (por defecto:
                ``GOOGLE_CLIENT_SECRET``).
            credentials_dir: Directorio donde guardar el token.
            redirect_uri: URI de redirección. Si se omite, se usa loopback con
                el puerto que elija :meth:`authorize_local_server`; el flujo
                manual usa ``OOB_REDIRECT_URI``.
        """
        self.credentials_dir = Path(credentials_dir or DEFAULT_CREDENTIALS_DIR)
        self.token_file = self.credentials_dir / TOKEN_FILENAME
        stored_id, stored_secret = self._load_client_file()
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "") or stored_id
        self.client_secret = (
            client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "") or stored_secret
        )
        self.redirect_uri = redirect_uri

    def _load_client_file(self) -> tuple[str, str]:
        """Lee las credenciales de la app de ``oauth_client.json`` si existe."""
        path = self.credentials_dir / CLIENT_FILENAME
        if not path.exists():
            return "", ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"No se pudo leer {path}: {exc}")
            return "", ""
        if isinstance(data, dict) and "installed" in data:
            data = data["installed"]
        if not isinstance(data, dict):
            return "", ""
        return str(data.get("client_id", "")), str(data.get("client_secret", ""))

    def _require_client(self) -> None:
        """Lanza un error claro si faltan las credenciales de la app."""
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Faltan GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET. Crea un OAuth "
                "Client ID en Google Cloud Console y exporta ambas variables."
            )

    # -- Flujo de autorización ----------------------------------------------

    def get_authorization_url(
        self,
        state: str | None = None,
        redirect_uri: str | None = None,
    ) -> str:
        """Genera la URL que el usuario debe abrir en el navegador.

        Args:
            state: Valor opaco anti-CSRF que Google devolverá tal cual.
            redirect_uri: Redirección a usar (por defecto la configurada o la
                de out-of-band, para el flujo manual).
        """
        self._require_client()
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri or self.redirect_uri or OOB_REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            # select_account fuerza el selector de cuenta: si el navegador
            # tiene varias sesiones de Google, no autoriza a la que toco por
            # defecto.
            "prompt": "consent select_account",
        }
        if state:
            params["state"] = state
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """Intercambia el código de autorización por tokens y los guarda.

        Args:
            code: Código que Google devuelve tras autorizar.
            redirect_uri: La misma redirección usada en la petición de
                autorización (Google la valida).

        Returns:
            Los tokens guardados (``access_token``, ``refresh_token``,
            ``expires_at``).
        """
        self._require_client()
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri or self.redirect_uri or OOB_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TOKEN_URL, data=data)
            response.raise_for_status()
            tokens = self._save_tokens(response.json())
        logger.info("Autenticación completada; token guardado")
        return tokens

    # -- Flujo loopback -----------------------------------------------------

    def authorize_local_server(
        self,
        port: int = 0,
        timeout: float = 600.0,
        open_browser: bool = True,
    ) -> dict:
        """Autoriza abriendo el navegador y captura el código en localhost.

        Levanta un servidor en ``127.0.0.1`` (puerto libre por defecto), abre
        la URL de consentimiento y espera a que Google redirija con el código.

        Args:
            port: Puerto local (0 = que el sistema elija uno libre).
            timeout: Segundos máximos de espera.
            open_browser: Si es ``False``, solo imprime la URL.

        Returns:
            Los tokens guardados.

        Raises:
            ValueError: si Google devuelve un error o vence el tiempo.
        """
        self._require_client()
        state = secrets.token_urlsafe(16)
        srv = _CallbackServer(("127.0.0.1", port), _CallbackHandler)
        srv.expected_state = state
        srv.timeout = 1.0
        redirect = LOOPBACK_TEMPLATE.format(port=srv.server_port)
        url = self.get_authorization_url(state=state, redirect_uri=redirect)
        try:
            print(f"\nAbre esta URL y autoriza:\n\n  {url}\n")
            if open_browser:
                webbrowser.open(url)
            print(f"Esperando la confirmación en {redirect} ...")
            deadline = time.time() + timeout
            while srv.result is None and time.time() < deadline:
                srv.handle_request()
            result = srv.result
        finally:
            srv.server_close()

        if result is None:
            raise ValueError(
                f"Sin respuesta de Google en {timeout:.0f} s. Reintenta con "
                "'youber-upload auth'."
            )
        if result.get("error"):
            raise ValueError(f"Google devolvió un error: {result['error']}")
        if result.get("state") != state:
            raise ValueError("El 'state' de la respuesta no coincide; se aborta")
        code = result.get("code")
        if not code:
            raise ValueError("La respuesta de Google no trae código")

        import asyncio

        return asyncio.run(self.exchange_code(code, redirect_uri=redirect))

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
