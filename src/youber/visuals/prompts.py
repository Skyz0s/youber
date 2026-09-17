"""Del guion y el mood a un **plan de planos** con prompts concretos.

Cada plano nace de la escena del guion a la que pertenece: el papel de la
escena (gancho, desarrollo, clímax...) decide el encuadre (*beat*), y el
tema, las palabras clave, el tono y el mood de la canción completan el
prompt. Todo es determinista y offline: mismas entradas ⇒ mismo plan.

Los *beats* son plantillas de encuadre con ``{topic}`` como único hueco; van
en inglés porque es el idioma con el que los modelos de difusión entienden
mejor las descripciones visuales.
"""

from __future__ import annotations

from collections.abc import Sequence

from youber.script.models import Scene, SceneType
from youber.visuals.models import (
    DEFAULT_MOTION_CYCLE,
    STYLE_SUFFIXES,
    Aspect,
    Shot,
    ShotPlan,
    VisualStyle,
)

#: Encuadres por papel de escena (se recorren en ciclo dentro de cada escena).
BEATS_BY_SCENE: dict[SceneType, tuple[str, ...]] = {
    SceneType.HOOK: (
        "wide establishing shot of {topic}, vast landscape at first light",
        "aerial drone view over {topic}, sweeping scale, dramatic clouds",
        "extreme wide shot, lone figure facing {topic}",
    ),
    SceneType.INTRO: (
        "medium shot introducing {topic}, natural light, soft depth of field",
        "observational documentary shot of {topic}, everyday detail",
        "wide shot of {topic} with layered foreground, quiet composition",
    ),
    SceneType.CONTENT: (
        "close up detail of {topic}, intricate texture, shallow focus",
        "macro texture related to {topic}, abstract surfaces, raking light",
        "over the shoulder view of {topic}, context around the frame",
    ),
    SceneType.CLIMAX: (
        "low angle shot, dramatic sky over {topic}, epic scale",
        "silhouette against a blazing horizon, {topic}, backlit haze",
        "high contrast scene of {topic}, storm light, motion in the air",
    ),
    SceneType.CTA: (
        "empty road at sunrise leading towards {topic}, hopeful horizon",
        "light beam through a window, {topic} implied, calm interior",
        "wide serene horizon of {topic}, negative space for a title",
    ),
}

#: Encuadres de reserva (cuando un plano no se puede atar a una escena).
GENERIC_BEATS: tuple[str, ...] = (
    "wide establishing shot of {topic}",
    "close up detail of {topic}",
    "silhouette of a person facing {topic}",
    "low angle shot, dramatic sky over {topic}",
    "abstract macro texture related to {topic}",
    "empty room, light beam, {topic} implied",
)

#: Pistas de iluminación/atmósfera por mood de la música.
MOOD_HINTS: dict[str, str] = {
    "felicidad": "warm golden light, uplifting atmosphere",
    "tristeza": "cold blue tones, rain, melancholic mood",
    "energia": "dynamic lighting, strong movement, high energy",
    "calma": "soft even light, stillness, peaceful atmosphere",
    "misterio": "fog, deep shadows, ambiguous shapes, enigmatic",
    "amor": "intimate warm light, soft skin tones, tender atmosphere",
}

#: Duración mínima de un plano (por debajo de esto el zoompan se nota nervioso).
MIN_SHOT_DURATION = 2.0

#: Objetivo aproximado de segundos por plano cuando no se indica el número.
DEFAULT_SECONDS_PER_SHOT = 16.0

#: Rango sensato de planos por vídeo.
MIN_SHOTS = 4
MAX_SHOTS = 40


def plan_shots_count(duration: float, shots: int | None = None) -> int:
    """Número de planos: el indicado o uno derivado de la duración."""
    if shots is not None:
        return max(1, int(shots))
    suggested = round(max(duration, 1.0) / DEFAULT_SECONDS_PER_SHOT)
    return max(MIN_SHOTS, min(MAX_SHOTS, suggested))


def fit_durations(target: float, count: int, transition: float) -> list[float]:
    """Reparte ``target`` segundos en ``count`` planos con solapamientos.

    ``count`` planos encadenados con transiciones de ``transition`` segundos
    duran ``suma - transition * (count - 1)``: por eso cada plano recibe algo
    más que ``target / count``. El último absorbe el redondeo para que la
    suma cuadre al milisegundo con el objetivo.

    Raises:
        ValueError: si ``target`` no da para ``count`` planos de duración
            mínima (:data:`MIN_SHOT_DURATION`).
    """
    if count < 1:
        raise ValueError("Se necesita al menos un plano")
    usable = target + transition * (count - 1)
    per_shot = usable / count
    if per_shot < MIN_SHOT_DURATION:
        raise ValueError(
            f"No caben {count} planos en {target:g} s "
            f"(saldrían de {per_shot:.2f} s, mínimo {MIN_SHOT_DURATION:g} s)"
        )
    durations = [round(per_shot, 3)] * count
    durations[-1] = round(durations[-1] + (usable - sum(durations)), 3)
    return durations


def scene_shot_counts(
    scenes: Sequence[Scene], total_shots: int
) -> list[int]:
    """Reparte ``total_shots`` planos entre las escenas, proporcional a su duración.

    Cada escena recibe al menos un plano; el resto se reparte por resto mayor
    (determinista: orden estable por duración).
    """
    if not scenes:
        return []
    count = max(len(scenes), total_shots)
    base = [1] * len(scenes)
    remaining = count - len(scenes)
    if remaining <= 0:
        return base
    total = sum(scene.duration for scene in scenes) or 1.0
    quotas = [(scene.duration / total) * remaining for scene in scenes]
    floors = [int(quota) for quota in quotas]
    for index, value in enumerate(floors):
        base[index] += value
    rest = remaining - sum(floors)
    order = sorted(
        range(len(scenes)),
        key=lambda index: (quotas[index] - floors[index], scenes[index].duration),
        reverse=True,
    )
    for index in order[:rest]:
        base[index] += 1
    return base


def shot_prompt(
    beat: str,
    *,
    topic: str,
    style: VisualStyle,
    mood: str | None = None,
    tone: str | None = None,
    keywords: Sequence[str] = (),
) -> str:
    """Compone el prompt de un plano: encuadre + tema + pistas + estilo."""
    parts = [beat.format(topic=topic)]
    if keywords:
        parts.append("featuring " + ", ".join(list(keywords)[:4]))
    if mood and mood in MOOD_HINTS:
        parts.append(MOOD_HINTS[mood])
    if tone:
        parts.append(f"overall tone: {tone}")
    parts.append(STYLE_SUFFIXES[style])
    return ", ".join(part for part in parts if part)


def build_shot_plan(
    topic: str,
    scenes: Sequence[Scene] = (),
    *,
    duration: float,
    aspect: Aspect = Aspect.LANDSCAPE,
    style: VisualStyle = VisualStyle.CINEMATIC,
    mood: str | None = None,
    tone: str | None = None,
    keywords: Sequence[str] = (),
    shots: int | None = None,
    transition: float = 0.8,
    fps: int = 30,
) -> ShotPlan:
    """Construye el plan visual de un vídeo a partir de su guion.

    Args:
        topic: Tema del vídeo (alimenta los prompts).
        scenes: Escenas del guion; reparten los planos y dictan los encuadres.
        duration: Duración objetivo del montaje (segundos).
        aspect: Formato de la pieza.
        style: Estilo visual de los planos.
        mood: Mood de la música (clave de :data:`MOOD_HINTS`).
        tone: Tono narrativo del brief (texto libre, se añade al prompt).
        keywords: Palabras clave (del brief) para enriquecer los prompts.
        shots: Número de planos (por defecto, derivado de la duración).
        transition: Duración del fundido entre planos (segundos).
        fps: Fotogramas por segundo del render.

    Returns:
        El :class:`ShotPlan` con los prompts y las duraciones ya resueltas.
    """
    count = plan_shots_count(duration, shots)
    keywords = list(dict.fromkeys(str(keyword) for keyword in keywords if keyword))

    # Sin escenas: planos genéricos equiespaciados.
    if not scenes:
        durations = fit_durations(duration, count, transition)
        plan = ShotPlan(
            topic=topic,
            style=style,
            aspect=aspect,
            fps=fps,
            transition=transition,
            music_mood=mood,
            keywords=keywords[:8],
        )
        for index, shot_duration in enumerate(durations):
            beat = GENERIC_BEATS[index % len(GENERIC_BEATS)]
            plan.shots.append(
                Shot(
                    index=index,
                    prompt=shot_prompt(
                        beat,
                        topic=topic,
                        style=style,
                        mood=mood,
                        tone=tone,
                        keywords=keywords,
                    ),
                    motion=DEFAULT_MOTION_CYCLE[index % len(DEFAULT_MOTION_CYCLE)],
                    duration=shot_duration,
                    beat=beat,
                )
            )
        return plan

    counts = scene_shot_counts(scenes, count)
    # El reparto puede subir el número de planos (mínimo uno por escena): las
    # duraciones se calculan sobre los planos que de verdad va a haber.
    durations = fit_durations(duration, sum(counts), transition)
    plan = ShotPlan(
        topic=topic,
        style=style,
        aspect=aspect,
        fps=fps,
        transition=transition,
        music_mood=mood,
        keywords=keywords[:8],
    )
    index = 0
    for scene_index, (scene, scene_shots) in enumerate(zip(scenes, counts, strict=True)):
        beats = BEATS_BY_SCENE.get(scene.type, GENERIC_BEATS)
        for beat_index in range(scene_shots):
            beat = beats[beat_index % len(beats)]
            plan.shots.append(
                Shot(
                    index=index,
                    prompt=shot_prompt(
                        beat,
                        topic=topic,
                        style=style,
                        mood=mood,
                        tone=tone,
                        keywords=keywords or scene.keywords,
                    ),
                    motion=DEFAULT_MOTION_CYCLE[index % len(DEFAULT_MOTION_CYCLE)],
                    duration=durations[index],
                    scene_index=scene_index,
                    beat=beat,
                )
            )
            index += 1
    return plan
