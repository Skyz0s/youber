"""Metadatos de vídeo para la subida a YouTube.

Modelo tipado con los campos que acepta la YouTube Data API v3: título,
descripción, etiquetas (tags), categoría, privacidad y fecha de publicación
programada.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

# Categorías comunes de YouTube (id → nombre). Lista completa vía
# youtube.videos.categories.list con la API.
CATEGORY_IDS = {
    "22": "People & Blogs",
    "24": "Entertainment",
    "27": "Education",
    "28": "Science & Technology",
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "20": "Gaming",
}


class PrivacyStatus(StrEnum):
    """Nivel de privacidad del vídeo publicado."""

    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"


class VideoMetadata(BaseModel):
    """Metadatos de un vídeo a subir a YouTube.

    Attributes:
        title: Título del vídeo (obligatorio, 1-100 caracteres).
        description: Descripción (opcional).
        tags: Etiquetas de búsqueda (opcional).
        category_id: Id de categoría de YouTube (por defecto 22, People & Blogs).
        privacy_status: public / unlisted / private (por defecto private).
        publish_at: Fecha de publicación programada (opcional). Si se indica,
            la API exige ``privacy_status=private``.
    """

    title: str = Field(min_length=1, max_length=100)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    category_id: str = Field(default="22", pattern=r"^\d+$")
    privacy_status: PrivacyStatus = PrivacyStatus.PRIVATE
    publish_at: datetime | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def _split_tags(cls, value: object) -> object:
        """Acepta una cadena ``"a,b,c"`` o una lista; normaliza a lista."""
        if isinstance(value, str):
            return [tag.strip() for tag in value.split(",") if tag.strip()]
        return value

    def category_name(self) -> str:
        """Nombre legible de la categoría (o el id si es desconocida)."""
        return CATEGORY_IDS.get(self.category_id, self.category_id)

    def to_snippet(self) -> dict:
        """Devuelve el objeto ``snippet`` de la API de YouTube."""
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "categoryId": self.category_id,
        }

    def to_status(self) -> dict:
        """Devuelve el objeto ``status`` de la API de YouTube.

        Si hay ``publish_at``, fuerza ``privacyStatus=private`` (requisito de
        la API para publicaciones programadas) e incluye ``publishAt`` en
        formato ISO 8601 con zona horaria.
        """
        status: dict = {"privacyStatus": self.privacy_status.value}
        if self.publish_at is not None:
            status["privacyStatus"] = PrivacyStatus.PRIVATE.value
            status["publishAt"] = self.publish_at.astimezone().isoformat()
        return status
