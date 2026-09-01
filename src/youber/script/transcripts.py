"""Análisis de transcripciones públicas para generar guiones automáticos.

Extrae los subtítulos públicos de los vídeos más virales de un canal
(``youtube-transcript-api``, sin login — son datos públicos) y analiza la
**estructura real del discurso**:

- **Hook**: qué dice el canal en los primeros segundos (cómo capta atención).
- **CTA**: qué dice al final (llamadas a la acción).
- **Transiciones**: cómo conecta las ideas.

Con eso, el generador de guiones produce **instrucciones concretas por
escena** (referencia real del patrón + adaptación a tu tema) en lugar de
plantillas genéricas. Ética: solo subtítulos públicos, sin descargar
vídeo/audio, sin evadir nada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from youber.research.data_models import VideoData

HOOK_SECONDS = 20.0
CTA_SECONDS = 25.0
CTA_MARKERS = (
    "suscríb",
    "suscrib",
    "comenta",
    "dale",
    "like",
    "deja un",
    "sígueme",
    "sigueme",
    "gracias por ver",
    "comparte",
    "activa la campana",
    "sigue",
    "más vídeos",
    "más videos",
    "link",
    "enlace",
    "compra",
    "libro",
    "merch",
    "instagram",
    "twitter",
    "tiktok",
    "aplica el código",
)


@dataclass
class TranscriptSnippet:
    """Un fragmento de transcripción con su marca de tiempo."""

    start: float
    text: str


@dataclass
class TranscriptAnalysis:
    """Estructura del discurso extraída de los vídeos del canal patrón."""

    hooks: list[str] = field(default_factory=list)
    ctas: list[str] = field(default_factory=list)
    avg_hook_duration: float | None = None
    video_count: int = 0
    samples: list[str] = field(default_factory=list)


def fetch_transcript(
    video_id: str, languages: tuple[str, ...] = ("es", "en")
) -> list[TranscriptSnippet]:
    """Devuelve los fragmentos de la transcripción pública de un vídeo.

    Returns:
        Lista de :class:`TranscriptSnippet` ordenada por tiempo, o vacía si
        no hay transcripción disponible (vídeo sin subtítulos, restringido…).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=list(languages))
        return [
            TranscriptSnippet(start=float(entry.start), text=entry.text)
            for entry in fetched
        ]
    except Exception:
        return []


def _clean(text: str) -> str:
    """Limpia el texto del subtítulo (espacios, guiones de línea)."""
    text = text.replace("\n", " ").replace("  ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _first_words(snippets: list[TranscriptSnippet], seconds: float) -> str:
    """Las primeras palabras dentro de los ``seconds`` primeros segundos.

    Los subtítulos de YouTube a veces repiten segmentos consecutivos;
    se eliminan los duplicados contiguos para no repetir frases.
    """
    parts: list[str] = []
    last = ""
    for s in snippets:
        if s.start > seconds:
            break
        clean = _clean(s.text)
        if clean and clean != last:
            parts.append(clean)
            last = clean
    return " ".join(parts)[:280]


def _cta_from_tail(snippets: list[TranscriptSnippet]) -> list[str]:
    """Frases de CTA del tramo final del vídeo (con marcadores típicos)."""
    if not snippets:
        return []
    end = snippets[-1].start
    tail = [s for s in snippets if s.start >= end - CTA_SECONDS]
    found: list[str] = []
    for snippet in tail:
        text = _clean(snippet.text).lower()
        if any(marker in text for marker in CTA_MARKERS):
            clean = _clean(snippet.text)
            if clean and clean not in found:
                found.append(clean[:180])
    return found[:3]


def analyze_video(video_id: str) -> TranscriptAnalysis | None:
    """Analiza un vídeo: devuelve su hook y CTA (o ``None`` sin transcripción)."""
    snippets = fetch_transcript(video_id)
    if not snippets:
        return None
    hook = _first_words(snippets, HOOK_SECONDS)
    ctas = _cta_from_tail(snippets)
    return TranscriptAnalysis(
        hooks=[hook] if hook else [],
        ctas=ctas,
        video_count=1,
        samples=[_clean(s.text) for s in snippets[:8] if _clean(s.text)],
    )


def analyze_channel(videos: list[VideoData], max_videos: int = 3) -> TranscriptAnalysis:
    """Analiza los ``max_videos`` primeros vídeos del canal (más virales).

    Args:
        videos: Vídeos del canal (deben venir ordenados por vistas desc).
        max_videos: Cuántos analizar (para no abusar del rate-limit).

    Returns:
        Análisis agregado con hooks, CTAs y duración media del hook.
    """
    analysis = TranscriptAnalysis()
    for video in videos[:max_videos]:
        single = analyze_video(video.video_id)
        if single is None:
            continue
        analysis.hooks.extend(single.hooks)
        analysis.ctas.extend(single.ctas)
        analysis.video_count += 1
    analysis.hooks = list(dict.fromkeys(h for h in analysis.hooks if h))
    analysis.ctas = list(dict.fromkeys(c for c in analysis.ctas if c))
    return analysis


def hook_template(topic: str, analysis: TranscriptAnalysis | None) -> str:
    """Texto del gancho: referencia real del patrón o plantilla con tu tema."""
    if analysis and analysis.hooks:
        reference = analysis.hooks[0]
        return (
            f"Gancho (patrón): «{reference}» — "
            f"traducción: «{_topic_hook(topic)}»"
        )
    return _topic_hook(topic)


def _topic_hook(topic: str) -> str:
    return f"Abre fuerte: «{topic}» en los primeros 5 segundos"
