"""Modelos de datos del catálogo de música de BARF.

Define el estado de ánimo (:class:`Mood`) y la pista musical
(:class:`Track`) que el catálogo local gestiona: metadatos, etiquetas de
estado de ánimo, uso y favoritos.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Mood(StrEnum):
    """Estado de ánimo / tema de una pista (etiquetas de búsqueda)."""

    ENERGETIC = "energética"
    RELAXING = "relajante"
    EPIC = "épica"
    FOCUSED = "productiva"
    SAD = "triste"
    HAPPY = "alegre"
    MYSTERIOUS = "misteriosa"
    CUSTOM = "personalizada"


class Track(BaseModel):
    """Pista musical del catálogo local."""

    id: str
    file_path: Path
    title: str = Field(min_length=1)
    artist: str | None = None
    duration: float = Field(ge=0)
    genre: str | None = None
    moods: list[Mood] = Field(default_factory=list)
    bpm: int | None = None
    key: str | None = None
    favorite: bool = False
    usage_count: int = 0
    last_used: datetime | None = None
    added_at: datetime = Field(default_factory=datetime.now)
    file_hash: str
