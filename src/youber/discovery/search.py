"""Buscador de canales de YouTube por categorías, temas y métricas (uso educativo).

Descubre canales de YouTube mediante dos vías (igual que ``youber.research``):

- **API oficial (modo ``api``)**: YouTube Data API v3 (conforme a ToS,
  requiere ``YOUTUBE_API_KEY``).
- **Página pública (modo ``html``)**: parsea ``ytInitialData`` de la página
  de resultados de búsqueda. Sin login, sin stealth, con rate-limit.
- **Modo ``demo``**: canales sintéticos deterministas (sin red), pensado
  para probar el flujo completo sin credenciales ni descargas.

Límites éticos: solo datos públicos; sin evasión de anti-bot; sin
manipulación de métricas. Esto es **descubrimiento para investigación de
mercado**, no inflado.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from youber.discovery.categories import ChannelCategory, infer_category, topics_for
from youber.research.channel_analyzer import _extract_embedded_json, _text

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 youber-discovery"
)
API_BASE = "https://www.googleapis.com/youtube/v3"
SEARCH_URL = "https://www.youtube.com/results"
# Filtro "canal" de la búsqueda de YouTube (sp=EgIQAg==).
CHANNEL_FILTER_SP = "EgIQAg%3D%3D"


class ChannelHit(BaseModel):
    """Canal descubierto (datos públicos, con métricas opcionales)."""

    channel_id: str
    title: str
    url: str
    handle: str | None = None
    description: str | None = None
    subscriber_count: int | None = None
    video_count: int | None = None
    view_count: int | None = None
    thumbnail_url: str | None = None
    category: ChannelCategory | None = None
    matched_topics: list[str] = Field(default_factory=list)
    score: float = 0.0
    source: str = "api"  # "api" | "html" | "demo"


class SearchResult(BaseModel):
    """Resultado de una búsqueda de canales."""

    query: str
    category: ChannelCategory | None = None
    backend: str
    channels: list[ChannelHit] = Field(default_factory=list)
    searched_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Parser de la página pública de resultados de búsqueda
# ---------------------------------------------------------------------------


def _iter_channel_renderers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Recorre los ``channelRenderer`` de la página de resultados de búsqueda."""
    contents = data.get("contents", {})
    search = contents.get("twoColumnSearchResultsRenderer", {})
    primary = search.get("primaryContents", {})
    sections = primary.get("sectionListRenderer", {}).get("contents", [])
    renderers: list[dict[str, Any]] = []
    for section in sections:
        items = section.get("itemSectionRenderer", {}).get("contents", [])
        for item in items:
            renderer = item.get("channelRenderer")
            if isinstance(renderer, dict):
                renderers.append(renderer)
    return renderers


def parse_search_html(html: str) -> list[ChannelHit]:
    """Parsea la página de resultados de búsqueda de YouTube.

    Args:
        html: HTML público de ``/results?search_query=...``.

    Returns:
        Canales encontrados (sin métricas numéricas si no se muestran).
    """
    data = _extract_embedded_json(html, "ytInitialData") or {}
    hits: list[ChannelHit] = []
    for renderer in _iter_channel_renderers(data):
        channel_id = renderer.get("channelId")
        if not isinstance(channel_id, str):
            continue
        title = _text(renderer.get("title"))
        if not title:
            continue
        description = _text(renderer.get("descriptionSnippet")) or None
        nav = renderer.get("navigationEndpoint", {}).get("browseEndpoint", {})
        base = nav.get("canonicalBaseUrl")
        handle = base.lstrip("/@") if isinstance(base, str) and base else None
        thumbnails = renderer.get("thumbnail", {}).get("thumbnails", [])
        category = infer_category(f"{title} {description or ''}")
        hits.append(
            ChannelHit(
                channel_id=channel_id,
                title=title,
                url=f"https://www.youtube.com/channel/{channel_id}",
                handle=handle,
                description=description,
                subscriber_count=_compact_int(renderer.get("subscriberCountText")),
                video_count=_compact_int(renderer.get("videoCountText")),
                thumbnail_url=thumbnails[-1].get("url") if thumbnails else None,
                category=category,
                matched_topics=_match_topics(title, description, category),
                source="html",
            )
        )
    logger.debug(f"parse_search_html: {len(hits)} canales")
    return hits


def _compact_int(node: Any) -> int | None:
    """Convierte un nodo de texto ("1,2 M de suscriptores") en entero."""
    value = _parse_compact(_text(node))
    return int(value) if value is not None else None


# El parser de números compactos del módulo research (``parse_compact_count``)
# no cubre textos con sufijo seguido de más palabras ("1,2 M de suscriptores"):
# el ``\b`` del regex falla entre la "M" y la "d". Aquí uno local más robusto.
_COMPACT_RE = re.compile(r"(\d[\d.,]*)\s*([KMBkmb]?)(?!\w)")


def _parse_compact(text: str) -> float | None:
    """Parsea "1,2 M de suscriptores", "345 vídeos" o "1.234.567" a número.

    Mejor esfuerzo para los formatos habituales de YouTube en español:
    coma decimal ("1,2 M"), puntos de miles ("1.234.567") y sufijos K/M/B.
    """
    if not text:
        return None
    match = _COMPACT_RE.search(text)
    if not match:
        return None
    raw, suffix = match.groups()
    try:
        if "," in raw:
            value = float(raw.replace(".", "").replace(",", "."))
        else:
            value = float(raw.replace(".", ""))
    except ValueError:
        return None
    multiplier = {"": 1.0, "k": 1_000.0, "m": 1_000_000.0, "b": 1_000_000_000.0}
    return value * multiplier.get(suffix.lower(), 1.0)


def _match_topics(
    title: str, description: str | None, category: ChannelCategory | None
) -> list[str]:
    """Devuelve los temas de la categoría que aparecen en título/descripción."""
    if category is None:
        return []
    text = f"{title} {description or ''}".lower()
    return [topic for topic in topics_for(category) if topic.lower() in text]


# ---------------------------------------------------------------------------
# Buscador
# ---------------------------------------------------------------------------


class ChannelSearcher:
    """Busca canales de YouTube por texto, categoría o temas.

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

    async def search(
        self,
        query: str | None = None,
        category: ChannelCategory | None = None,
        topics: list[str] | None = None,
        limit: int = 10,
        mode: str = "auto",
    ) -> SearchResult:
        """Busca canales y los clasifica por categoría y temas.

        Args:
            query: Texto libre. Si no se da, se construye desde ``category``
                o ``topics``.
            category: Categoría predefinida (expande sus temas).
            topics: Temas concretos (alternativa a ``category``).
            limit: Número máximo de canales a devolver.
            mode: ``"auto"`` (API si hay clave, si no HTML), ``"api"``,
                ``"html"`` o ``"demo"`` (sintético, sin red).

        Raises:
            ValueError: si no hay término de búsqueda o el modo es inválido.
        """
        term = self._build_query(query, category, topics)
        backend = self._resolve_mode(mode)

        if backend == "api":
            channels = await self._search_via_api(term, limit)
        elif backend == "html":
            channels = await self._search_via_html(term, limit)
        elif backend == "demo":
            channels = self._search_demo(term, limit, category)
        else:
            raise ValueError(f"Modo desconocido: {mode!r}")

        return SearchResult(
            query=term,
            category=category,
            backend=backend,
            channels=channels,
        )

    # -- Utilidades --------------------------------------------------------

    def _build_query(
        self,
        query: str | None,
        category: ChannelCategory | None,
        topics: list[str] | None,
    ) -> str:
        """Construye el término de búsqueda a partir de los criterios."""
        if query and query.strip():
            return query.strip()
        if topics:
            return " ".join(topics)
        if category:
            return " ".join(topics_for(category)[:5])
        raise ValueError("Indica un texto, una categoría o temas de búsqueda")

    def _resolve_mode(self, mode: str) -> str:
        if mode == "auto":
            return "api" if self.api_key else "html"
        return mode

    def _categorize(self, hit: ChannelHit) -> ChannelHit:
        """Clasifica el canal en una categoría y calcula sus temas."""
        text = f"{hit.title} {hit.description or ''}"
        hit.category = infer_category(text)
        hit.matched_topics = _match_topics(hit.title, hit.description, hit.category)
        return hit

    # -- Modo API ----------------------------------------------------------

    async def _search_via_api(self, term: str, limit: int) -> list[ChannelHit]:
        if not self.api_key:
            raise ValueError("El modo 'api' requiere YOUTUBE_API_KEY")
        params: dict[str, Any] = {
            "part": "snippet",
            "type": "channel",
            "q": term,
            "maxResults": min(limit, 50),
            "key": self.api_key,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"Buscando canales vía YouTube Data API: {term!r}")
            response = await client.get(f"{API_BASE}/search", params=params)
            response.raise_for_status()
            items = response.json().get("items", [])
            ids = [
                item.get("id", {}).get("channelId")
                for item in items
                if item.get("id", {}).get("channelId")
            ]
            stats = await self._fetch_channel_stats(client, ids)

            hits: list[ChannelHit] = []
            for item in items:
                channel_id = item.get("id", {}).get("channelId")
                snippet = item.get("snippet", {})
                title = snippet.get("title", "")
                description = snippet.get("description", "")
                thumbs = snippet.get("thumbnails", {})
                thumb = thumbs.get("high") or thumbs.get("medium") or thumbs.get("default")
                stat = stats.get(channel_id, {})
                hit = ChannelHit(
                    channel_id=channel_id,
                    title=title,
                    url=f"https://www.youtube.com/channel/{channel_id}",
                    handle=(snippet.get("channelTitle") or None),
                    description=description or None,
                    subscriber_count=_int_or_none(stat.get("subscriberCount")),
                    video_count=_int_or_none(stat.get("videoCount")),
                    view_count=_int_or_none(stat.get("viewCount")),
                    thumbnail_url=thumb.get("url") if thumb else None,
                    source="api",
                )
                hits.append(self._categorize(hit))
            return hits[:limit]

    async def _fetch_channel_stats(
        self, client: httpx.AsyncClient, channel_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Recupera las estadísticas de varios canales (lotes de 50)."""
        stats: dict[str, dict[str, Any]] = {}
        for start in range(0, len(channel_ids), 50):
            batch = channel_ids[start : start + 50]
            params: dict[str, Any] = {
                "part": "statistics",
                "id": ",".join(batch),
                "key": self.api_key,
            }
            response = await client.get(f"{API_BASE}/channels", params=params)
            response.raise_for_status()
            for item in response.json().get("items", []):
                stats[item["id"]] = item.get("statistics", {})
        return stats

    # -- Modo HTML ---------------------------------------------------------

    async def _search_via_html(self, term: str, limit: int) -> list[ChannelHit]:
        url = f"{SEARCH_URL}?search_query={quote(term)}&sp={CHANNEL_FILTER_SP}"
        logger.info(f"Buscando canales en {url} (modo html)")
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "es,en;q=0.8"},
            follow_redirects=True,
        ) as client:
            await asyncio.sleep(self.request_delay)
            response = await client.get(url)
            response.raise_for_status()
            hits = parse_search_html(response.text)
            return [self._categorize(hit) for hit in hits][:limit]

    # -- Modo demo (sintético, sin red) ------------------------------------

    def _search_demo(
        self,
        term: str,
        limit: int,
        category: ChannelCategory | None,
    ) -> list[ChannelHit]:
        """Genera canales sintéticos deterministas para probar sin red."""
        seed = int(hashlib.sha256(term.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)
        pool_topics = topics_for(category) if category else [term]
        hits: list[ChannelHit] = []
        for index in range(limit):
            topic = pool_topics[index % len(pool_topics)]
            subs = rng.randint(5_000, 5_000_000)
            videos = rng.randint(20, 2_000)
            title = f"CanalDemo {index + 1} · {topic.title()}"
            hit = ChannelHit(
                channel_id=f"demo{index + 1:03d}",
                title=title,
                url=f"https://www.youtube.com/channel/demo{index + 1:03d}",
                handle=f"democanal{index + 1}",
                description=f"Canal de demostración sobre {topic} (sintético).",
                subscriber_count=subs,
                video_count=videos,
                view_count=subs * rng.randint(3, 30),
                thumbnail_url=None,
                category=category or infer_category(title),
                matched_topics=[topic],
                source="demo",
            )
            hits.append(hit)
        return hits


def _int_or_none(value: Any) -> int | None:
    """Convierte un valor de la API a entero (o ``None``)."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
