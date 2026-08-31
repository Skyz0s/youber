"""Análisis de canales de YouTube (datos públicos, uso educativo).

Extrae datos **públicos** de un canal (nombre, handle, suscriptores, vídeos
recientes) mediante dos vías:

- **API oficial (modo ``api``)**: YouTube Data API v3. Es la vía conforme a
  los términos de servicio; requiere ``YOUTUBE_API_KEY``.
- **Página pública (modo ``html``)**: parsea el JSON ``ytInitialData`` que
  YouTube embebe en las páginas públicas. Es la vía educativa: sin login,
  sin stealth, con rate-limit configurable. ``/watch`` y ``/channel`` no
  están bloqueados en el robots.txt de YouTube; aun así, úsalo con mesura
  y respetando la ToS (este proyecto es educativo).

Límites éticos: solo datos públicos, sin evasión de anti-bot, sin
manipulación de métricas. Esto es **análisis**, no inflado.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from loguru import logger

from youber.research.data_models import ChannelData, VideoData

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 youber-research"
)
API_BASE = "https://www.googleapis.com/youtube/v3"


# ---------------------------------------------------------------------------
# Utilidades de extracción de JSON embebido
# ---------------------------------------------------------------------------


def _extract_embedded_json(html: str, marker: str) -> dict[str, Any] | None:
    """Extrae y parsea el JSON embebido tras ``marker`` (p. ej. ``ytInitialData``).

    Escanea el primer objeto ``{...}`` equilibrado que aparece después del
    marcador, sin depender de regex frágiles sobre HTML completo.

    Args:
        html: HTML de la página.
        marker: Nombre de la variable JS (sin ``var``).

    Returns:
        El JSON parseado, o ``None`` si no se encuentra.
    """
    start = html.find(f"var {marker} =")
    if start == -1:
        start = html.find(f"var {marker}=")
    if start == -1:
        return None
    start = html.find("{", start)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(html)):
        char = html[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _find_first(node: Any, key: str) -> Any | None:
    """Devuelve el primer valor de ``key`` en un árbol JSON (recorrido en profundidad)."""

    def walk(current: Any) -> Any | None:
        if isinstance(current, dict):
            if key in current:
                return current[key]
            for value in current.values():
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(current, list):
            for value in current:
                found = walk(value)
                if found is not None:
                    return found
        return None

    return walk(node)


def _text(node: Any) -> str:
    """Extrae texto de un nodo de YouTube (``simpleText``, ``runs`` o cadena)."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if isinstance(node.get("simpleText"), str):
        return node["simpleText"]
    runs = node.get("runs")
    if isinstance(runs, list):
        return "".join(run.get("text", "") for run in runs if isinstance(run, dict))
    return ""


# ---------------------------------------------------------------------------
# Parser de la página pública de un canal
# ---------------------------------------------------------------------------


def _channel_header(data: dict[str, Any]) -> dict[str, Any]:
    """Localiza el renderer de cabecera del canal (layout nuevo o antiguo)."""
    header = data.get("header", {})
    for key in ("c4TabbedHeaderRenderer", "pageHeaderRenderer"):
        if isinstance(header.get(key), dict):
            return header[key]
    return {}


def _iter_video_renderers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Recorre los ``videoRenderer`` de la pestaña de vídeos del canal."""
    contents = data.get("contents", {})
    tabs = contents.get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    renderers: list[dict[str, Any]] = []
    for tab in tabs:
        content = tab.get("tabRenderer", {}).get("content", {})
        for container_key in ("richGridRenderer", "itemSectionRenderer"):
            container = content.get(container_key)
            if not isinstance(container, dict):
                continue
            for item in container.get("contents", []):
                inner = item.get("richItemRenderer", {}).get("content", {})
                renderer = inner.get("videoRenderer") or item.get("videoRenderer")
                if isinstance(renderer, dict):
                    renderers.append(renderer)
    return renderers


def _channel_url_from_header(header: dict[str, Any], fallback: str) -> str:
    nav = header.get("navigationEndpoint", {})
    base = nav.get("canonicalBaseUrl")
    if isinstance(base, str) and base:
        return f"https://www.youtube.com{base}"
    return fallback


def _handle_from_header(header: dict[str, Any]) -> str | None:
    handle_text = _text(header.get("channelHandleText"))
    if handle_text:
        return handle_text.lstrip("@")
    nav = header.get("navigationEndpoint", {})
    base = nav.get("canonicalBaseUrl", "")
    if isinstance(base, str) and base.startswith("/@"):
        return base[2:]
    return None


def parse_channel_html(html: str, channel_url: str) -> ChannelData:
    """Parsea el HTML de la pestaña de vídeos de un canal.

    Args:
        html: HTML público de ``https://www.youtube.com/<handle>/videos``.
        channel_url: URL canónica del canal (para rellenar ``ChannelData.url``).

    Returns:
        Datos estructurados del canal con sus vídeos visibles en la página.
    """
    data = _extract_embedded_json(html, "ytInitialData") or {}
    header = _channel_header(data)

    name = _text(header.get("title")) or _text(header.get("pageTitle"))
    if not name:
        name = urlparse(channel_url).path.strip("/").lstrip("@")

    subscribers = _text(header.get("subscriberCountText")) or None
    handle = _handle_from_header(header) or (
        urlparse(channel_url).path.strip("/").lstrip("@") or None
    )
    canonical = _channel_url_from_header(header, channel_url)

    videos: list[VideoData] = []
    for renderer in _iter_video_renderers(data):
        video_id = renderer.get("videoId")
        if not isinstance(video_id, str):
            continue
        title = _text(renderer.get("title"))
        if not title:
            continue
        thumbnails = renderer.get("thumbnail", {}).get("thumbnails", [])
        videos.append(
            VideoData(
                title=title,
                url=f"https://www.youtube.com/watch?v={video_id}",
                video_id=video_id,
                views=_text(renderer.get("viewCountText")) or "0",
                duration=_text(renderer.get("lengthText")) or None,
                publish_date=_text(renderer.get("publishedTimeText")) or None,
                thumbnail_url=(
                    thumbnails[-1].get("url") if thumbnails else None
                ),
                channel_name=name,
                channel_url=canonical,
            )
        )

    logger.debug(f"parse_channel_html: {len(videos)} vídeos de «{name}»")
    return ChannelData(
        name=name,
        url=canonical,
        handle=handle,
        subscribers=subscribers,
        videos=videos,
        extracted_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# Modo API oficial (YouTube Data API v3)
# ---------------------------------------------------------------------------


def _iso8601_duration_to_hms(duration: str) -> str:
    """Convierte una duración ISO 8601 (``PT1H2M3S``) a ``H:MM:SS``/``M:SS``."""
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return duration
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class ChannelAnalyzer:
    """Analiza un canal de YouTube y devuelve :class:`ChannelData`.

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

    async def analyze(
        self,
        channel_url: str,
        max_videos: int = 20,
        mode: str = "auto",
    ) -> ChannelData:
        """Extrae los datos públicos del canal.

        Args:
            channel_url: URL del canal (``https://www.youtube.com/@handle``,
                ``.../channel/UC...`` o ``@handle``).
            max_videos: Número máximo de vídeos a recoger.
            mode: ``"auto"`` (API si hay clave, si no HTML), ``"api"`` o
                ``"html"``.

        Returns:
            Datos estructurados del canal.

        Raises:
            ValueError: si el modo requiere API key y no se proporciona, o si
                no se puede extraer información de la página.
        """
        resolved = mode
        if resolved == "auto":
            resolved = "api" if self.api_key else "html"

        if resolved == "api":
            if not self.api_key:
                raise ValueError("El modo 'api' requiere YOUTUBE_API_KEY")
            return await self._analyze_via_api(channel_url, max_videos)
        if resolved == "html":
            return await self._analyze_via_html(channel_url, max_videos)
        raise ValueError(f"Modo desconocido: {mode!r}")

    # -- Modo HTML ---------------------------------------------------------

    async def _analyze_via_html(self, channel_url: str, max_videos: int) -> ChannelData:
        normalized = _normalize_channel_url(channel_url)
        videos_url = f"{normalized}/videos"
        logger.info(f"Extrayendo datos públicos de {videos_url} (modo html)")
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "es,en;q=0.8"},
            follow_redirects=True,
        ) as client:
            await asyncio.sleep(self.request_delay)
            response = await client.get(videos_url)
            response.raise_for_status()
            channel = parse_channel_html(response.text, normalized)
            channel.videos = channel.videos[:max_videos]
            return channel

    # -- Modo API ----------------------------------------------------------

    async def _analyze_via_api(self, channel_url: str, max_videos: int) -> ChannelData:
        handle = _extract_handle(channel_url)
        params: dict[str, Any] = {"part": "snippet,statistics,contentDetails", "key": self.api_key}
        if handle:
            params["forHandle"] = handle
        else:
            params["id"] = _extract_channel_id(channel_url)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"Consultando canal vía YouTube Data API ({handle or channel_url})")
            response = await client.get(f"{API_BASE}/channels", params=params)
            response.raise_for_status()
            items = response.json().get("items", [])
            if not items:
                raise ValueError(f"Canal no encontrado: {channel_url}")
            item = items[0]

            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            name = snippet.get("title", "")
            canonical = f"https://www.youtube.com/channel/{item.get('id', '')}"
            uploads = (
                item.get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads")
            )

            videos = await self._fetch_uploads_videos(
                client, uploads, max_videos, name, canonical
            )

            return ChannelData(
                name=name,
                url=canonical,
                handle=snippet.get("customUrl", "").lstrip("@") or None,
                subscribers=str(statistics.get("subscriberCount", "")),
                total_views=str(statistics.get("viewCount", "")),
                videos=videos,
                extracted_at=datetime.now(),
            )

    async def _fetch_uploads_videos(
        self,
        client: httpx.AsyncClient,
        uploads_playlist: str | None,
        max_videos: int,
        channel_name: str,
        channel_url: str,
    ) -> list[VideoData]:
        if not uploads_playlist:
            return []
        videos: list[VideoData] = []
        page_token: str | None = None

        while len(videos) < max_videos:
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist,
                "maxResults": min(50, max_videos - len(videos)),
                "key": self.api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            response = await client.get(f"{API_BASE}/playlistItems", params=params)
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items", [])
            if not items:
                break
            for entry in items:
                snippet = entry.get("snippet", {})
                video_id = entry.get("contentDetails", {}).get("videoId")
                if not video_id:
                    continue
                thumbnails = snippet.get("thumbnails", {})
                thumb = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default")
                videos.append(
                    VideoData(
                        title=snippet.get("title", ""),
                        url=f"https://www.youtube.com/watch?v={video_id}",
                        video_id=video_id,
                        views="0",
                        duration=None,
                        publish_date=snippet.get("publishedAt", "").split("T")[0],
                        thumbnail_url=thumb.get("url") if thumb else None,
                        channel_name=channel_name,
                        channel_url=channel_url,
                    )
                )
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        # Rellenar vistas/duraciones con el endpoint de vídeos (en lotes).
        for batch_start in range(0, len(videos), 50):
            batch = videos[batch_start : batch_start + 50]
            ids = ",".join(video.video_id for video in batch)
            params = {"part": "snippet,contentDetails,statistics", "id": ids, "key": self.api_key}
            response = await client.get(f"{API_BASE}/videos", params=params)
            response.raise_for_status()
            details = {item["id"]: item for item in response.json().get("items", [])}
            for video in batch:
                detail = details.get(video.video_id, {})
                stats = detail.get("statistics", {})
                video.views = str(stats.get("viewCount", "0"))
                video.likes = str(stats.get("likeCount", "")) or None
                video.comments = str(stats.get("commentCount", "")) or None
                content = detail.get("contentDetails", {})
                if content.get("duration"):
                    video.duration = _iso8601_duration_to_hms(content["duration"])
        return videos[:max_videos]


# ---------------------------------------------------------------------------
# Normalización de URLs
# ---------------------------------------------------------------------------


def _extract_handle(channel_url: str) -> str | None:
    """Extrae ``@handle`` (con o sin @) de una URL o referencia de canal."""
    stripped = channel_url.strip()
    if stripped.startswith("http"):
        path = urlparse(stripped).path
        if "/@" in path:
            return path.split("/@", 1)[1].split("/")[0]
        return None
    if stripped.startswith("@"):
        return stripped[1:].split("/")[0]
    return None


def _extract_channel_id(channel_url: str) -> str:
    path = urlparse(channel_url).path
    match = re.search(r"/channel/([^/]+)", path)
    if not match:
        raise ValueError(f"No se pudo extraer el ID de canal de: {channel_url}")
    return match.group(1)


def _normalize_channel_url(channel_url: str) -> str:
    """Convierte ``@handle`` / ``handle`` en la URL pública del canal."""
    stripped = channel_url.strip()
    if stripped.startswith("http"):
        return stripped.rstrip("/")
    if stripped.startswith("@"):
        return f"https://www.youtube.com/{stripped.lstrip('@')}"
    return f"https://www.youtube.com/@{quote(stripped)}"
