"""Módulo de subida a YouTube de BARF.

Sube **contenido propio** (o con licencia) a YouTube usando la YouTube Data
API v3 con OAuth 2.0: autenticación, metadatos (título, descripción, tags,
categoría, privacidad), publicación programada, **miniatura**
(``thumbnails.set``) y **pistas de subtítulos** (``captions.insert``).

Límites éticos (igual que el resto del framework):

- Solo vídeos propios o con permiso; sin spam ni contenido malicioso.
- Sin manipulación de métricas: se publica, no se infla.
- Uso educativo y de investigación.
"""

from youber.upload.auth import YouTubeAuth
from youber.upload.captions import build_multipart_body, caption_snippet
from youber.upload.chapters import build_chapters, chapters_from_script, format_timestamp
from youber.upload.metadata import PrivacyStatus, VideoMetadata
from youber.upload.thumbnail import ThumbnailResult, make_thumbnail, pick_thumbnail_time
from youber.upload.youtube import YouTubeUploader

__all__ = [
    "PrivacyStatus",
    "ThumbnailResult",
    "VideoMetadata",
    "YouTubeAuth",
    "YouTubeUploader",
    "build_chapters",
    "build_multipart_body",
    "caption_snippet",
    "chapters_from_script",
    "format_timestamp",
    "make_thumbnail",
    "pick_thumbnail_time",
]
