"""Modelos de datos del motor de producción con OpenMontage.

Define la especificación del vídeo patrón y el plan de producción
que se ejecuta con el pipeline hybrid de OpenMontage.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PatternSource(StrEnum):
    """Origen del vídeo patrón."""

    LOCAL = "local"
    YOUTUBE = "youtube"


class PatternSpec(BaseModel):
    """Especificación del vídeo patrón de entrada.

    Args:
        source: Tipo de origen (local o YouTube).
        path: Ruta local al fichero (si LOCAL) o URL de YouTube.
        title: Título del vídeo patrón (para referencia).
        duration: Duración total en segundos.
        resolution: Tupla (width, height) del vídeo patrón.
        fps: Framerate del vídeo patrón.
        has_audio: Si tiene pista de audio.
        audio_peaks: Momentos de mayor energía de audio (segundos).
        scene_changes: Momentos de cambio de plano detectados (segundos).
        color_palette: Colores dominantes (hex) extraídos del vídeo.
        transitions: Tipos de transiciones detectadas entre escenas.
        transcript: Transcripción si está disponible (opcional, v2).
        metadata: Metadatos adicionales (exif, etc.).
    """

    source: PatternSource
    path: str
    title: str = Field(min_length=1)
    duration: float = Field(gt=0)
    resolution: tuple[int, int]
    fps: float = Field(gt=0)
    has_audio: bool = True
    audio_peaks: list[float] = Field(default_factory=list)
    scene_changes: list[float] = Field(default_factory=list)
    color_palette: list[str] = Field(default_factory=list)
    transitions: list[str] = Field(default_factory=list)
    transcript: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    analyzed_at: datetime = Field(default_factory=datetime.now)


class ProductionMode(StrEnum):
    """Modo de producción del vídeo final."""

    REMIX = "remix"  # Reutiliza el footage patrón como base visual
    INSPIRED = "inspired"  # Solo estructura/ritmo, genera visuales nuevas con OpenMontage
    HYBRID = "hybrid"  # Mezcla: footage propio + overlays generados


class AudioSource(BaseModel):
    """Especificación de la pista de audio a usar."""

    # Uno de estos tres (prioridad en orden):
    track_id: str | None = None  # ID en catálogo youber.music
    mood: str | None = None  # Mood para buscar en catálogo
    file_path: Path | None = None  # Archivo local arbitrario

    # Ajustes
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    start_at: float = Field(default=0.0, ge=0)  # Offset en la pista
    loop: bool = False  # Repetir si es más corto que el vídeo


class ProductionPlan(BaseModel):
    """Plan de producción completo para OpenMontage."""

    pattern: PatternSpec
    mode: ProductionMode = ProductionMode.HYBRID
    audio: AudioSource = Field(default_factory=AudioSource)
    target_duration: float | None = None  # Si None, usa duración del patrón
    target_resolution: tuple[int, int] = (1920, 1080)
    target_fps: int = 30
    output_path: Path | None = None
    # Configuración OpenMontage
    pipeline: str = "hybrid"
    playbook: str = "clean-professional"
    budget_usd: float = 2.0
    # Metadatos de salida
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


class ProductionResult(BaseModel):
    """Resultado de la producción."""

    success: bool
    output_path: Path | None = None
    duration: float = 0.0
    resolution: tuple[int, int] = (0, 0)
    error: str | None = None
    openmontage_report: dict[str, Any] | None = None
    completed_at: datetime = Field(default_factory=datetime.now)