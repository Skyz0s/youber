"""Generador de guiones a partir de insights de estructura de un canal.

Analiza los patrones de éxito de un canal de YouTube (duración media,
patrones de títulos, hashtags) y produce un :class:`Script` con la
estructura viral típica:

- **Hook** (gancho): captar atención en los primeros segundos.
- **Intro**: presentar el tema.
- **Contenido**: desarrollo en puntos (2-3 escenas).
- **Clímax**: momento fuerte / revelación.
- **CTA**: llamada a la acción.

Las duraciones se escalan a la duración media de los vídeos del canal y
los textos superpuestos se inspiran en sus patrones de títulos (números,
MAYÚSCULAS, preguntas, "vs", listas "top N").

Ética: es un generador de ideas de edición para **tu propio vídeo**; no
copia contenido ajeno ni manipula métricas.
"""

from __future__ import annotations

from typing import Any

from youber.music.models import Mood
from youber.script.models import Scene, SceneType, Script
from youber.script.transcripts import TranscriptAnalysis, hook_template
from youber.video.models import TextPosition, TransitionType

# Proporción de la duración total para cada tipo de escena.
_STRUCTURE: list[tuple[SceneType, float]] = [
    (SceneType.HOOK, 0.10),
    (SceneType.INTRO, 0.15),
    (SceneType.CONTENT, 0.25),
    (SceneType.CONTENT, 0.20),
    (SceneType.CONTENT, 0.15),
    (SceneType.CLIMAX, 0.10),
    (SceneType.CTA, 0.05),
]

# Términos de búsqueda de stock (B-roll) por tipo de escena. En inglés
# porque Pexels/Pixabay indexan mejor el material audiovisual en inglés.
_SCENE_KEYWORDS: dict[SceneType, list[str]] = {
    SceneType.HOOK: ["dramatic", "suspense", "close up", "action"],
    SceneType.INTRO: ["person talking", "introduction", "presenter", "studio"],
    SceneType.CONTENT: ["working", "desk", "workspace", "laptop"],
    SceneType.CLIMAX: ["epic", "reveal", "dramatic moment", "sunset"],
    SceneType.CTA: ["subscribe", "hand gesture", "call to action", "thank you"],
}

DEFAULT_DURATION = 60.0  # duración objetivo si el canal no aporta datos


def _target_duration(insights: dict[str, Any], duration: float | None) -> float:
    """Duración total del guion: explícita o la media del canal."""
    if duration and duration > 0:
        return float(duration)
    stats = insights.get("duration_stats", {})
    avg = stats.get("avg_seconds")
    if avg and avg > 0:
        return float(avg)
    return DEFAULT_DURATION


def _hook_text(patterns: dict[str, Any], topic: str) -> str:
    """Texto del gancho según los patrones de títulos del canal."""
    if patterns.get("with_question", 0) >= 2:
        return f"¿{topic.capitalize()}?"
    if patterns.get("with_numbers", 0) >= 2:
        return f"3 CLAVES sobre {topic}"
    if patterns.get("with_vs", 0):
        return f"{topic}: ¿lo haces bien?"
    return topic.upper()


def _scene_titles(topic: str, patterns: dict[str, Any]) -> dict[SceneType, str]:
    """Títulos de escena derivados del tema y los patrones del canal."""
    numbered = patterns.get("with_numbers", 0) >= 2
    titles: dict[SceneType, str] = {
        SceneType.INTRO: f"Introducción: {topic}",
        SceneType.CLIMAX: "El momento clave",
        SceneType.CTA: "¿Te ha servido? Comenta 👇",
    }
    if numbered:
        titles[SceneType.CONTENT] = f"Punto 1: lo esencial de {topic}"
    else:
        titles[SceneType.CONTENT] = f"Desarrollo: {topic}"
    return titles


def _content_instructions(
    topic: str, index: int, total: int, analysis: TranscriptAnalysis | None
) -> str:
    """Instrucción de una escena de contenido.

    Si hay transcripción del canal patrón, usa una frase real como
    referencia del estilo; si no, cae a la plantilla con el tema.
    """
    if analysis and analysis.samples:
        reference = analysis.samples[(index - 1) % len(analysis.samples)]
        return (
            f"Bloque {index}/{total}: desarrolla «{topic}» — "
            f"estilo del patrón: «{reference[:100]}»"
        )
    return f"{topic} — punto {index} de {total}"


def _cta_instruction(topic: str, analysis: TranscriptAnalysis | None) -> str:
    """Instrucción de CTA: referencia real del patrón o plantilla."""
    if analysis and analysis.ctas:
        return f"CTA: «{analysis.ctas[0][:120]}» — adapta a «{topic}»"
    return f"¿Te ha servido {topic}? Comenta 👇"


def _climax_instruction(topic: str, analysis: TranscriptAnalysis | None) -> str:
    """Instrucción del clímax: momento fuerte con el tema."""
    if analysis and analysis.hooks:
        return f"Clímax: revela lo mejor de «{topic}» (el patrón abre con «{analysis.hooks[0][:80]}»)"
    return f"El momento clave de {topic}"


def generate_script(
    insights: dict[str, Any],
    topic: str,
    duration: float | None = None,
    music_mood: Mood | None = None,
    transcripts: TranscriptAnalysis | None = None,
) -> Script:
    """Genera un guion con estructura viral a partir de los insights.

    Args:
        insights: Salida de :func:`youber.research.patterns.channel_overview`.
        topic: Tema del vídeo propio.
        duration: Duración total en segundos (por defecto: media del canal).
        music_mood: Estado de ánimo para la música (por defecto: se infiere).
        transcripts: Análisis de transcripciones públicas del canal patrón
            (opcional). Si se aporta, las escenas incluyen instrucciones
            reales del estilo del canal en lugar de plantillas.

    Returns:
        Un :class:`Script` listo para construir el proyecto de edición.
    """
    total = _target_duration(insights, duration)
    patterns = insights.get("title_patterns", {})
    titles = _scene_titles(topic, patterns)
    channel = insights.get("channel", {}).get("name")

    mood = music_mood or _infer_mood(insights)

    scenes: list[Scene] = []
    content_index = 0
    content_count = sum(1 for stype, _ in _STRUCTURE if stype == SceneType.CONTENT)
    for scene_type, ratio in _STRUCTURE:
        scene_duration = max(2.0, round(total * ratio, 1))
        if scene_type == SceneType.HOOK:
            if transcripts is not None:
                text = hook_template(topic, transcripts)
            else:
                text = _hook_text(patterns, topic)
        elif scene_type == SceneType.CONTENT:
            content_index += 1
            base = titles.get(SceneType.CONTENT, f"Punto {content_index}")
            text = _content_instructions(topic, content_index, content_count, transcripts)
            scenes.append(
                Scene(
                    type=scene_type,
                    title=base,
                    duration=scene_duration,
                    text=text,
                    position=TextPosition.CENTER,
                    transition=TransitionType.FADE,
                    keywords=_SCENE_KEYWORDS.get(scene_type, []),
                )
            )
            continue
        elif scene_type == SceneType.CLIMAX:
            text = _climax_instruction(topic, transcripts)
        elif scene_type == SceneType.CTA:
            text = _cta_instruction(topic, transcripts)
        else:
            text = titles.get(scene_type, f"{scene_type.value}: {topic}")
        scenes.append(
            Scene(
                type=scene_type,
                title=titles.get(scene_type, scene_type.value),
                duration=scene_duration,
                text=text,
                position=(
                    TextPosition.CENTER
                    if scene_type in (SceneType.HOOK, SceneType.CLIMAX, SceneType.CTA)
                    else TextPosition.BOTTOM_CENTER
                ),
                transition=(
                    TransitionType.FADE
                    if scene_type in (SceneType.HOOK, SceneType.INTRO)
                    else TransitionType.CROSSFADE
                ),
                keywords=_SCENE_KEYWORDS.get(scene_type, []),
            )
        )

    top_hashtags = insights.get("top_hashtags", [])[:5]
    hashtags = [entry["hashtag"] for entry in top_hashtags if entry.get("hashtag")]

    return Script(
        topic=topic,
        source_channel=channel,
        total_duration=round(total, 1),
        scenes=scenes,
        hashtags=hashtags,
        music_mood=mood,
    )


def _infer_mood(insights: dict[str, Any]) -> Mood:
    """Infere un estado de ánimo para la música según la duración del canal.

    Vídeos cortos → más enérgico; vídeos largos → más épico/focus.
    """
    stats = insights.get("duration_stats", {})
    avg = stats.get("avg_seconds")
    if avg is None:
        return Mood.ENERGETIC
    if avg < 240:  # < 4 min
        return Mood.ENERGETIC
    if avg < 900:  # 4-15 min
        return Mood.HAPPY
    return Mood.EPIC
