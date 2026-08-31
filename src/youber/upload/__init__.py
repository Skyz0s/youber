"""Módulo de subida a YouTube de BARF.

Sube **contenido propio** (o con licencia) a YouTube usando la YouTube Data
API v3 con OAuth 2.0: autenticación, metadatos (título, descripción, tags,
categoría, privacidad) y publicación programada.

Límites éticos (igual que el resto del framework):

- Solo vídeos propios o con permiso; sin spam ni contenido malicioso.
- Sin manipulación de métricas: se publica, no se infla.
- Uso educativo y de investigación.
"""

from youber.upload.auth import YouTubeAuth
from youber.upload.metadata import PrivacyStatus, VideoMetadata
from youber.upload.youtube import YouTubeUploader

__all__ = [
    "PrivacyStatus",
    "VideoMetadata",
    "YouTubeAuth",
    "YouTubeUploader",
]
