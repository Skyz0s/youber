"""Subida a TikTok con la **Content Posting API** oficial (uso educativo).

Dos modos de publicación, ambos soportados por la API:

- **Bandeja de entrada** (``/post/publish/inbox/video/init/``): el vídeo llega
  como borrador al perfil del usuario y se termina de publicar en la app. Es el
  único modo disponible para apps **no auditadas** por TikTok.
- **Post directo** (``/post/publish/video/init/``): publica sin intervención
  humana. Requiere la configuración *Direct Post* y el scope
  ``video.publish`` aprobados, y que la app pase la auditoría (si no, todo el
  contenido sale restringido a ``SELF_ONLY``).

Flujo de subida (idéntico en ambos modos):

1. ``creator_info/query`` para conocer límites y opciones de privacidad.
2. ``init`` → devuelve ``publish_id`` + ``upload_url``.
3. ``PUT`` del fichero en chunks secuenciales (5-64 MB, el último absorbe el
   resto) con la cabecera ``Content-Range``.
4. ``status/fetch`` hasta ``PUBLISH_COMPLETE`` (o ``SEND_TO_USER_INBOX``).

Documentación oficial: https://developers.tiktok.com/doc/content-posting-api-get-started
"""

from __future__ import annotations

import json
import math
import os
import secrets
import time
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from youber.upload.auth import DEFAULT_CREDENTIALS_DIR, account_dir

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API_BASE = "https://open.tiktokapis.com/v2"
CREATOR_INFO_URL = f"{API_BASE}/post/publish/creator_info/query/"
VIDEO_INIT_URL = f"{API_BASE}/post/publish/video/init/"
INBOX_INIT_URL = f"{API_BASE}/post/publish/inbox/video/init/"
STATUS_URL = f"{API_BASE}/post/publish/status/fetch/"
CANCEL_URL = f"{API_BASE}/post/publish/cancel/"

#: Scopes necesarios: leer el perfil, subir y (opcionalmente) publicar.
DEFAULT_SCOPES = "user.info.basic,video.upload,video.publish"

TOKEN_FILENAME = "tiktok_token.json"
CLIENT_FILENAME = "tiktok_client.json"
ACCOUNT_ENV = "YOUBER_ACCOUNT"

#: Restricciones de chunk documentadas por TikTok.
MIN_CHUNK_SIZE = 5 * 1024 * 1024
MAX_CHUNK_SIZE = 64 * 1024 * 1024
MAX_LAST_CHUNK_SIZE = 128 * 1024 * 1024
MAX_CHUNKS = 1000
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024

#: MIME por extensión aceptada por la Content Posting API.
VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}

#: Estados finales de ``status/fetch``.
FINAL_STATES = {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"}


class TikTokError(RuntimeError):
    """Error genérico del cliente de TikTok."""


class TikTokAPIError(TikTokError):
    """La API devolvió un ``error.code`` distinto de ``ok``."""

    def __init__(self, code: str, message: str = "", log_id: str = "") -> None:
        """Guarda el código de error, el mensaje y el ``log_id`` de la petición."""
        detail = f"{code}: {message}" if message else code
        if log_id:
            detail = f"{detail} (log_id={log_id})"
        super().__init__(detail)
        self.code = code
        self.message = message
        self.log_id = log_id


class PrivacyLevel(StrEnum):
    """Niveles de privacidad que acepta ``post_info.privacy_level``."""

    PUBLIC = "PUBLIC_TO_EVERYONE"
    FRIENDS = "MUTUAL_FOLLOW_FRIENDS"
    SELF_ONLY = "SELF_ONLY"


class TikTokPostInfo(BaseModel):
    """``post_info`` del post directo.

    Solo se usa en el modo directo; en la bandeja de entrada los metadatos se
    rellenan en la app.
    """

    title: str = Field(default="", max_length=2200)
    privacy_level: PrivacyLevel = PrivacyLevel.SELF_ONLY
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False
    video_cover_timestamp_ms: int | None = Field(default=None, ge=0)

    def to_payload(self) -> dict[str, Any]:
        """Serializa el modelo al JSON que espera la API."""
        payload: dict[str, Any] = {
            "title": self.title,
            "privacy_level": self.privacy_level.value,
            "disable_comment": self.disable_comment,
            "disable_duet": self.disable_duet,
            "disable_stitch": self.disable_stitch,
        }
        if self.video_cover_timestamp_ms is not None:
            payload["video_cover_timestamp_ms"] = self.video_cover_timestamp_ms
        return payload


# ---------------------------------------------------------------------------
# Planificación de chunks (función pura, sin red)
# ---------------------------------------------------------------------------


def plan_chunks(size: int, chunk_size: int | None = None) -> tuple[int, int, list[tuple[int, int]]]:
    """Calcula los rangos de bytes de una subida por chunks.

    Reglas de TikTok: cada chunk mide entre 5 MB y 64 MB (el último puede ser
    mayor, hasta 128 MB, para absorber el resto), mínimo 1 y máximo 1000
    chunks, y los ficheros de menos de 5 MB se suben enteros.

    Args:
        size: Tamaño total del fichero en bytes.
        chunk_size: Tamaño deseado de chunk (se ajusta a los límites).

    Returns:
        ``(chunk_size, total_chunk_count, [(first_byte, last_byte), ...])``.

    Raises:
        ValueError: si el tamaño no es válido o no caben los chunks.
    """
    if size <= 0:
        raise ValueError("El fichero está vacío")
    if size < MIN_CHUNK_SIZE:
        return size, 1, [(0, size - 1)]

    desired = chunk_size or DEFAULT_CHUNK_SIZE
    # El chunk debe permitir no pasar de MAX_CHUNKS y respetar los límites.
    minimum_for_count = math.ceil(size / MAX_CHUNKS)
    desired = max(desired, MIN_CHUNK_SIZE, minimum_for_count)
    desired = min(desired, MAX_CHUNK_SIZE, size)

    total = max(1, size // desired)
    if total > MAX_CHUNKS:
        raise ValueError(f"Demasiados chunks ({total} > {MAX_CHUNKS}); sube chunk_size")

    ranges: list[tuple[int, int]] = []
    first = 0
    for index in range(total):
        last = first + desired - 1
        if index == total - 1 or last >= size - 1:
            last = size - 1
        ranges.append((first, last))
        first = last + 1
        if first >= size:
            break

    if not ranges:
        raise ValueError("No se pudo planificar la subida")
    last_len = ranges[-1][1] - ranges[-1][0] + 1
    if last_len > MAX_LAST_CHUNK_SIZE:
        raise ValueError(f"El último chunk ({last_len} bytes) supera el máximo")
    return desired, len(ranges), ranges


def detect_mime(path: str | Path) -> str:
    """Devuelve el MIME del vídeo según su extensión (mp4 por defecto)."""
    return VIDEO_MIME.get(Path(path).suffix.lower(), "video/mp4")


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------


def _dir_for_account() -> Path:
    """Directorio de credenciales activo (``YOUBER_ACCOUNT`` manda)."""
    account = os.getenv(ACCOUNT_ENV, "").strip()
    return account_dir(account) if account else DEFAULT_CREDENTIALS_DIR


class TikTokAuth:
    """OAuth 2.0 de TikTok (authorization code) y persistencia de tokens.

    Las credenciales de la app salen, por orden, de los argumentos, de las
    variables ``TIKTOK_CLIENT_KEY`` / ``TIKTOK_CLIENT_SECRET`` o de
    ``~/.youber/credentials/tiktok_client.json``::

        {"client_key": "...", "client_secret": "..."}

    Los tokens se guardan en ``~/.youber/credentials/tiktok_token.json`` (o en
    ``~/.youber/credentials/<cuenta>/`` si se define ``YOUBER_ACCOUNT``).
    """

    def __init__(
        self,
        client_key: str | None = None,
        client_secret: str | None = None,
        credentials_dir: str | Path | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        """Resuelve credenciales y rutas de token."""
        self.credentials_dir = Path(credentials_dir) if credentials_dir else _dir_for_account()
        self.client_key = client_key
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._load_client_file()

    # -- Configuración ------------------------------------------------------

    def _load_client_file(self) -> None:
        """Completa client_key/secret desde el entorno o el fichero de la app."""
        if not self.client_key:
            self.client_key = os.getenv("TIKTOK_CLIENT_KEY") or None
        if not self.client_secret:
            self.client_secret = os.getenv("TIKTOK_CLIENT_SECRET") or None
        if self.client_key and self.client_secret:
            return
        path = self.credentials_dir / CLIENT_FILENAME
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.client_key = self.client_key or data.get("client_key") or data.get("client_id")
        self.client_secret = self.client_secret or data.get("client_secret")

    @property
    def token_file(self) -> Path:
        """Ruta del fichero donde viven los tokens."""
        return self.credentials_dir / TOKEN_FILENAME

    def _require_client(self) -> None:
        """Comprueba que hay credenciales de app antes de llamar a la API."""
        if not self.client_key or not self.client_secret:
            raise TikTokError(
                "Faltan credenciales de la app de TikTok. Define "
                "TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET o crea "
                f"{self.credentials_dir / CLIENT_FILENAME}"
            )

    # -- OAuth --------------------------------------------------------------

    def get_authorization_url(
        self,
        redirect_uri: str | None = None,
        state: str | None = None,
        scopes: str = DEFAULT_SCOPES,
    ) -> str:
        """Construye la URL de consentimiento de TikTok.

        Args:
            redirect_uri: URI registrada en la app (obligatoria).
            state: Cadena anti-CSRF (se genera si no se pasa).
            scopes: Scopes separados por comas.
        """
        self._require_client()
        target = redirect_uri or self.redirect_uri
        if not target:
            raise TikTokError("Falta redirect_uri (debe estar registrada en la app)")
        params = {
            "client_key": self.client_key,
            "scope": scopes,
            "response_type": "code",
            "redirect_uri": target,
            "state": state or secrets.token_urlsafe(16),
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """Canjea el código por tokens y los guarda.

        Args:
            code: ``code`` devuelto en la redirección.
            redirect_uri: La misma URI usada al pedir la autorización.
        """
        self._require_client()
        data = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or self.redirect_uri or "",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TOKEN_URL, data=data)
            payload = _json_or_error(response)
        tokens = self._save_tokens(payload)
        logger.info("Autorización de TikTok completada; token guardado")
        return tokens

    # -- Persistencia -------------------------------------------------------

    def has_token(self) -> bool:
        """Indica si hay tokens guardados."""
        return self.token_file.exists()

    def load_tokens(self) -> dict:
        """Carga los tokens guardados.

        Raises:
            ValueError: si no hay token todavía.
        """
        if not self.token_file.exists():
            raise ValueError("No hay token de TikTok. Ejecuta primero: youber-tiktok auth")
        return json.loads(self.token_file.read_text(encoding="utf-8"))

    def _save_tokens(self, payload: dict) -> dict:
        """Normaliza y escribe los tokens (incluida la expiración)."""
        self.credentials_dir.mkdir(parents=True, exist_ok=True)
        tokens = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token"),
            "open_id": payload.get("open_id"),
            "scope": payload.get("scope"),
            "expires_at": time.time() + int(payload.get("expires_in", 86400)),
            "refresh_expires_at": time.time() + int(payload.get("refresh_expires_in", 0)),
        }
        self.token_file.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        return tokens

    # -- Access token -------------------------------------------------------

    async def get_access_token(self) -> str:
        """Devuelve un access token válido, refrescándolo si caduca pronto.

        Raises:
            ValueError: si no hay token o no queda refresh_token.
        """
        tokens = self.load_tokens()
        if tokens.get("expires_at", 0) > time.time() + 120:
            return str(tokens["access_token"])

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise ValueError("El token caducó y no hay refresh_token. Repite: youber-tiktok auth")

        self._require_client()
        data = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TOKEN_URL, data=data)
            payload = _json_or_error(response)
        payload.setdefault("refresh_token", refresh_token)
        payload.setdefault("open_id", tokens.get("open_id"))
        tokens = self._save_tokens(payload)
        logger.debug("Access token de TikTok refrescado")
        return str(tokens["access_token"])


# ---------------------------------------------------------------------------
# Cliente de publicación
# ---------------------------------------------------------------------------


class TikTokUploader:
    """Sube vídeos a TikTok con la Content Posting API."""

    def __init__(self, auth: TikTokAuth, timeout: float = 300.0) -> None:
        """Crea el uploader.

        Args:
            auth: Autenticación ya autorizada.
            timeout: Timeout HTTP en segundos (la subida es lenta).
        """
        self.auth = auth
        self.timeout = timeout

    async def _headers(self) -> dict[str, str]:
        token = await self.auth.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def query_creator_info(self) -> dict:
        """Consulta la información del creador (privacidad y límites)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(CREATOR_INFO_URL, headers=await self._headers(), json={})
            return _data_or_error(response)

    async def init_inbox_upload(
        self, video_path: str | Path, chunk_size: int | None = None
    ) -> dict:
        """Inicia una subida a la **bandeja de entrada** (borrador).

        Returns:
            ``{"publish_id": ..., "upload_url": ...}``.
        """
        return await self._init(INBOX_INIT_URL, video_path, None, chunk_size)

    async def init_direct_post(
        self,
        video_path: str | Path,
        post_info: TikTokPostInfo,
        chunk_size: int | None = None,
    ) -> dict:
        """Inicia un **post directo** con metadatos y privacidad.

        Returns:
            ``{"publish_id": ..., "upload_url": ...}``.
        """
        return await self._init(VIDEO_INIT_URL, video_path, post_info, chunk_size)

    async def _init(
        self,
        url: str,
        video_path: str | Path,
        post_info: TikTokPostInfo | None,
        chunk_size: int | None,
    ) -> dict:
        """Prepara y envía la petición ``init`` compartida por ambos modos."""
        path = Path(video_path)
        if not path.is_file():
            raise FileNotFoundError(f"Vídeo no encontrado: {path}")
        size = path.stat().st_size
        chosen, total, _ = plan_chunks(size, chunk_size)

        body: dict[str, Any] = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chosen,
                "total_chunk_count": total,
            }
        }
        if post_info is not None:
            body["post_info"] = post_info.to_payload()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=await self._headers(), json=body)
            data = _data_or_error(response)

        if not data.get("upload_url") or not data.get("publish_id"):
            raise TikTokError("La API no devolvió upload_url/publish_id")
        logger.info(f"Subida iniciada: publish_id={data['publish_id']} ({total} chunks)")
        return data

    async def upload_file(
        self,
        upload_url: str,
        video_path: str | Path,
        chunk_size: int | None = None,
    ) -> int:
        """Sube el fichero por chunks secuenciales con ``Content-Range``.

        Returns:
            Bytes totales enviados.

        Raises:
            TikTokError: si un chunk es rechazado (URL caducada, rango...).
        """
        path = Path(video_path)
        size = path.stat().st_size
        _, total, ranges = plan_chunks(size, chunk_size)
        mime = detect_mime(path)
        sent = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with path.open("rb") as handle:
                for index, (first, last) in enumerate(ranges, start=1):
                    handle.seek(first)
                    chunk = handle.read(last - first + 1)
                    headers = {
                        "Content-Type": mime,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {first}-{last}/{size}",
                    }
                    response = await client.put(upload_url, headers=headers, content=chunk)
                    if response.status_code not in (201, 206):
                        raise TikTokError(
                            f"Chunk {index}/{total} rechazado (HTTP {response.status_code}): "
                            f"{response.text[:200]}"
                        )
                    sent += len(chunk)
                    logger.debug(f"Chunk {index}/{total} subido ({sent}/{size} bytes)")
                    if response.status_code == 201:
                        break
        return sent

    async def get_status(self, publish_id: str) -> dict:
        """Consulta el estado de una publicación."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                STATUS_URL,
                headers=await self._headers(),
                json={"publish_id": publish_id},
            )
            return _data_or_error(response)

    async def wait_for_publish(
        self,
        publish_id: str,
        timeout: float = 600.0,
        interval: float = 3.0,
    ) -> dict:
        """Espera a que la publicación llegue a un estado final.

        Args:
            publish_id: Id devuelto por ``init``.
            timeout: Segundos máximos de espera.
            interval: Segundos entre consultas.

        Returns:
            El último ``data`` recibido (incluye ``status``).

        Raises:
            TikTokError: si el estado es ``FAILED`` o vence el tiempo.
        """
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            last = await self.get_status(publish_id)
            status = str(last.get("status", ""))
            logger.debug(f"Estado de {publish_id}: {status or 'desconocido'}")
            if status in FINAL_STATES:
                if status == "FAILED":
                    raise TikTokError(
                        f"TikTok falló al procesar: {last.get('fail_reason', 'sin motivo')}"
                    )
                return last
            await _sleep(interval)
        raise TikTokError(f"Timeout esperando la publicación {publish_id}: {last.get('status')}")

    async def publish(
        self,
        video_path: str | Path,
        post_info: TikTokPostInfo | None = None,
        *,
        direct: bool = False,
        wait: bool = True,
        chunk_size: int | None = None,
    ) -> dict:
        """Flujo completo: init → subida por chunks → estado.

        Args:
            video_path: Fichero de vídeo local.
            post_info: Metadatos (obligatorio en modo directo).
            direct: ``True`` para post directo, ``False`` para bandeja de entrada.
            wait: Si ``True``, espera al estado final.
            chunk_size: Tamaño de chunk en bytes (se ajusta a los límites).

        Returns:
            ``{"publish_id", "upload_url", "status", "uploaded_bytes"}``.
        """
        if direct and post_info is None:
            raise TikTokError("El modo directo necesita post_info (título y privacidad)")
        if direct:
            assert post_info is not None
            init = await self.init_direct_post(video_path, post_info, chunk_size)
        else:
            init = await self.init_inbox_upload(video_path, chunk_size)
        uploaded = await self.upload_file(init["upload_url"], video_path, chunk_size)
        result: dict = {
            "publish_id": init["publish_id"],
            "upload_url": init["upload_url"],
            "uploaded_bytes": uploaded,
            "status": "PROCESSING_UPLOAD",
        }
        if wait:
            status = await self.wait_for_publish(init["publish_id"])
            result["status"] = status.get("status")
            result["detail"] = status
        return result


# ---------------------------------------------------------------------------
# Utilidades HTTP
# ---------------------------------------------------------------------------


def _json_or_error(response: httpx.Response) -> dict:
    """Devuelve el JSON de la respuesta o lanza con el error de la API.

    La Content Posting API responde ``200`` con un objeto ``error`` cuyo
    ``code`` es ``ok`` cuando todo va bien, así que un ``error`` presente no
    implica fallo: hay que mirar el código. El endpoint de OAuth, en cambio,
    usa ``{"error": "invalid_grant", ...}`` con el error como cadena.
    """
    payload: dict = response.json() if response.content else {}
    error = payload.get("error")
    if isinstance(error, str):
        message = str(payload.get("error_description") or payload.get("message") or "")
        raise TikTokAPIError(error, message, str(payload.get("log_id", "")))
    if isinstance(error, dict):
        code = str(error.get("code", "ok"))
        if code != "ok":
            raise TikTokAPIError(code, str(error.get("message", "")), str(error.get("log_id", "")))
    if response.is_error:
        raise TikTokAPIError(f"http_{response.status_code}", response.text[:300])
    return payload


def _data_or_error(response: httpx.Response) -> dict:
    """Extrae ``data`` y comprueba ``error.code == ok`` de la API de contenido."""
    payload = _json_or_error(response)
    return dict(payload.get("data") or {})


async def _sleep(seconds: float) -> None:
    """Envuelve ``asyncio.sleep`` para poder parchearlo en tests."""
    import asyncio

    await asyncio.sleep(seconds)
