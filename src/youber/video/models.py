"""Modelos de datos del motor de edición de vídeo de BARF.

Define los tipos de transición, posiciones de texto, clips, overlays,
transiciones y el :class:`Project` completo que el motor renderiza con
FFmpeg.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class TransitionType(StrEnum):
    """Tipo de transición entre dos clips consecutivos."""

    NONE = "none"
    FADE = "fade"
    CROSSFADE = "crossfade"
    WIPE = "wipe"
    SLIDE = "slide"


class TextPosition(StrEnum):
    """Posición de un texto superpuesto en el encuadre."""

    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER = "center"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


class Clip(BaseModel):
    """Un clip de vídeo dentro del proyecto.

    Attributes:
        file_path: Ruta al fichero de vídeo (MP4, MOV, AVI, MKV).
        start: Offset de inicio dentro del fichero (segundos).
        duration: Duración del clip en el resultado (si es ``None``, se usa
            todo el resto del fichero).
        volume: Volumen del audio del clip (0.0-2.0).
        speed: Velocidad de reproducción (1.0 = normal; >1 acelera).
        crop: Recorte ``(x, y, width, height)`` aplicado antes de escalar.
    """

    file_path: Path
    start: float = Field(default=0.0, ge=0)
    duration: float | None = Field(default=None, gt=0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    speed: float = Field(default=1.0, gt=0)
    crop: tuple[int, int, int, int] | None = None


class TextOverlay(BaseModel):
    """Texto superpuesto sobre el vídeo (filtro ``drawtext``)."""

    text: str = Field(min_length=1)
    position: TextPosition = TextPosition.BOTTOM_CENTER
    font_size: int = Field(default=48, gt=0)
    color: str = "white"
    background: str | None = "black@0.5"
    font_file: str | None = None
    start_time: float = Field(default=0.0, ge=0)
    duration: float | None = Field(default=None, gt=0)


class ImageOverlay(BaseModel):
    """Imagen superpuesta (marca de agua) sobre el vídeo."""

    image_path: Path
    position: TextPosition = TextPosition.BOTTOM_RIGHT
    opacity: float = Field(default=0.8, ge=0.0, le=1.0)
    scale: float = Field(default=0.15, gt=0, le=1.0)
    start_time: float = Field(default=0.0, ge=0)
    duration: float | None = Field(default=None, gt=0)


class Transition(BaseModel):
    """Transición entre dos clips consecutivos.

    Attributes:
        clip_index: Índice del clip donde termina la transición (entre el
            clip ``clip_index-1`` y el ``clip_index``).
        type: Tipo de transición.
        duration: Duración de la transición en segundos.
    """

    clip_index: int = Field(ge=1)
    type: TransitionType = TransitionType.FADE
    duration: float = Field(default=1.0, gt=0)


class Project(BaseModel):
    """Proyecto de edición de vídeo completo."""

    title: str = Field(min_length=1)
    clips: list[Clip] = Field(default_factory=list)
    music_track_id: str | None = None
    music_volume: float = Field(default=0.3, ge=0.0, le=1.0)
    transitions: list[Transition] = Field(default_factory=list)
    text_overlays: list[TextOverlay] = Field(default_factory=list)
    image_overlays: list[ImageOverlay] = Field(default_factory=list)
    output_format: str = "mp4"
    resolution: tuple[int, int] = (1920, 1080)
    fps: int = Field(default=30, gt=0)
    created_at: str | None = None
    updated_at: str | None = None
