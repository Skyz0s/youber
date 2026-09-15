"""Modelos del *registro de decisiones* (decision journal) de BARF.

Cada vídeo generado deja una **huella auditable**: qué tendencia/patrón se
detectó en los metadatos de referencia, qué atributos se extrajeron, por qué
se eligió una canción (con qué puntuación y con qué candidatas competía), qué
vídeo se generó y —más tarde— cómo rindió realmente (impresiones, CTR,
retención, visualizaciones, suscripciones...).

Con el tiempo, ese registro se convierte en el **dataset** con el que estudiar
qué características del *matching* predicen de verdad que un vídeo funcione:
el journal no es solo un generador, es el cuaderno de laboratorio del
proyecto.

Es análisis descriptivo de **datos propios**: no se manipula ninguna métrica
de plataforma (nada de views/likes/watch time artificiales).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

#: Versión del algoritmo que produjo una decisión. Permite estudiar la
#: deriva del matcher (comparar decisiones de distintas versiones).
ALGORITHM_VERSION = "journal-1"

#: Ventanas temporales habituales de las métricas de rendimiento.
WINDOWS: tuple[str, ...] = ("24h", "48h", "7d", "14d", "28d", "lifetime")


def new_decision_id() -> str:
    """Genera un identificador corto y único para una decisión."""
    return f"dec-{uuid4().hex[:12]}"


class ContentAttributes(BaseModel):
    """Atributos extraídos de los metadatos del contenido de referencia.

    Es lo que el algoritmo «vio»: el perfil temático del texto de los
    metadatos, el sentimiento, las palabras clave y los patrones de títulos
    del canal que se usaron para construir el prompt.
    """

    topic: str = ""
    #: Canal/vídeo de referencia del que salieron los metadatos.
    source: str | None = None
    #: Temas emocionales detectados → peso (0..1).
    themes: dict[str, float] = Field(default_factory=dict)
    dominant_theme: str | None = None
    sentiment: str = "neutral"
    keywords: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    #: Patrones de títulos del canal (`youber.research.patterns.title_patterns`).
    title_patterns: dict[str, int] = Field(default_factory=dict)
    videos_analyzed: int = 0
    metadata_words: int = 0
    target_duration: float = 0.0


class TrackCandidate(BaseModel):
    """Pista candidata puntuada por el selector (para auditar la elección)."""

    rank: int = 0
    track_id: str
    title: str
    artist: str | None = None
    score: float = 0.0
    matched_themes: list[str] = Field(default_factory=list)
    reason: str = ""


class TrackDecision(BaseModel):
    """Decisión sobre la banda sonora: qué canción, por qué y contra qué.

    Guarda explícitamente las señales que usó el scoring (tema compartido,
    sentimiento, mood, keywords, favorita, uso previo) para poder estudiar
    después **qué señal** se correlaciona con el rendimiento.
    """

    chosen_id: str | None = None
    chosen_title: str | None = None
    chosen_artist: str | None = None
    #: Duración de la canción elegida (s): el vídeo se ajusta a ella.
    duration_seconds: float | None = None
    score: float = 0.0
    reason: str = ""
    matched_themes: list[str] = Field(default_factory=list)
    #: Puntuación ponderada por temas compartidos (peso vídeo × peso letra).
    theme_score: float = 0.0
    sentiment_match: bool = False
    mood_match: bool = False
    favorite: bool = False
    usage_count: int = 0
    keyword_hits: int = 0
    #: ``True`` si la canción se forzó a mano (``--track``) en vez de elegirla.
    forced: bool = False
    catalog_size: int = 0
    #: Ranking completo de candidatas (la primera es la elegida).
    candidates: list[TrackCandidate] = Field(default_factory=list)

    @property
    def margin(self) -> float | None:
        """Ventaja sobre la siguiente candidata (decisividad de la elección).

        Un *margin* bajo significa que varias canciones encajaban casi igual
        (decisión poco informativa); alto significa elección clara.
        """
        if self.chosen_id is None or len(self.candidates) < 2:
            return None
        ranked = sorted(self.candidates, key=lambda candidate: candidate.score, reverse=True)
        return round(ranked[0].score - ranked[1].score, 4)


class VideoArtifact(BaseModel):
    """Vídeo generado: fichero, duración, tamaño y procedencia de los clips."""

    path: str | None = None
    duration_seconds: float | None = None
    size_bytes: int | None = None
    scene_count: int = 0
    clip_count: int = 0
    #: ``local`` (tus clips), ``pexels``/``pixabay`` (stock) o ``synthetic``.
    clip_source: str = "none"
    music_mood: str | None = None


class UploadRecord(BaseModel):
    """Subida del vídeo: el id público permite cruzar métricas más tarde."""

    video_id: str | None = None
    url: str | None = None
    title: str | None = None
    privacy: str | None = None
    published_at: datetime | None = None
    uploaded_at: datetime = Field(default_factory=datetime.now)


class PerformanceSnapshot(BaseModel):
    """Métricas de rendimiento de un vídeo en una ventana temporal.

    Los campos son los que exporta YouTube Studio (o los que se registran a
    mano). Todo es opcional: una ventana puede tener solo lo que se conozca.
    """

    window: str = "7d"
    captured_at: datetime = Field(default_factory=datetime.now)
    impressions: int | None = Field(default=None, ge=0)
    views: int | None = Field(default=None, ge=0)
    #: CTR de las impresiones, en porcentaje (0..100).
    ctr: float | None = Field(default=None, ge=0, le=100)
    watch_time_minutes: float | None = Field(default=None, ge=0)
    avg_view_duration_seconds: float | None = Field(default=None, ge=0)
    #: Porcentaje medio visto (retención), 0..100.
    avg_view_percentage: float | None = Field(default=None, ge=0, le=100)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    subscribers_gained: int | None = Field(default=None)
    subscribers_lost: int | None = Field(default=None)
    revenue: float | None = Field(default=None, ge=0)
    #: Columnas extra del CSV original (trazabilidad de la fuente).
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("window")
    @classmethod
    def _clean_window(cls, value: str) -> str:
        """Normaliza la ventana temporal (``7d``, ``28d``, ``lifetime``...)."""
        cleaned = (value or "7d").strip().lower()
        if not cleaned or len(cleaned) > 16 or " " in cleaned:
            raise ValueError(f"Ventana no válida: {value!r} (p. ej. 7d, 28d, lifetime)")
        return cleaned

    @property
    def retention(self) -> float | None:
        """Retención media (porcentaje medio visto)."""
        return self.avg_view_percentage

    @property
    def engagement(self) -> int | None:
        """Interacciones totales (me gusta + comentarios + compartidos)."""
        parts = [self.likes, self.comments, self.shares]
        if all(part is None for part in parts):
            return None
        return sum(part or 0 for part in parts)

    @property
    def engagement_rate(self) -> float | None:
        """Interacciones por visualización, en porcentaje."""
        engagement = self.engagement
        if engagement is None or not self.views:
            return None
        return round(100.0 * engagement / self.views, 4)

    @property
    def net_subscribers(self) -> int | None:
        """Suscripciones netas (altas − bajas)."""
        if self.subscribers_gained is None and self.subscribers_lost is None:
            return None
        return (self.subscribers_gained or 0) - (self.subscribers_lost or 0)


class DecisionRecord(BaseModel):
    """Una decisión completa: de los metadatos al vídeo generado.

    El :attr:`id` es estable y es la clave con la que se cuelgan las métricas
    posteriores (:class:`PerformanceSnapshot`).
    """

    id: str = Field(default_factory=new_decision_id)
    created_at: datetime = Field(default_factory=datetime.now)
    #: Identificador de la ejecución del workflow que produjo la decisión.
    run_id: str | None = None
    topic: str = ""
    source_channel: str | None = None
    source_url: str | None = None
    #: Modo de investigación usado: ``html``, ``api`` o ``demo``.
    mode: str = "html"
    algorithm_version: str = ALGORITHM_VERSION
    attributes: ContentAttributes = Field(default_factory=ContentAttributes)
    track: TrackDecision = Field(default_factory=TrackDecision)
    prompt: str = ""
    #: Rutas de los artefactos generados (brief, guion, markdown, json...).
    artifacts: dict[str, str] = Field(default_factory=dict)
    video: VideoArtifact = Field(default_factory=VideoArtifact)
    upload: UploadRecord | None = None
    notes: str = ""
    tags: list[str] = Field(default_factory=list)

    @property
    def video_id(self) -> str | None:
        """ID público del vídeo subido (o ``None`` si aún no se subió)."""
        return self.upload.video_id if self.upload is not None else None
