"""Datos del videoclip **dirigido por la letra** (``youber.musicvideo``).

Aquí se invierte la jerarquía del flujo anterior: antes un vídeo nacía de los
metadatos de un canal (tema → canción → guion de vídeo hablado) y la letra
solo elegía la canción. Ahora la **canción es la protagonista** y su letra es
la *directora*: cada línea con su ventana temporal se convierte en un plano,
la duración de la pieza es la de la canción y la estructura es la de la
canción (verso/estribillo/puente), no una plantilla de vídeo hablado.

El resultado son dos líneas de producción desde la misma dirección:

- el **videoclip** completo (duración = canción);
- un **corto vertical** con los *mejores momentos* (:class:`Highlight`), para
  la promoción en Shorts/Reels.

Ética: la letra es tuya (o se transcribe de tu propio audio); el vídeo es
contenido original generado en local. Nada de material ajeno ni de métricas.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from youber.music.models import Mood
from youber.visuals.beats import VisualBeat

#: Plano vacío de arranque (una escena sin plano todavía); se rellena al dirigir.
_DEFAULT_BEAT = VisualBeat(camera="", subject="")


class MusicVideoError(RuntimeError):
    """Error del módulo ``musicvideo`` (letra sin tiempos y sin duración...)."""


class SongSection(StrEnum):
    """Papel de un tramo de la canción (la estructura la dicta la canción)."""

    INTRO = "intro"
    VERSE = "verse"
    PRE_CHORUS = "pre_chorus"
    CHORUS = "chorus"
    BRIDGE = "bridge"
    OUTRO = "outro"
    UNKNOWN = "unknown"


class SectionSpan(BaseModel):
    """Un tramo de la canción con su papel y sus señales.

    Attributes:
        kind: Papel del tramo (intro, verso, estribillo...).
        start: Segundo de inicio.
        end: Segundo de fin.
        lines: Líneas que cubre (normalizadas para medir repetición).
        repetition: Cuántas veces se canta el contenido del tramo en la
            canción (>= 1). El estribillo es el tramo que más se repite.
        energy: Energía medida del tramo (``0..1``), si se midió.
    """

    kind: SongSection = SongSection.UNKNOWN
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    lines: list[str] = Field(default_factory=list)
    repetition: int = Field(default=1, ge=1)
    energy: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def duration(self) -> float:
        """Duración del tramo (segundos)."""
        return max(0.0, self.end - self.start)


class LyricScene(BaseModel):
    """Una línea de la letra convertida en escena (la letra dirige).

    Attributes:
        index: Posición dentro del videoclip (0-based).
        text: La línea, tal cual se canta (es el texto que se quema en pantalla).
        start: Segundo en el que empieza a sonar.
        end: Segundo en el que termina.
        section: Tramo de la canción al que pertenece.
        section_index: Índice del :class:`SectionSpan` (``-1`` si no se pudo).
        beat: Planos (cámara/sujeto/acción/escena/luz) **derivados de la línea**.
        keywords: Términos de la línea para B-roll (inglés, best-effort).
        energy: Energía medida del tramo (``0..1``), si se midió.
        hook: ``True`` si la línea se repite (gancho/estribillo).
    """

    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    section: SongSection = SongSection.UNKNOWN
    section_index: int = Field(default=-1, ge=-1)
    beat: VisualBeat = Field(default_factory=lambda: _DEFAULT_BEAT.model_copy())
    keywords: list[str] = Field(default_factory=list)
    energy: float | None = Field(default=None, ge=0.0, le=1.0)
    hook: bool = False

    @property
    def duration(self) -> float:
        """Duración de la escena (segundos)."""
        return max(0.0, self.end - self.start)


class Highlight(BaseModel):
    """Un *mejor momento* de la canción (la base del corto vertical).

    Attributes:
        start: Segundo de inicio (absoluto, dentro de la canción).
        end: Segundo de fin.
        reason: Por qué se eligió (auditable).
        section: Papel del tramo elegido.
        score: Puntuación (repetición + energía).
        repetition: Veces que se canta el tramo.
        energy: Energía medida del tramo (``0..1``).
    """

    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    reason: str = ""
    section: SongSection = SongSection.UNKNOWN
    score: float = 0.0
    repetition: int = Field(default=1, ge=1)
    energy: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def duration(self) -> float:
        """Duración del momento (segundos)."""
        return max(0.0, self.end - self.start)


class MusicVideoPlan(BaseModel):
    """La dirección completa de un videoclip: escenas, tramos y cortes.

    Es el documento que produce :mod:`youber.musicvideo.director` y del que
    salen las dos líneas de producción:
    :meth:`to_shot_plan` (planos que genera el motor visual) y
    :meth:`to_script` (guion con el texto de cada línea para quemar en pantalla).

    Attributes:
        title: Título de la canción.
        artist: Intérprete (si se conoce).
        duration: Duración de la pieza (segundos).
        timed: ``True`` si las líneas traían marcas de tiempo reales.
        scenes: Una escena por línea (directora del vídeo).
        sections: Tramos detectados (intro, verso, estribillo...).
        highlights: Mejores momentos (el corto vertical sale del primero).
        mood: Ánimo global de la pieza (si se conoce).
        sentiment: Sentimiento global (``positive``/``neutral``/``negative``).
    """

    title: str = ""
    artist: str | None = None
    duration: float = Field(gt=0)
    timed: bool = False
    scenes: list[LyricScene] = Field(default_factory=list)
    sections: list[SectionSpan] = Field(default_factory=list)
    highlights: list[Highlight] = Field(default_factory=list)
    mood: Mood | None = None
    sentiment: str = "neutral"

    def highlight_scenes(self, highlight: Highlight | None = None) -> list[LyricScene]:
        """Escenas que caen dentro de un momento (por defecto, el mejor).

        El corte vertical se compone con estas escenas; se recortan las que
        solapan parcialmente para que el corto empiece y acabe donde manda el
        momento elegido.
        """
        target = highlight or (self.highlights[0] if self.highlights else None)
        if target is None:
            return list(self.scenes)
        return [
            scene
            for scene in self.scenes
            if scene.end > target.start and scene.start < target.end
        ]
