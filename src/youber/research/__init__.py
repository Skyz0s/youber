"""Módulo de investigación de YouTube de BARF.

Herramientas educativas para extraer datos **públicos** de canales y vídeos
de YouTube (título, visualizaciones, likes, duración, hashtags...) y
analizarlos de forma estructurada: modelos tipados, análisis de patrones y
exportación a JSON/CSV/Markdown.

Límites éticos (igual que el resto del framework):

- Solo datos públicos visibles en la web; sin login ni evasión de anti-bot.
- Respeto a robots.txt y términos de servicio (modo API = conforme a ToS).
- Sin manipulación de métricas: esto es análisis, no inflado.
- Uso educativo y de investigación.
"""

from youber.research.channel_analyzer import ChannelAnalyzer, parse_channel_html
from youber.research.data_models import ChannelData, VideoData
from youber.research.exporters import (
    export_channel,
    export_videos,
    generate_channel_json,
    generate_channel_markdown,
    generate_videos_csv,
)
from youber.research.patterns import (
    channel_overview,
    duration_stats,
    extract_hashtags,
    hashtag_frequency,
    parse_duration_to_seconds,
    title_patterns,
)
from youber.research.video_analyzer import VideoAnalyzer, parse_video_html

__all__ = [
    "ChannelAnalyzer",
    "ChannelData",
    "VideoAnalyzer",
    "VideoData",
    "channel_overview",
    "duration_stats",
    "export_channel",
    "export_videos",
    "extract_hashtags",
    "generate_channel_json",
    "generate_channel_markdown",
    "generate_videos_csv",
    "hashtag_frequency",
    "parse_channel_html",
    "parse_duration_to_seconds",
    "parse_video_html",
    "title_patterns",
]
