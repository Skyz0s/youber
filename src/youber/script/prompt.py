"""Del perfil de letras al **prompt** de producción y al guion.

Cierra el flujo «metadatos → letras → vídeo»: toma los insights de un canal
(metadatos de sus vídeos), el perfil temático de ese contenido y la canción
elegida por su letra, y produce:

- un :class:`VideoBrief` con el **prompt** de producción en texto (tono,
  estructura, keywords de B-roll para Pexels y banda sonora);
- un :class:`~youber.script.models.Script` listo para
  :func:`youber.script.builder.build_project` y el render local con FFmpeg.

Todo es offline y determinista (léxicos locales, sin servicios externos).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from youber.music.lyrics_analyzer import LyricsAnalysis
from youber.music.models import Mood
from youber.music.selector import TrackMatch, theme_profile
from youber.script.generator import DEFAULT_DURATION, MIN_TARGET_DURATION, generate_script
from youber.script.models import Script

#: Tono narrativo sugerido por tema dominante.
TONE_BY_THEME: dict[str, str] = {
    "felicidad": "luminoso y optimista",
    "tristeza": "melancólico y nostálgico",
    "energia": "enérgico y dinámico",
    "calma": "sereno y contemplativo",
    "misterio": "intrigante y atmosférico",
    "amor": "cálido e íntimo",
}

_TONE_BY_SENTIMENT: dict[str, str] = {
    "positive": "luminoso y optimista",
    "negative": "melancólico y reflexivo",
    "neutral": "neutro y descriptivo",
}

MAX_KEYWORDS = 8


class TrackBrief(BaseModel):
    """Canción elegida por su letra para la banda sonora del vídeo."""

    id: str
    title: str
    artist: str | None = None
    score: float = 0.0
    reason: str = ""
    matched_themes: list[str] = Field(default_factory=list)


class VideoBrief(BaseModel):
    """Prompt de producción de un vídeo derivado de los metadatos y las letras.

    Attributes:
        topic: Tema del vídeo.
        source: Canal/vídeo de referencia (origen de los metadatos).
        tone: Tono narrativo sugerido.
        themes: Temas emocionales del contenido → peso.
        sentiment: Sentimiento global del contenido.
        keywords: Términos de búsqueda para clips de B-roll (Pexels/Pixabay).
        music_mood: Estado de ánimo de la música.
        target_duration: Duración objetivo en segundos.
        track: Canción elegida por su letra (o ``None`` si no hay catálogo).
        prompt: El prompt de producción en texto plano.
    """

    topic: str
    source: str | None = None
    tone: str = "neutro y descriptivo"
    themes: dict[str, float] = Field(default_factory=dict)
    sentiment: str = "neutral"
    keywords: list[str] = Field(default_factory=list)
    music_mood: Mood | None = None
    target_duration: float = DEFAULT_DURATION
    track: TrackBrief | None = None
    prompt: str = ""


def _target_duration(insights: dict[str, Any], duration: float | None) -> float:
    """Duración objetivo: explícita o la media de los vídeos del canal."""
    if duration and duration > 0:
        return float(duration)
    avg = insights.get("duration_stats", {}).get("avg_seconds")
    if avg and avg > 0:
        return max(float(avg), MIN_TARGET_DURATION)
    return DEFAULT_DURATION


def brief_keywords(
    insights: dict[str, Any], profile: LyricsAnalysis | None
) -> list[str]:
    """Palabras clave para B-roll: hashtags del canal + palabras del contenido."""
    keywords: list[str] = []
    for entry in insights.get("top_hashtags") or []:
        hashtag = entry.get("hashtag")
        if hashtag:
            keywords.append(str(hashtag))
    if profile is not None:
        keywords.extend(profile.top_words)
    return list(dict.fromkeys(keywords))[:MAX_KEYWORDS]


def _tone(profile: LyricsAnalysis | None) -> str:
    """Tono narrativo: por tema dominante y, si no, por sentimiento."""
    if profile is not None and profile.dominant_theme:
        tone = TONE_BY_THEME.get(profile.dominant_theme)
        if tone:
            return tone
    sentiment = profile.sentiment if profile is not None else "neutral"
    return _TONE_BY_SENTIMENT.get(sentiment, _TONE_BY_SENTIMENT["neutral"])


def _prompt_text(brief: VideoBrief, insights: dict[str, Any]) -> str:
    """Compone el prompt de producción en texto plano."""
    channel = (insights.get("channel") or {}).get("name")
    lines = [
        f"🎬 PROMPT DE PRODUCCIÓN — «{brief.topic}»",
        f"Referencia: {brief.source or channel or 'contenido propio'}",
        f"Duración objetivo: {brief.target_duration:g} s · Tono: {brief.tone} · "
        f"Sentimiento: {brief.sentiment}",
    ]
    if brief.themes:
        themes = ", ".join(f"{theme} {weight:.2f}" for theme, weight in brief.themes.items())
        lines.append(f"Temas del contenido (letras): {themes}")
    lines.append("Estructura: gancho → intro → desarrollo (3 bloques) → clímax → CTA")
    if brief.keywords:
        lines.append("B-roll (Pexels/Pixabay): " + ", ".join(brief.keywords))
    if brief.track is not None:
        artist = f" — {brief.track.artist}" if brief.track.artist else ""
        lines.append(
            f"Banda sonora: «{brief.track.title}»{artist} · motivo: {brief.track.reason}"
        )
    if brief.music_mood is not None:
        lines.append(f"Mood de la música: {brief.music_mood.value}")
    return "\n".join(lines)


def build_video_brief(
    insights: dict[str, Any],
    *,
    topic: str,
    duration: float | None = None,
    profile: LyricsAnalysis | None = None,
    metadata_text: str | None = None,
    track_match: TrackMatch | None = None,
    keywords: list[str] | None = None,
) -> VideoBrief:
    """Construye el prompt de producción a partir de metadatos + letras.

    Args:
        insights: Salida de :func:`youber.research.patterns.channel_overview`.
        topic: Tema del vídeo propio.
        duration: Duración objetivo en segundos (por defecto: media del canal).
        profile: Perfil temático del contenido (si falta, se calcula desde
            ``metadata_text`` con el léxico de :mod:`youber.music.lyrics_analyzer`).
        metadata_text: Texto de los metadatos (títulos, descripciones, hashtags).
        track_match: Canción elegida por su letra (:mod:`youber.music.selector`).
        keywords: Palabras clave explícitas para el B-roll.

    Returns:
        El :class:`VideoBrief` con el prompt de producción ya compuesto.
    """
    if profile is None:
        profile = theme_profile(metadata_text or topic)

    moods = profile.moods()
    brief = VideoBrief(
        topic=topic,
        source=(insights.get("channel") or {}).get("name"),
        tone=_tone(profile),
        themes=profile.themes,
        sentiment=profile.sentiment,
        keywords=(
            list(dict.fromkeys(keywords))[:MAX_KEYWORDS]
            if keywords
            else brief_keywords(insights, profile)
        ),
        music_mood=moods[0] if moods else None,
        target_duration=_target_duration(insights, duration),
        track=(
            TrackBrief(
                id=track_match.track_id,
                title=track_match.title,
                artist=track_match.artist,
                score=track_match.score,
                reason=track_match.reason,
                matched_themes=track_match.matched_themes,
            )
            if track_match is not None
            else None
        ),
    )
    brief.prompt = _prompt_text(brief, insights)
    return brief


def brief_to_script(
    brief: VideoBrief,
    insights: dict[str, Any],
    transcripts: Any = None,
) -> Script:
    """Materializa el brief en un guion editable (escenas + textos + keywords).

    Usa :func:`youber.script.generator.generate_script` con el tema, la
    duración, el mood y las keywords del brief, de forma que el guion sea
    coherente con el prompt y con la canción elegida.
    """
    return generate_script(
        insights,
        topic=brief.topic,
        duration=brief.target_duration,
        music_mood=brief.music_mood,
        transcripts=transcripts,
        content_keywords=brief.keywords or None,
    )
