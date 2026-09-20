"""Modelos del generador visual con IA local (ruta C de BARF).

Aquí están los *datos* del plan visual: el formato de salida
(:class:`Aspect`), el movimiento de cámara (:class:`Motion`), el estilo
(:class:`VisualStyle`), cada plano (:class:`Shot`) y el plan completo
(:class:`ShotPlan`).

Quién dibuja los planos (un modelo local tipo SDXL-Turbo o un generador de
prueba determinista) vive en :mod:`youber.visuals.generator`: este módulo no
depende de torch ni de la GPU.

Ética: el modelo genera **contenido original** a partir de tu guion; nada de
copiar material ajeno ni de scraping.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Aspect(StrEnum):
    """Formato de la pieza: horizontal, vertical o cuadrado.

    Los tamaños de *generación* son tamaños de entrenamiento de SDXL
    (evitan deformaciones al componer); los de *render* son los de entrega
    (1080p y familia). El escalado entre ambos lo hace FFmpeg.
    """

    LANDSCAPE = "16:9"
    VERTICAL = "9:16"
    SQUARE = "1:1"

    @property
    def ratio(self) -> float:
        """Relación de aspecto (``ancho / alto``)."""
        return _RATIOS[self]

    def generate_size(self) -> tuple[int, int]:
        """Tamaño al que genera el modelo (``ancho, alto``)."""
        return _GENERATE_SIZES[self]

    def render_size(self) -> tuple[int, int]:
        """Tamaño del vídeo entregado (``ancho, alto``)."""
        return _RENDER_SIZES[self]

    @property
    def is_vertical(self) -> bool:
        """``True`` para el formato de Shorts/Reels (9:16)."""
        return self is Aspect.VERTICAL


_RATIOS: dict[Aspect, float] = {
    Aspect.LANDSCAPE: 16 / 9,
    Aspect.VERTICAL: 9 / 16,
    Aspect.SQUARE: 1.0,
}

#: Tamaños de entrenamiento de SDXL (múltiplos de 8, sin recorte apreciable).
_GENERATE_SIZES: dict[Aspect, tuple[int, int]] = {
    Aspect.LANDSCAPE: (1344, 768),
    Aspect.VERTICAL: (768, 1344),
    Aspect.SQUARE: (1024, 1024),
}

_RENDER_SIZES: dict[Aspect, tuple[int, int]] = {
    Aspect.LANDSCAPE: (1920, 1080),
    Aspect.VERTICAL: (1080, 1920),
    Aspect.SQUARE: (1080, 1080),
}


class Motion(StrEnum):
    """Movimiento de cámara aplicado a un still (efecto Ken Burns)."""

    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    STATIC = "static"

    @property
    def is_zoom(self) -> bool:
        """``True`` si el movimiento cambia el zoom (y no solo desplaza)."""
        return self in (Motion.ZOOM_IN, Motion.ZOOM_OUT)


#: Ciclo de movimientos por defecto (alterna para que no se note el patrón).
DEFAULT_MOTION_CYCLE: tuple[Motion, ...] = (
    Motion.ZOOM_IN,
    Motion.PAN_LEFT,
    Motion.ZOOM_OUT,
    Motion.PAN_RIGHT,
    Motion.TILT_UP,
    Motion.TILT_DOWN,
)


#: Objetivo aproximado de segundos por plano (el selector lo ajusta por audio).
DEFAULT_SECONDS_PER_SHOT = 16.0


class VisualStyle(StrEnum):
    """Estilo visual de los planos (se añade al prompt de cada uno)."""

    CINEMATIC = "cinematic"
    DREAMY = "dreamy"
    DARK = "dark"
    VIBRANT = "vibrant"
    MINIMAL = "minimal"


#: Sufijo de prompt por estilo. Sin texto ni marcas de agua: el modelo no debe
#: escribir nada (los textos del guion los dibuja FFmpeg encima).
STYLE_SUFFIXES: dict[VisualStyle, str] = {
    VisualStyle.CINEMATIC: (
        "cinematic film still, dramatic lighting, shallow depth of field, 35mm, "
        "detailed, moody atmosphere, no text, no watermark"
    ),
    VisualStyle.DREAMY: (
        "dreamlike ethereal scene, soft diffused light, pastel haze, glowing bokeh, "
        "35mm, no text, no watermark"
    ),
    VisualStyle.DARK: (
        "dark moody scene, low key lighting, deep shadows, desaturated palette, "
        "volumetric light, cinematic, no text, no watermark"
    ),
    VisualStyle.VIBRANT: (
        "vivid saturated colors, golden hour light, high contrast, crisp details, "
        "photographic, no text, no watermark"
    ),
    VisualStyle.MINIMAL: (
        "minimalist composition, generous negative space, soft gradient background, "
        "clean shapes, subtle grain, no text, no watermark"
    ),
}


class Shot(BaseModel):
    """Un plano: qué se ve, cómo se mueve y cuánto dura.

    Attributes:
        index: Posición dentro del plan (0-based).
        prompt: Prompt completo enviado al generador de imagen.
        motion: Movimiento de cámara aplicado al still.
        duration: Duración en el montaje final (segundos).
        scene_index: Escena del guion a la que pertenece (si procede).
        beat: Plantilla de encuadre usada (trazabilidad del prompt).
        image: Ruta del still generado (si ya se generó).
        clip: Ruta del clip animado (si ya se animó).
    """

    index: int = Field(ge=0)
    prompt: str = Field(min_length=1)
    motion: Motion = Motion.ZOOM_IN
    duration: float = Field(gt=0)
    scene_index: int | None = None
    beat: str = ""
    image: Path | None = None
    clip: Path | None = None


class ShotPlan(BaseModel):
    """Plan visual completo listo para generar, animar y montar.

    Attributes:
        topic: Tema del vídeo (alimenta todos los prompts).
        style: Estilo visual aplicado.
        aspect: Formato de la pieza.
        fps: Fotogramas por segundo del render.
        transition: Duración del fundido entre planos (segundos).
        shots: Planos ordenados.
        music_mood: Mood de la música que inspira el estilo (informativo).
        keywords: Palabras clave usadas para los prompts.
        motion_offset: Desplazamiento del ciclo de movimientos (variedad).
        seconds_per_shot: Objetivo de segundos por plano usado para repartir.
        beat_bpm: Pulso medido de la canción, si se midió (informativo).
        beat_offset: Segundo del primer beat de la canción, si se midió.
        beat_aligned: ``True`` si los cortes cayeron sobre el pulso.
        style_reason: Por qué se eligió (o quién pidió) este estilo.
        style_scores: Puntuación de cada estilo con las señales de la pieza.
        style_signals: Señales (ejes) que decidieron el estilo.
        seed: Semilla base de las imágenes (para poder repetir el render).
    """

    topic: str = Field(min_length=1)
    style: VisualStyle = VisualStyle.CINEMATIC
    aspect: Aspect = Aspect.LANDSCAPE
    fps: int = Field(default=30, gt=0)
    transition: float = Field(default=0.8, ge=0)
    shots: list[Shot] = Field(default_factory=list)
    music_mood: str | None = None
    keywords: list[str] = Field(default_factory=list)
    motion_offset: int = Field(default=0, ge=0)
    seconds_per_shot: float = Field(default=DEFAULT_SECONDS_PER_SHOT, gt=0)
    beat_bpm: float | None = Field(default=None, gt=0)
    beat_offset: float | None = Field(default=None, ge=0)
    beat_aligned: bool = False
    style_reason: str = ""
    style_scores: dict[str, float] = Field(default_factory=dict)
    style_signals: dict[str, float] = Field(default_factory=dict)
    seed: int | None = None

    @property
    def total_duration(self) -> float:
        """Duración del montaje: suma de planos menos solapamientos."""
        if not self.shots:
            return 0.0
        return max(
            0.0,
            sum(shot.duration for shot in self.shots)
            - self.transition * (len(self.shots) - 1),
        )

    def shot_start(self, index: int) -> float:
        """Instante en el que arranca el plano ``index`` (segundos)."""
        if index <= 0:
            return 0.0
        durations = [shot.duration for shot in self.shots[:index]]
        return sum(durations) - self.transition * index

    def scene_shot_index(self, scene_index: int) -> int | None:
        """Índice del primer plano de una escena (``None`` si no tiene)."""
        for shot in self.shots:
            if shot.scene_index == scene_index:
                return shot.index
        return None
