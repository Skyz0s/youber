"""Modelos de datos del módulo de audio de BARF.

Configuración tipada para las operaciones de edición y resultado
estructurado de cada procesado.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class AudioConfig(BaseModel):
    """Configuración para añadir música de fondo a un vídeo."""

    music_path: Path
    volume: float = Field(default=0.3, ge=0.0, le=1.0)
    music_start: float = Field(default=0.0, ge=0.0)
    fade_in: float = Field(default=2.0, ge=0.0)
    fade_out: float = Field(default=2.0, ge=0.0)
    loop: bool = True
    original_audio_volume: float = Field(default=0.7, ge=0.0, le=1.0)


class ProcessingResult(BaseModel):
    """Resultado de una operación de procesado de audio/vídeo."""

    success: bool
    output_path: Path | None = None
    duration: float | None = None
    error: str | None = None
