"""Modelos del generador de guiones (scripting) de BARF.

Convierte los insights de estructura de un canal (``channel_overview``) en
un guion editable: escenas con duración, texto superpuesto, transición y
música sugerida. El :class:`Script` es la pieza que une investigación y
edición: se genera desde datos públicos y se materializa en un
:class:`~youber.video.models.Project` con ``youber.script.builder``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from youber.music.models import Mood
from youber.video.models import TextPosition, TransitionType


class SceneType(StrEnum):
    """Papel de una escena dentro del guion (estructura viral típica)."""

    HOOK = "hook"  # gancho: captar atención en los primeros segundos
    INTRO = "intro"  # presentación del tema
    CONTENT = "content"  # desarrollo / puntos clave
    CLIMAX = "climax"  # momento fuerte / revelación
    CTA = "cta"  # llamada a la acción


class Scene(BaseModel):
    """Una escena del guion: qué se ve, durante cuánto y con qué texto."""

    type: SceneType
    title: str
    duration: float = Field(gt=0, description="Duración en segundos")
    text: str = Field(description="Texto superpuesto (drawtext)")
    position: TextPosition = TextPosition.CENTER
    transition: TransitionType = TransitionType.FADE
    transition_duration: float = Field(default=1.0, gt=0)


class Script(BaseModel):
    """Guion completo derivado de los insights de un canal.

    Attributes:
        topic: Tema del vídeo propio.
        source_channel: Canal analizado (origen de la estructura).
        total_duration: Duración total del guion (s).
        scenes: Escenas ordenadas.
        hashtags: Hashtags sugeridos (de los más usados del canal).
        music_mood: Estado de ánimo sugerido para la música de fondo.
    """

    topic: str
    source_channel: str | None = None
    total_duration: float = Field(gt=0)
    scenes: list[Scene] = Field(min_length=1)
    hashtags: list[str] = Field(default_factory=list)
    music_mood: Mood | None = None

    def timeline(self) -> list[tuple[float, float]]:
        """Devuelve los intervalos ``(inicio, fin)`` de cada escena (s)."""
        start = 0.0
        intervals: list[tuple[float, float]] = []
        for scene in self.scenes:
            intervals.append((start, start + scene.duration))
            start += scene.duration
        return intervals
