"""Análisis de vídeos de YouTube (datos públicos, uso educativo).

Extrae los datos públicos de un vídeo (título, visualizaciones, likes,
comentarios, duración, fecha, descripción, hashtags...) mediante:

- **API oficial (modo ``api``)**: YouTube Data API v3 (conforme a ToS,
  requiere ``YOUTUBE_API_KEY``).
- **Página pública (modo ``html``)**: parsea el JSON ``ytInitialPlayerResponse``
  que YouTube embebe en la página del vídeo. Sin login, sin stealth, con
  rate-limit. ``/watch`` no está bloqueado en el robots.txt de YouTube.

Límites éticos: solo datos públicos, sin manipulación de métricas.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from loguru import logger

from youber.research.channel_analyzer import (
    API_BASE,
    DEFAULT_UA,
    _extract_embedded_json,
    _find_first,
    _iso8601_duration_to_hms,
    _text,
)
from youber.research.data_models import VideoData

HASHTAG_RE = re.compile(r"#([\w\u00C0-\u024F]+)")


def extract_video_id(url: str) -> str | None:
    """Extrae el ID de vídeo de una URL de YouTube (``watch?v=``, ``youtu.be``, ID plano)."""
    stripped = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", stripped):
        return stripped
    parsed = urlparse(stripped)
    if "youtu.be" in parsed.netloc:
        candidate = parsed.path.strip("/")
        return candidate[:11] if candidate else None
    query = parse_qs(parsed.query)
    value = query.get("v", [None])[0]
    return value[:11] if value else None


def _format_seconds(total: int) -> str:
    """Formatea segundos como ``M:SS`` o ``H:MM:SS``."""
    if total <= 0:
        return "0:00"
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _parse_likes_and_comments(initial_data: dict[str, Any]) -> tuple[str | None, str | None]:
    """Intenta leer likes y comentarios del ``ytInitialData`` (mejor esfuerzo).

    Returns:
        Tupla ``(likes, comentarios)``; cada valor puede ser ``None`` si la
        página no los expone (p. ej. vídeos con comentarios desactivados).
    """
    likes: str | None = None
    comments: str | None = None

    primary = _find_first(initial_data, "videoPrimaryInfoRenderer")
    if isinstance(primary, dict):
        buttons = (
            primary.get("videoActions", {})
            .get("menuRenderer", {})
            .get("topLevelButtons", [])
        )
        if buttons:
            first = buttons[0]
            renderer = first.get("toggleButtonRenderer") or first.get("buttonRenderer") or {}
            default_text = renderer.get("defaultText") or renderer.get("text")
            likes = _text(default_text) or None

    entry_point = _find_first(initial_data, "commentsEntryPointHeaderRenderer")
    if isinstance(entry_point, dict):
        count = entry_point.get("commentCount")
        comments = _text(count) or None

    return likes, comments


def parse_video_html(html: str, video_url: str) -> VideoData:
    """Parsea el HTML de una página pública de vídeo (``/watch?v=...``).

    Args:
        html: HTML público de la página del vídeo.
        video_url: URL del vídeo (se usa para el ID y el enlace canónico).

    Returns:
        Datos estructurados del vídeo. Los campos que la página no expone
        (likes, comentarios) quedan a ``None``.
    """
    video_id = extract_video_id(video_url) or ""
    player = _extract_embedded_json(html, "ytInitialPlayerResponse") or {}
    details = player.get("videoDetails", {}) or {}
    microformat = player.get("microformat", {}).get("playerMicroformatRenderer", {}) or {}

    title = details.get("title") or ""
    description = details.get("shortDescription") or ""
    hashtags = list(dict.fromkeys(HASHTAG_RE.findall(description)))

    try:
        length_seconds = int(details.get("lengthSeconds") or 0)
    except (TypeError, ValueError):
        length_seconds = 0

    thumbnails = details.get("thumbnail", {}).get("thumbnails", [])
    channel_id = details.get("channelId") or ""
    author = details.get("author") or microformat.get("ownerChannelName") or ""
    channel_url = (
        f"https://www.youtube.com/channel/{channel_id}"
        if channel_id
        else f"https://www.youtube.com/@{author}"
    )

    likes, comments = _parse_likes_and_comments(
        _extract_embedded_json(html, "ytInitialData") or {}
    )

    return VideoData(
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}" if video_id else video_url,
        video_id=video_id,
        views=str(details.get("viewCount") or "0"),
        likes=likes,
        comments=comments,
        duration=_format_seconds(length_seconds) if length_seconds else None,
        publish_date=microformat.get("publishDate") or None,
        thumbnail_url=thumbnails[-1].get("url") if thumbnails else None,
        description=description or None,
        hashtags=hashtags,
        channel_name=author,
        channel_url=channel_url,
        extracted_at=datetime.now(),
    )


class VideoAnalyzer:
    """Analiza un vídeo de YouTube y devuelve :class:`VideoData`.

    Args:
        api_key: Clave de la YouTube Data API v3 (modo conforme a ToS).
        request_delay: Pausa entre peticiones en modo HTML (rate-limit).
        timeout: Timeout HTTP en segundos.
    """

    def __init__(
        self,
        api_key: str | None = None,
        request_delay: float = 1.5,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.request_delay = request_delay
        self.timeout = timeout

    async def analyze(self, video_url: str, mode: str = "auto") -> VideoData:
        """Extrae los datos públicos del vídeo.

        Args:
            video_url: URL del vídeo (``https://www.youtube.com/watch?v=...``,
                ``https://youtu.be/...`` o ID plano).
            mode: ``"auto"`` (API si hay clave, si no HTML), ``"api"`` o ``"html"``.

        Returns:
            Datos estructurados del vídeo.

        Raises:
            ValueError: si no se puede extraer un ID de vídeo válido, si el
                modo requiere API key y no se proporciona, o si la página no
                expone datos.
        """
        video_id = extract_video_id(video_url)
        if not video_id:
            raise ValueError(f"No se pudo extraer el ID de vídeo de: {video_url}")

        resolved = mode
        if resolved == "auto":
            resolved = "api" if self.api_key else "html"

        if resolved == "api":
            if not self.api_key:
                raise ValueError("El modo 'api' requiere YOUTUBE_API_KEY")
            return await self._analyze_via_api(video_id)
        if resolved == "html":
            return await self._analyze_via_html(video_id)
        raise ValueError(f"Modo desconocido: {mode!r}")

    async def _analyze_via_html(self, video_id: str) -> VideoData:
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"Extrayendo datos públicos de {watch_url} (modo html)")
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "es,en;q=0.8"},
            follow_redirects=True,
        ) as client:
            await asyncio.sleep(self.request_delay)
            response = await client.get(watch_url)
            response.raise_for_status()
            video = parse_video_html(response.text, watch_url)
            if not video.title:
                raise ValueError(f"No se pudo extraer el vídeo {video_id} (¿página válida?)")
            return video

    async def _analyze_via_api(self, video_id: str) -> VideoData:
        params = {"part": "snippet,contentDetails,statistics", "id": video_id, "key": self.api_key}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"Consultando vídeo {video_id} vía YouTube Data API")
            response = await client.get(f"{API_BASE}/videos", params=params)
            response.raise_for_status()
            items = response.json().get("items", [])
            if not items:
                raise ValueError(f"Vídeo no encontrado: {video_id}")
            item = items[0]

            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            content = item.get("contentDetails", {})
            description = snippet.get("description", "") or ""
            hashtags = list(dict.fromkeys(HASHTAG_RE.findall(description)))

            thumbnails = snippet.get("thumbnails", {})
            thumbnail = (
                thumbnails.get("maxres")
                or thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
            )
            channel_id = snippet.get("channelId", "")

            return VideoData(
                title=snippet.get("title", ""),
                url=f"https://www.youtube.com/watch?v={video_id}",
                video_id=video_id,
                views=str(statistics.get("viewCount", "0")),
                likes=str(statistics.get("likeCount", "")) or None,
                comments=str(statistics.get("commentCount", "")) or None,
                duration=(
                    _iso8601_duration_to_hms(content.get("duration", ""))
                    if content.get("duration")
                    else None
                ),
                publish_date=snippet.get("publishedAt", "").split("T")[0] or None,
                thumbnail_url=thumbnail.get("url") if thumbnail else None,
                description=description or None,
                hashtags=hashtags,
                channel_name=snippet.get("channelTitle", ""),
                channel_url=(
                    f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""
                ),
                extracted_at=datetime.now(),
            )
