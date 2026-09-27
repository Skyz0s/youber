"""Subida de vídeos a YouTube (YouTube Data API v3, uso educativo).

Usa la **subida resumable** oficial: primero se inicializa con los metadatos
(POST) y se recibe una URL de subida, y después se envían los bytes del
vídeo (PUT). Solo se publica **contenido propio** o con licencia.

Además del vídeo, el cliente sube la **miniatura** (``thumbnails.set``) y las
**pistas de subtítulos** (``captions.insert``) del flujo de letras.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger

from youber.upload.auth import YouTubeAuth
from youber.upload.captions import (
    CAPTIONS_API_URL,
    CAPTIONS_UPLOAD_URL,
    DEFAULT_CAPTION_MIME,
    DEFAULT_LANGUAGE,
    build_multipart_body,
    caption_snippet,
)
from youber.upload.metadata import VideoMetadata

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API_URL = "https://www.googleapis.com/youtube/v3/videos"
THUMBNAILS_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CONTENT_TYPE = "application/octet-stream"

#: Extensiones → MIME de imagen de miniatura.
THUMBNAIL_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

_SCOPE_HINT = (
    "La API ha rechazado el token por permisos: la miniatura y las pistas de "
    "subtítulos necesitan el scope 'youtube.force-ssl'. Rehaz la autorización: "
    "youber-upload auth"
)


class YouTubeUploader:
    """Cliente de subida a YouTube (requiere OAuth 2.0 autenticado)."""

    def __init__(self, auth: YouTubeAuth, timeout: float = 120.0) -> None:
        """Crea el uploader.

        Args:
            auth: Autenticación OAuth 2.0 ya autorizada.
            timeout: Timeout HTTP en segundos (la subida de vídeos es lenta).
        """
        self.auth = auth
        self.timeout = timeout

    async def _headers(self) -> dict[str, str]:
        token = await self.auth.get_access_token()
        return {"Authorization": f"Bearer {token}"}

    async def upload_video(
        self,
        video_path: str | Path,
        metadata: VideoMetadata,
    ) -> dict:
        """Sube un vídeo a YouTube (subida resumable).

        Args:
            video_path: Ruta al fichero de vídeo (MP4/MKV).
            metadata: Metadatos (título, descripción, tags, privacidad...).

        Returns:
            El recurso del vídeo publicado, con su ``id``.

        Raises:
            FileNotFoundError: si el vídeo no existe.
            RuntimeError: si la API no devuelve URL de subida o falla.
        """
        path = Path(video_path)
        if not path.is_file():
            raise FileNotFoundError(f"Vídeo no encontrado: {path}")

        headers = {
            **await self._headers(),
            "Content-Type": "application/json; charset=UTF-8",
        }
        body = {
            "snippet": metadata.to_snippet(),
            "status": metadata.to_status(),
        }
        params = {"uploadType": "resumable", "part": "snippet,status"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"Iniciando subida de {path.name}…")
            init = await client.post(
                UPLOAD_URL, params=params, headers=headers, json=body
            )
            init.raise_for_status()
            location = init.headers.get("Location")
            if not location:
                raise RuntimeError("La API no devolvió una URL de subida")

            data = path.read_bytes()
            logger.debug(f"Enviando {len(data)} bytes a la URL de subida")
            upload = await client.put(
                location,
                headers={"Content-Type": CONTENT_TYPE},
                content=data,
            )
            upload.raise_for_status()
            resource = upload.json()

        video_id = resource.get("id")
        logger.info(f"Vídeo subido: {video_id} → {self.get_video_url(video_id)}")
        return resource

    async def set_thumbnail(
        self,
        video_id: str,
        image_path: str | Path,
    ) -> dict:
        """Sube y fija la miniatura de un vídeo (``thumbnails.set``).

        Args:
            video_id: Id del vídeo al que se asocia la miniatura.
            image_path: JPEG/PNG de la miniatura (máx. 2 MB para el vídeo ya
                publicado; la API acepta hasta 50 MB).

        Returns:
            El recurso devuelto por la API (``items`` con las miniaturas).

        Raises:
            FileNotFoundError: si la imagen no existe.
            RuntimeError: si la API rechaza la subida.
        """
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Miniatura no encontrada: {path}")

        mime = THUMBNAIL_MIME.get(path.suffix.lower(), "application/octet-stream")
        headers = {**await self._headers(), "Content-Type": mime}
        params = {"videoId": video_id, "uploadType": "media"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                THUMBNAILS_URL,
                params=params,
                headers=headers,
                content=path.read_bytes(),
            )
            self._raise(response)
            resource = response.json()
        logger.info(f"Miniatura fijada para el vídeo {video_id}")
        return resource

    async def upload_caption(
        self,
        video_id: str,
        caption_path: str | Path,
        *,
        language: str = DEFAULT_LANGUAGE,
        name: str | None = None,
        is_draft: bool = False,
        mime: str = DEFAULT_CAPTION_MIME,
    ) -> dict:
        """Sube una pista de subtítulos (``captions.insert``).

        La pista se sube en ``multipart/related``: el ``snippet`` en JSON y el
        fichero (.srt) como parte binaria. Requiere el scope
        ``youtube.force-ssl``.

        Args:
            video_id: Id del vídeo al que pertenece la pista.
            caption_path: Fichero de subtítulos (.srt).
            language: Código ISO 639-1 del idioma (por defecto ``es``).
            name: Nombre visible de la pista.
            is_draft: Subir como borrador (no visible para el público).
            mime: MIME de la parte binaria.

        Returns:
            La pista creada (``id`` y ``snippet``).

        Raises:
            FileNotFoundError: si el fichero de subtítulos no existe.
            RuntimeError: si la API rechaza la subida.
        """
        path = Path(caption_path)
        if not path.is_file():
            raise FileNotFoundError(f"Subtítulos no encontrados: {path}")

        snippet = caption_snippet(
            video_id, language=language, name=name, is_draft=is_draft
        )
        body, content_type = build_multipart_body(
            snippet, path.read_bytes(), mime=mime
        )
        headers = {**await self._headers(), "Content-Type": content_type}
        params = {"uploadType": "multipart", "part": "snippet"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                CAPTIONS_UPLOAD_URL, params=params, headers=headers, content=body
            )
            self._raise(response)
            resource = response.json()
        logger.info(
            f"Pista de subtítulos subida ({language}) para el vídeo {video_id}"
        )
        return resource

    async def list_captions(self, video_id: str) -> list[dict]:
        """Lista las pistas de subtítulos de un vídeo (``captions.list``).

        Args:
            video_id: Id del vídeo.

        Returns:
            Las pistas (``items`` de la respuesta).
        """
        headers = await self._headers()
        params = {"part": "snippet", "videoId": video_id}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(CAPTIONS_API_URL, params=params, headers=headers)
            self._raise(response)
            return list(response.json().get("items", []))

    async def delete_caption(self, caption_id: str) -> None:
        """Borra una pista de subtítulos (``captions.delete``)."""
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.delete(
                CAPTIONS_API_URL, params={"id": caption_id}, headers=headers
            )
            self._raise(response)
        logger.info(f"Pista de subtítulos borrada: {caption_id}")

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        """``raise_for_status`` con pista clara si falta el scope de la API."""
        if response.status_code in (401, 403):
            raise RuntimeError(f"{_SCOPE_HINT} (HTTP {response.status_code})")
        response.raise_for_status()

    async def check_status(self, video_id: str) -> dict:
        """Consulta el estado de un vídeo subido.

        Args:
            video_id: Id del vídeo en YouTube.

        Returns:
            El primer ``item`` de la respuesta (con ``status`` y ``snippet``).

        Raises:
            ValueError: si el vídeo no existe.
        """
        headers = await self._headers()
        params = {"part": "status,snippet", "id": video_id}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(API_URL, params=params, headers=headers)
            response.raise_for_status()
            items = response.json().get("items", [])
        if not items:
            raise ValueError(f"Vídeo no encontrado: {video_id}")
        return items[0]

    @staticmethod
    def get_video_url(video_id: str) -> str:
        """Devuelve la URL pública de un vídeo de YouTube."""
        return f"https://www.youtube.com/watch?v={video_id}"
