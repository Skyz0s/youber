"""El **director**: convierte la letra de la canción en la dirección del vídeo.

Une las piezas de :mod:`youber.musicvideo` en un :class:`MusicVideoPlan`:

1. resuelve los tiempos de cada línea (marcas reales, o reparto sobre la
   duración si la letra es texto plano);
2. convierte cada línea en una escena cuyo plano sale **de la línea**
   (:mod:`youber.musicvideo.lexicon`);
3. detecta los tramos y elige los mejores momentos
   (:mod:`youber.musicvideo.sections`).

De ahí salen las dos líneas de producción, ya como objetos del motor visual:
:func:`plan_to_shot_plan` (los planos que genera y monta el motor) y
:func:`plan_to_script` (el guion con el texto de cada línea para quemar en
pantalla). La duración de la pieza es la de la canción, no una media de canal.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from youber.music.models import Mood
from youber.musicvideo.lexicon import beat_from_line, keywords_from_line, normalize
from youber.musicvideo.models import (
    Highlight,
    LyricScene,
    MusicVideoError,
    MusicVideoPlan,
    SongSection,
)
from youber.musicvideo.sections import detect_sections, find_highlights, line_repetition
from youber.script.models import Scene, SceneType, Script
from youber.sync.timestamps import LyricsDocument
from youber.video.models import TextPosition, TransitionType
from youber.visuals.beats import compose_prompt
from youber.visuals.models import (
    DEFAULT_MOTION_CYCLE,
    STYLE_SUFFIXES,
    Aspect,
    Shot,
    ShotPlan,
    VisualStyle,
)
from youber.visuals.prompts import MOOD_HINTS
from youber.visuals.selector import section_energy

#: Segundos por línea cuando la letra no trae tiempos ni hay duración.
DEFAULT_SECONDS_PER_LINE = 4.0

#: Duración mínima de una escena; por debajo, la línea se funde con la siguiente.
MIN_LINE_SECONDS = 2.0

#: Duración por defecto del corte vertical (segundos).
DEFAULT_SHORT_SECONDS = 45.0

#: Tramo de canción → papel de la escena en el guion del montaje.
_SECTION_SCENE: dict[SongSection, SceneType] = {
    SongSection.INTRO: SceneType.INTRO,
    SongSection.CHORUS: SceneType.CLIMAX,
    SongSection.OUTRO: SceneType.CTA,
}


def _entry_text(document: LyricsDocument) -> list[tuple[float | None, float | None, str]]:
    """Líneas no vacías del documento como ``(start, end, texto)``."""
    return [
        (line.start, line.end, line.text.strip())
        for line in document.lines
        if line.text.strip()
    ]


def _resolve_timings(
    document: LyricsDocument,
    duration: float | None,
    seconds_per_line: float,
) -> tuple[list[tuple[str, float, float]], float, bool]:
    """Resuelve ``(texto, inicio, fin)`` de cada línea y la duración total.

    Con marcas de tiempo reales se usan; sin ellas, se reparten las líneas a
    partes iguales sobre la duración (que entonces es obligatoria o se estima).

    Raises:
        MusicVideoError: si la letra no tiene líneas.
    """
    entries = _entry_text(document)
    if not entries:
        raise MusicVideoError("La letra no tiene líneas que dirigir")
    count = len(entries)
    timed = document.timed

    if not timed:
        total = duration if (duration and duration > 0) else count * seconds_per_line
        step = total / count
        even = [(text, i * step, (i + 1) * step) for i, (_, _, text) in enumerate(entries)]
        return even, total, False

    starts = [max(0.0, start or 0.0) for start, _, _ in entries]
    if duration is None or duration <= 0:
        gaps = [b - a for a, b in zip(starts, starts[1:], strict=False) if b > a]
        step = statistics.median(gaps) if gaps else seconds_per_line
        duration = max(starts[-1] + step, seconds_per_line)
    spans: list[tuple[str, float, float]] = []
    for index, (_, explicit_end, text) in enumerate(entries):
        next_start = starts[index + 1] if index + 1 < count else duration
        end = next_start
        if explicit_end is not None and starts[index] < explicit_end <= next_start:
            end = explicit_end
        spans.append((text, starts[index], max(end, starts[index])))
    return spans, duration, True


def _merge_short(
    spans: Sequence[tuple[str, float, float]], min_seconds: float
) -> list[tuple[str, float, float]]:
    """Funde líneas demasiado cortas con la siguiente (nadie dura 0,3 s).

    Un plano por línea solo tiene sentido si la línea dura lo suficiente para
    verse; las muy cortas se leen juntas en el mismo plano.
    """
    merged: list[tuple[str, float, float]] = []
    text: str | None = None
    start = end = 0.0
    for item, item_start, item_end in spans:
        if text is None:
            text, start, end = item, item_start, item_end
            continue
        if end - start < min_seconds:
            text = f"{text} {item}".strip()
            end = item_end
        else:
            merged.append((text, start, end))
            text, start, end = item, item_start, item_end
    if text is not None:
        if merged and end - start < min_seconds:
            previous = merged[-1]
            merged[-1] = (f"{previous[0]} {text}".strip(), previous[1], end)
        else:
            merged.append((text, start, end))
    return merged


def _infer_profile(text: str) -> tuple[Mood | None, str]:
    """Ánimo y sentimiento de la letra con el léxico de canciones (offline)."""
    from youber.music.lyrics_analyzer import LyricsAnalyzer

    analysis = LyricsAnalyzer().analyze_lyrics(text)
    moods = analysis.moods()
    return (moods[0] if moods else None), analysis.sentiment


def _energy_at(
    energies: Sequence[float] | None, start: float, end: float, window: float
) -> float | None:
    """Energía medida del tramo ``[start, end)`` (``None`` si no hay perfil)."""
    if not energies:
        return None
    return section_energy(energies, start, max(0.0, end - start), window=window)


def direct_song(
    document: LyricsDocument,
    *,
    title: str = "",
    artist: str | None = None,
    duration: float | None = None,
    energies: Sequence[float] | None = None,
    energy_window: float = 1.0,
    mood: Mood | None = None,
    sentiment: str | None = None,
    infer_profile: bool = True,
    min_line_seconds: float = MIN_LINE_SECONDS,
    seconds_per_line: float = DEFAULT_SECONDS_PER_LINE,
    short_seconds: float = DEFAULT_SHORT_SECONDS,
    min_short_seconds: float = 20.0,
    max_short_seconds: float = 60.0,
) -> MusicVideoPlan:
    """Dirige el videoclip de una canción a partir de su letra.

    Args:
        document: Letra (con o sin marcas de tiempo).
        title: Título de la canción.
        artist: Intérprete (si se conoce).
        duration: Duración de la canción (segundos); si falta y la letra tiene
            tiempos, se estima con la mediana entre líneas.
        energies: Perfil de energía de la canción (RMS por ventana); alimenta
            el estilo por tramo y la elección de los mejores momentos.
        energy_window: Duración de cada ventana del perfil (segundos).
        mood: Ánimo global (si falta y ``infer_profile``, se infiere).
        sentiment: Sentimiento global (si falta y ``infer_profile``, se infiere).
        infer_profile: Infiere ánimo/sentimiento de la letra si no se aportan.
        min_line_seconds: Duración mínima de una escena antes de fundirla.
        seconds_per_line: Segundos por línea sin tiempos ni duración.
        short_seconds: Duración deseada del corte vertical.
        min_short_seconds: Duración mínima del corte.
        max_short_seconds: Duración máxima del corte.

    Returns:
        El :class:`MusicVideoPlan` con escenas, tramos y mejores momentos.

    Raises:
        MusicVideoError: si la letra no tiene líneas.
    """
    spans, total, timed = _resolve_timings(document, duration, seconds_per_line)
    spans = _merge_short(spans, min_line_seconds)

    if (mood is None or sentiment is None) and infer_profile:
        inferred_mood, inferred_sentiment = _infer_profile(document.plain_text)
        mood = mood or inferred_mood
        sentiment = sentiment or inferred_sentiment
    sentiment = sentiment or "neutral"

    # Escenas «en borrador» para medir repetición y detectar tramos; el tramo
    # decide el movimiento de cámara, así que el plano se recalcula después.
    draft = [
        LyricScene(
            index=index,
            text=text,
            start=round(start, 3),
            end=round(end, 3),
            energy=_energy_at(energies, start, end, energy_window),
        )
        for index, (text, start, end) in enumerate(spans)
    ]
    sections = detect_sections(draft)
    counts = line_repetition(draft)
    section_of: dict[int, tuple[SongSection, int]] = {}
    for section_index, section in enumerate(sections):
        for scene in draft:
            if scene.start >= section.start - 1e-6 and scene.end <= section.end + 1e-6:
                section_of[scene.index] = (section.kind, section_index)

    scenes: list[LyricScene] = []
    for scene in draft:
        kind, section_index = section_of.get(scene.index, (SongSection.UNKNOWN, -1))
        scenes.append(
            scene.model_copy(
                update={
                    "section": kind,
                    "section_index": section_index,
                    "hook": counts.get(normalize(scene.text), 1) > 1,
                    "keywords": keywords_from_line(scene.text),
                    "beat": beat_from_line(
                        scene.text, index=scene.index, section=kind, mood=mood
                    ),
                }
            )
        )

    highlights = find_highlights(
        sections,
        target=short_seconds,
        min_seconds=min_short_seconds,
        max_seconds=max_short_seconds,
    )
    return MusicVideoPlan(
        title=title,
        artist=artist,
        duration=round(total, 3),
        timed=timed,
        scenes=scenes,
        sections=sections,
        highlights=highlights,
        mood=mood,
        sentiment=sentiment,
    )


def plan_to_shot_plan(
    plan: MusicVideoPlan,
    *,
    scenes: Sequence[LyricScene] | None = None,
    aspect: Aspect = Aspect.LANDSCAPE,
    style: VisualStyle = VisualStyle.CINEMATIC,
    transition: float = 0.8,
    fps: int = 30,
    motion_offset: int = 0,
    include_topic: bool = False,
) -> ShotPlan:
    """Materializa un :class:`ShotPlan` (un plano por escena) para el motor visual.

    Cada línea genera su plano con el encuadre que salió de ella; el prompt no
    lleva el texto cantado (lo dibuja FFmpeg encima, no el modelo).

    Args:
        plan: Dirección del videoclip.
        scenes: Escenas a incluir (por defecto, todas). El corte vertical pasa
            solo las del mejor momento.
        aspect: Formato (``16:9`` para el videoclip, ``9:16`` para el corto).
        style: Estilo visual de los planos.
        transition: Duración del fundido entre planos (segundos).
        fps: Fotogramas por segundo.
        motion_offset: Desplazamiento del ciclo de movimientos.
        include_topic: Añadir el título como tema del prompt (coherencia global).

    Returns:
        El plan de planos listo para generar y montar.
    """
    chosen = list(scenes if scenes is not None else plan.scenes)
    mood_value = plan.mood.value if plan.mood is not None else None
    plan_out = ShotPlan(
        topic=plan.title or "videoclip",
        style=style,
        aspect=aspect,
        fps=fps,
        transition=transition,
        music_mood=mood_value,
        motion_offset=motion_offset % len(DEFAULT_MOTION_CYCLE),
    )
    topic = plan.title if include_topic else None
    for index, scene in enumerate(chosen):
        prompt = compose_prompt(
            scene.beat,
            topic=topic,
            keywords=scene.keywords[:4],
            atmosphere=MOOD_HINTS.get(mood_value) if mood_value else None,
            style_suffix=STYLE_SUFFIXES[style],
        )
        plan_out.shots.append(
            Shot(
                index=index,
                prompt=prompt,
                motion=DEFAULT_MOTION_CYCLE[(index + motion_offset) % len(DEFAULT_MOTION_CYCLE)],
                duration=max(scene.duration, MIN_LINE_SECONDS),
                scene_index=index,
                beat=scene.beat.describe(),
            )
        )
    return plan_out


def plan_to_script(plan: MusicVideoPlan, *, scenes: Sequence[LyricScene] | None = None) -> Script:
    """Guion del montaje: el texto de cada línea se quema en pantalla.

    Cada :class:`LyricScene` se vuelve una escena cuyo texto es la línea de la
    letra (lo que el espectador lee), con la duración real de la canción y una
    transición acorde al tramo.

    Args:
        plan: Dirección del videoclip.
        scenes: Escenas a incluir (por defecto, todas).

    Returns:
        El :class:`~youber.script.models.Script` para ``youber.script.builder``.
    """
    chosen = list(scenes if scenes is not None else plan.scenes)
    script_scenes: list[Scene] = []
    for scene in chosen:
        kind = _SECTION_SCENE.get(scene.section, SceneType.CONTENT)
        script_scenes.append(
            Scene(
                type=kind,
                title=scene.section.value,
                duration=max(scene.duration, MIN_LINE_SECONDS),
                text=scene.text,
                position=(
                    TextPosition.CENTER
                    if scene.section in (SongSection.CHORUS, SongSection.INTRO, SongSection.OUTRO)
                    else TextPosition.BOTTOM_CENTER
                ),
                transition=(
                    TransitionType.FADE
                    if scene.section in (SongSection.INTRO, SongSection.OUTRO)
                    else TransitionType.CROSSFADE
                ),
                keywords=scene.keywords,
                keywords_from_content=True,
            )
        )
    return Script(
        topic=plan.title or "videoclip",
        source_channel=None,
        total_duration=round(sum(scene.duration for scene in script_scenes), 3),
        scenes=script_scenes,
        music_mood=plan.mood,
    )


def best_highlight(plan: MusicVideoPlan) -> Highlight | None:
    """El mejor momento de la canción (o ``None`` si no se pudo elegir)."""
    return plan.highlights[0] if plan.highlights else None
