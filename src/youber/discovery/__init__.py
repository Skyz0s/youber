"""Módulo de descubrimiento de canales de YouTube de BARF.

Busca y analiza canales por **categorías, temas y métricas públicas** para
facilitar la investigación de mercado: categorías predefinidas, buscador con
doble vía (YouTube Data API v3 / página pública), ranking por métricas,
canales similares, caché de resultados y CLI ``youber-discovery``.

Límites éticos (igual que el resto del framework):

- Solo datos públicos; sin login ni evasión de anti-bot.
- Respeto a robots.txt y términos de servicio (modo API = conforme a ToS).
- Sin manipulación de métricas: esto es descubrimiento/análisis, no inflado.
- Uso educativo y de investigación.
"""

from youber.discovery.cache import DEFAULT_CACHE_PATH, DiscoveryCache
from youber.discovery.categories import (
    CATEGORY_TOPICS,
    ChannelCategory,
    all_categories,
    infer_category,
    topic_scores,
    topics_for,
)
from youber.discovery.ranking import (
    RankedChannel,
    RankingMetric,
    engagement_score,
    metric_value,
    rank_channels,
    summarize,
    views_per_video,
)
from youber.discovery.search import (
    ChannelHit,
    ChannelSearcher,
    SearchResult,
    parse_search_html,
)
from youber.discovery.similarity import (
    SimilarChannel,
    find_similar,
    shared_topics,
    similarity_score,
)

__all__ = [
    "CATEGORY_TOPICS",
    "ChannelCategory",
    "ChannelHit",
    "ChannelSearcher",
    "DEFAULT_CACHE_PATH",
    "DiscoveryCache",
    "RankedChannel",
    "RankingMetric",
    "SearchResult",
    "SimilarChannel",
    "all_categories",
    "engagement_score",
    "find_similar",
    "infer_category",
    "metric_value",
    "parse_search_html",
    "rank_channels",
    "shared_topics",
    "similarity_score",
    "summarize",
    "topic_scores",
    "topics_for",
    "views_per_video",
]
