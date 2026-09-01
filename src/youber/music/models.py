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


class TrackSource(StrEnum):
    """Origen de una pista del catálogo.

    ``local`` son ficheros de audio propios (escaneados con ffprobe);
    el resto son metadatos públicos importados desde plataformas
    (``spotify``, ``apple``/iTunes, ``youtube``) — **sin descargar audio**.
    """

    LOCAL = "local"
    SPOTIFY = "spotify"
    APPLE = "apple"
    YOUTUBE = "youtube"


class Track(BaseModel):
    """Pista musical del catálogo.

    Las pistas ``local`` apuntan a un fichero de audio real; las pistas
    importadas desde plataformas (``source`` != ``local``) usan una ruta
    sintética ``cloud:<source>:<external_id>`` y solo guardan metadatos
    públicos (título, artista, álbum, carátula, preview) — nunca audio.
    """

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
    source: TrackSource = TrackSource.LOCAL
    external_id: str | None = None
    album: str | None = None
    artwork_url: str | None = None
    preview_url: str | None = None
