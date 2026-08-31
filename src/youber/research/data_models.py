"""Modelos de datos tipados para la investigación de YouTube.

Define :class:`VideoData` y :class:`ChannelData` con pydantic v2: los campos
reflejan datos **públicos** visibles en la web/API de YouTube y se serializan
fácilmente a JSON/CSV/Markdown para análisis posterior.

Nota: se usa ``Field(default_factory=...)`` en lugar de valores por defecto
directos (``datetime.now()`` como default se evaluaría una sola vez al
importar el módulo, compartiendo timestamp entre todas las instancias).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class VideoData(BaseModel):
    """Datos públicos de un vídeo de YouTube."""

    title: str
    url: str
    video_id: str
    views: str
    likes: str | None = None
    comments: str | None = None
    duration: str | None = None
    publish_date: str | None = None
    thumbnail_url: str | None = None
    description: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    channel_name: str
    channel_url: str
    extracted_at: datetime = Field(default_factory=datetime.now)


class ChannelData(BaseModel):
    """Datos públicos de un canal de YouTube, con su lista de vídeos."""

    name: str
    url: str
    handle: str | None = None
    subscribers: str | None = None
    total_views: str | None = None
    videos: list[VideoData] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=datetime.now)
