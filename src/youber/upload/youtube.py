"""Subida de vídeos a YouTube (YouTube Data API v3, uso educativo).

Usa la **subida resumable** oficial: primero se inicializa con los metadatos
(POST) y se recibe una URL de subida, y después se envían los bytes del
vídeo (PUT). Solo se publica **contenido propio** o con licencia.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger

from youber.upload.auth import YouTubeAuth
from youber.upload.metadata import VideoMetadata

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API_URL = "https://www.googleapis.com/youtube/v3/videos"
CONTENT_TYPE = "application/octet-stream"


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
