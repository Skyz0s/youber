"""El **guion** repartido en planos: cada plano con su ventana y su tramo.

Por qué existe
--------------
El primer videoclip (piloto) tenía planos escritos **por sección de la letra**,
pero el montaje los reciclaba en bucle: cada plano acababa sonando sobre versos
que no le tocaban y el conjunto parecía «un vídeo random con música encima». La
causa era aritmética: pocos planos para muchos huecos, y ningún vínculo entre
plano y tramo a la hora de cortar.

Aquí se cierra el agujero. La dirección (:class:`MusicVideoPlan`) se reparte en
``count`` **huecos** (:class:`ShotSlot`) que cubren la canción entera —desde el
segundo 0 hasta la duración— sin solapes ni agujeros, cada uno dentro de **su**
tramo, y con el **motivo** explícito: cuando un tramo se repite (el estribillo),
sus planos **reutilizan** los del primer paso, alineados por posición relativa,
de modo que la repetición se lee como intención y no como reciclaje.

``distinct_count`` dice cuántos planos hay que generar de verdad (los que no son
motivo); :func:`slot_coverage` comprueba que el reparto cubre la canción sin
huecos, sin solapes y sin planos fuera de su tramo, y es lo que exige el test.

El motivo tiene **dos reglas** (y ninguna más, para no volver al reciclaje):

1. tramos con la **letra idéntica** (el estribillo) comparten planos, alineados
   por posición relativa;
2. dentro de un tramo, las **líneas que se repiten** comparten plano en bloques
   de ``max_run`` huecos (más seguidos sería un plano congelado, no un motivo).
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from youber.musicvideo.lexicon import normalize
from youber.musicvideo.models import (
    LyricScene,
    MusicVideoError,
    MusicVideoPlan,
    SectionSpan,
    SongSection,
)
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
from youber.visuals.tempo import BeatGrid

#: Planos por defecto de un videoclip completo (≈ 6,5 s por plano a 115 BPM).
DEFAULT_SLOTS = 40

#: Duración mínima de un hueco; por debajo, el corte se nota nervioso.
MIN_SLOT_SECONDS = 2.0

#: Huecos seguidos que puede durar un motivo sin que parezca un plano congelado.
MAX_MOTIF_RUN = 2

#: Tolerancia con la que se comparan tiempos (evita el ruido de los redondeos).
EPSILON = 1e-6


class ShotSlot(BaseModel):
    """Un hueco de montaje: la ventana de canción que cubre **un** plano.

    Attributes:
        index: Posición en el montaje (0-based).
        start: Segundo en el que empieza la ventana.
        end: Segundo en el que termina.
        section: Tramo al que pertenece (un hueco nunca cruza dos tramos).
        section_index: Índice del tramo en el plan (``-1`` si no se pudo).
        scene_index: Escena (línea) **dominante** del hueco: la que ocupa más
            tiempo dentro de la ventana. De ella salen el texto y el encuadre.
        scene_indexes: Todas las escenas que toca la ventana (para la cobertura).
        text: Línea dominante, tal cual se canta.
        keywords: Términos de esa línea (B-roll/prompt).
        energy: Energía medida del tramo, si la hay.
        hook: ``True`` si el tramo es gancho (se repite en la canción).
        repeat_of: Índice del hueco cuyo plano se reutiliza (motivo del
            estribillo), o ``None`` si este hueco necesita un plano nuevo.
    """

    index: int = Field(ge=0)
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    section: SongSection = SongSection.UNKNOWN
    section_index: int = Field(default=-1, ge=-1)
    scene_index: int = Field(default=0, ge=0)
    scene_indexes: list[int] = Field(default_factory=list)
    text: str = ""
    keywords: list[str] = Field(default_factory=list)
    energy: float | None = Field(default=None, ge=0.0, le=1.0)
    hook: bool = False
    repeat_of: int | None = None

    @property
    def duration(self) -> float:
        """Duración de la ventana (segundos)."""
        return max(0.0, self.end - self.start)

    @property
    def generated(self) -> bool:
        """``True`` si el hueco necesita un plano nuevo (no es motivo)."""
        return self.repeat_of is None


class SlotCoverage(BaseModel):
    """Informe de cobertura del reparto de planos (lo que exige el test).

    Attributes:
        slots: Número de huecos.
        duration: Duración de la canción (segundos).
        covered: Segundos cubiertos por los huecos.
        gaps: Tramos de canción sin ningún plano ``[inicio, fin]``.
        overlaps: Tramo donde dos huecos se pisan ``[inicio, fin]``.
        scenes_total: Escenas de la letra.
        scenes_covered: Escenas dentro de algún hueco.
        missing_scenes: Índices de escena que se quedaron fuera.
        stray_slots: Huecos que tocan escenas de otro tramo (corte desalineado).
        bad_repeats: Huecos cuyo ``repeat_of`` no apunta a su mismo tramo.
        per_section: Huecos por tramo (clave: valor del :class:`SongSection`).
        generated: Planos que hay que generar de verdad.
        repeated: Huecos que reutilizan un plano (motivo).
    """

    slots: int = 0
    duration: float = 0.0
    covered: float = 0.0
    gaps: list[list[float]] = Field(default_factory=list)
    overlaps: list[list[float]] = Field(default_factory=list)
    scenes_total: int = 0
    scenes_covered: int = 0
    missing_scenes: list[int] = Field(default_factory=list)
    stray_slots: list[int] = Field(default_factory=list)
    bad_repeats: list[int] = Field(default_factory=list)
    per_section: dict[str, int] = Field(default_factory=dict)
    generated: int = 0
    repeated: int = 0

    @property
    def ok(self) -> bool:
        """``True`` si cubre la canción sin huecos, solapes ni planos huérfanos."""
        return (
            not self.gaps
            and not self.overlaps
            and not self.missing_scenes
            and not self.stray_slots
            and not self.bad_repeats
            and abs(self.covered - self.duration) < 1e-3
        )


def _section_groups(plan: MusicVideoPlan) -> list[list[LyricScene]]:
    """Escenas contiguas agrupadas por tramo (una lista por tramo)."""
    groups: list[list[LyricScene]] = []
    for scene in plan.scenes:
        if groups and groups[-1][0].section_index == scene.section_index:
            groups[-1].append(scene)
        else:
            groups.append([scene])
    return groups


def allocate_slots(durations: Sequence[float], count: int) -> list[int]:
    """Reparte ``count`` huecos entre tramos, proporcional a su duración.

    El reparto es determinista (resto mayor, empate por duración) y **cada tramo
    recibe al menos uno**; si ``count`` venía por debajo del número de tramos se
    eleva, porque dejar un tramo sin plano es exactamente el fallo que se está
    corrigiendo.

    Args:
        durations: Duración de cada tramo (segundos).
        count: Huecos deseados en total.

    Returns:
        Huecos que le tocan a cada tramo (misma longitud que ``durations``).

    Raises:
        ValueError: si no hay tramos.
    """
    if not durations:
        raise ValueError("No hay tramos que repartir")
    total_slots = max(int(count), len(durations))
    base = [1] * len(durations)
    remaining = total_slots - len(durations)
    if remaining <= 0:
        return base
    total = sum(durations) or 1.0
    quotas = [duration / total * remaining for duration in durations]
    floors = [int(quota) for quota in quotas]
    for index, value in enumerate(floors):
        base[index] += value
    rest = remaining - sum(floors)
    order = sorted(
        range(len(durations)),
        key=lambda index: (quotas[index] - floors[index], durations[index], -index),
        reverse=True,
    )
    for index in order[:rest]:
        base[index] += 1
    return base


def _split_section(
    scenes: Sequence[LyricScene], count: int
) -> list[tuple[float, float, list[int]]]:
    """Parte las escenas de un tramo en ``count`` ventanas contiguas.

    Reparte **por tiempo**, no por número de líneas: una línea larga puede
    cubrir dos huecos y dos cortas compartir uno.

    Returns:
        Lista de ``(inicio, fin, índices de escena)``.
    """
    spans: list[tuple[float, float, list[int]]] = [
        (scene.start, scene.end, [scene.index]) for scene in scenes
    ]
    while len(spans) < count:
        widest = max(range(len(spans)), key=lambda i: spans[i][1] - spans[i][0])
        start, end, indexes = spans[widest]
        middle = round((start + end) / 2, 3)
        spans[widest] = (start, middle, indexes)
        spans.insert(widest + 1, (middle, end, indexes))
    while len(spans) > count:
        shortest = min(range(len(spans)), key=lambda i: spans[i][1] - spans[i][0])
        neighbour = shortest - 1 if shortest > 0 else shortest + 1
        first, second = sorted((shortest, neighbour))
        indexes = sorted({*spans[first][2], *spans[second][2]})
        spans[first : second + 1] = [(spans[first][0], spans[second][1], indexes)]
    return spans


def _snap_starts(
    starts: Sequence[float],
    total: float,
    *,
    grid: BeatGrid | None = None,
    minimum: float = MIN_SLOT_SECONDS,
) -> list[float]:
    """Ajusta los cortes al pulso, manteniendo el orden y la duración mínima.

    Los extremos son fijos (``0`` y la duración de la canción): la canción se
    cubre entera, instrumentales incluidos.

    Args:
        starts: Fronteras deseadas (la primera debe ser 0).
        total: Duración total de la canción.
        grid: Rejilla de pulsos medida (opcional).
        minimum: Duración mínima de cada hueco.

    Returns:
        Las fronteras ajustadas (``len(starts)`` valores, la última se fuerza a
        ``total``).

    Raises:
        ValueError: si no caben tantos huecos con la duración mínima.
    """
    count = len(starts)
    if count * minimum > total + EPSILON:
        raise ValueError(
            f"No caben {count} planos en {total:g} s con un mínimo de {minimum:g} s"
        )
    out = list(starts)
    out[0] = 0.0
    out[-1] = total
    for index in range(1, count - 1):
        value = out[index]
        if grid is not None and grid.detected:
            value = grid.nearest_beat(value)
        out[index] = min(max(value, 0.0), total)
    for index in range(1, count - 1):
        out[index] = max(out[index], out[index - 1] + minimum)
    for index in range(count - 2, 0, -1):
        out[index] = min(out[index], out[index + 1] - minimum)
    return [round(value, 3) for value in out]


def _dominant_scene(
    indexes: Sequence[int], scenes: dict[int, LyricScene], start: float, end: float
) -> LyricScene:
    """Escena que ocupa más tiempo dentro de ``[start, end)``."""
    best: LyricScene | None = None
    best_overlap = -1.0
    for index in indexes:
        scene = scenes[index]
        overlap = max(0.0, min(end, scene.end) - max(start, scene.start))
        if overlap > best_overlap:
            best, best_overlap = scene, overlap
    if best is None:  # pragma: no cover - indexes nunca va vacío
        raise MusicVideoError("Un hueco sin escenas")
    return best


def section_signature(section: SectionSpan) -> tuple[str, ...]:
    """Huella de un tramo: sus líneas normalizadas, en orden.

    Dos tramos con la misma huella son **el mismo texto cantado** (el estribillo
    que vuelve); dos versos distintos la tienen distinta aunque los dos sean
    ``verse``. Es lo que decide si un tramo puede reutilizar planos.
    """
    return tuple(line for line in section.lines if line)


def _apply_section_motif(slots: list[ShotSlot], plan: MusicVideoPlan) -> None:
    """Regla 1: tramos con la letra idéntica comparten planos.

    El primer paso de cada tramo es la referencia; los siguientes apuntan al
    plano de la **misma posición relativa**, así la misma línea canta siempre
    con la misma imagen. Un tramo con huella vacía (o sin identificar) no se
    toca: no se puede saber si se repite.
    """
    bases: dict[tuple[str, ...], list[int]] = {}
    for section_index in dict.fromkeys(slot.section_index for slot in slots):
        indexes = [slot.index for slot in slots if slot.section_index == section_index]
        if not 0 <= section_index < len(plan.sections):
            continue
        signature = section_signature(plan.sections[section_index])
        if not signature:
            continue
        for slot_index in indexes:
            slots[slot_index].hook = True
        if signature not in bases:
            bases[signature] = indexes
            continue
        base = bases[signature]
        for position, slot_index in enumerate(indexes):
            slots[slot_index].repeat_of = base[
                min(len(base) - 1, position * len(base) // len(indexes))
            ]


def _apply_line_motif(slots: list[ShotSlot], *, max_run: int = MAX_MOTIF_RUN) -> None:
    """Regla 2: las líneas que se repiten dentro de un tramo comparten plano.

    Se agrupan por ``(tramo, línea)``; la cabeza de cada bloque de ``max_run``
    huecos genera el plano y el resto lo reutiliza. Así «to be like that.»
    (que se canta en bucle al final) no pide nueve planos distintos, pero
    tampoco deja la pantalla congelada un minuto.
    """
    heads: dict[tuple[int, str], int] = {}
    seen: dict[tuple[int, str], int] = {}
    for slot in slots:
        if slot.repeat_of is not None or not slot.text:
            continue
        key = (slot.section_index, normalize(slot.text))
        count = seen.get(key, 0) + 1
        seen[key] = count
        if count % max_run == 1:
            heads[key] = slot.index
        else:
            slot.repeat_of = heads[key]


def build_shot_slots(
    plan: MusicVideoPlan,
    count: int = DEFAULT_SLOTS,
    *,
    grid: BeatGrid | None = None,
    motif: bool = True,
) -> list[ShotSlot]:
    """Reparte la canción en ``count`` huecos atados a su tramo.

    Args:
        plan: Dirección del videoclip (escenas + tramos + duración).
        count: Huecos deseados. Se eleva al número de tramos si hace falta.
        grid: Rejilla de pulsos medida; si se da, los cortes caen en el pulso.
        motif: Reutilizar los planos de los tramos repetidos (estribillo).

    Returns:
        Los huecos en orden de montaje.

    Raises:
        MusicVideoError: si la letra no tiene escenas.
        ValueError: si ``count`` no cabe en la canción con la duración mínima.
    """
    if not plan.scenes:
        raise MusicVideoError("La letra no tiene líneas: no hay nada que montar")
    groups = _section_groups(plan)
    durations = [group[-1].end - group[0].start for group in groups]
    quotas = allocate_slots(durations, count)

    windows: list[tuple[float, float, list[int], int]] = []
    for group_index, (group, quota) in enumerate(zip(groups, quotas, strict=True)):
        for start, end, indexes in _split_section(group, quota):
            windows.append((start, end, indexes, group_index))

    starts = _snap_starts(
        [0.0, *(window[0] for window in windows[1:]), plan.duration],
        plan.duration,
        grid=grid,
    )
    scenes = {scene.index: scene for scene in plan.scenes}
    slots: list[ShotSlot] = []
    for index in range(len(windows)):
        start, end = starts[index], starts[index + 1]
        _raw_start, _raw_end, indexes, group_index = windows[index]
        dominant = _dominant_scene(indexes, scenes, start, end)
        head = groups[group_index][0]
        slots.append(
            ShotSlot(
                index=index,
                start=start,
                end=end,
                section=head.section,
                section_index=head.section_index,
                scene_index=dominant.index,
                scene_indexes=list(indexes),
                text=dominant.text,
                keywords=list(dominant.keywords),
                energy=head.energy,
                hook=any(scenes[item].hook for item in indexes),
            )
        )
    if motif:
        _apply_section_motif(slots, plan)
        _apply_line_motif(slots)
    return slots


def distinct_count(slots: Sequence[ShotSlot]) -> int:
    """Cuántos planos hay que **generar** (los que no reutilizan otro)."""
    return sum(1 for slot in slots if slot.generated)


def slot_coverage(slots: Sequence[ShotSlot], plan: MusicVideoPlan) -> SlotCoverage:
    """Comprueba que el reparto cubre la canción y respeta los tramos.

    Args:
        slots: Huecos generados con :func:`build_shot_slots`.
        plan: Dirección del videoclip.

    Returns:
        El informe :class:`SlotCoverage` (``ok`` resume si está bien).
    """
    report = SlotCoverage(slots=len(slots), duration=plan.duration)
    if not slots:
        report.missing_scenes = [scene.index for scene in plan.scenes]
        return report
    ordered = sorted(slots, key=lambda slot: slot.start)
    covered = 0.0
    cursor = 0.0
    for slot in ordered:
        if slot.start > cursor + 1e-3:
            report.gaps.append([round(cursor, 3), round(slot.start, 3)])
        elif slot.start < cursor - 1e-3:
            report.overlaps.append([round(slot.start, 3), round(min(cursor, slot.end), 3)])
        covered += slot.duration
        cursor = max(cursor, slot.end)
    if cursor < plan.duration - 1e-3:
        report.gaps.append([round(cursor, 3), round(plan.duration, 3)])
    report.covered = round(covered, 3)

    seen: set[int] = set()
    for slot in slots:
        seen.update(slot.scene_indexes)
    report.scenes_total = len(plan.scenes)
    report.scenes_covered = len(seen)
    report.missing_scenes = [
        scene.index for scene in plan.scenes if scene.index not in seen
    ]
    for slot in slots:
        for index in slot.scene_indexes:
            scene = plan.scenes[index] if index < len(plan.scenes) else None
            if scene is not None and scene.section_index != slot.section_index:
                report.stray_slots.append(slot.index)
                break
        if slot.repeat_of is not None:
            source = slots[slot.repeat_of] if slot.repeat_of < len(slots) else None
            if source is None or source.section != slot.section:
                report.bad_repeats.append(slot.index)
    for slot in slots:
        key = slot.section.value
        report.per_section[key] = report.per_section.get(key, 0) + 1
    report.generated = distinct_count(slots)
    report.repeated = len(slots) - report.generated
    return report


def slots_to_shot_plan(
    plan: MusicVideoPlan,
    slots: Sequence[ShotSlot],
    *,
    aspect: Aspect = Aspect.LANDSCAPE,
    style: VisualStyle = VisualStyle.CINEMATIC,
    transition: float = 0.0,
    fps: int = 30,
    motion_offset: int = 0,
    include_topic: bool = False,
) -> ShotPlan:
    """Convierte los huecos en el :class:`ShotPlan` que consume el motor visual.

    Cada hueco es un plano: el encuadre sale de su **línea dominante** (la
    escena que se está cantando en esa ventana), no del orden de la lista.

    Args:
        plan: Dirección del videoclip.
        slots: Huecos de :func:`build_shot_slots`.
        aspect: Formato (``16:9`` el videoclip, ``9:16`` el corto).
        style: Estilo visual de los planos.
        transition: Duración del fundido entre planos (segundos).
        fps: Fotogramas por segundo.
        motion_offset: Desplazamiento del ciclo de movimientos.
        include_topic: Añadir el título como tema del prompt.

    Returns:
        El plan de planos listo para generar y montar.
    """
    mood_value = plan.mood.value if plan.mood is not None else None
    topic = plan.title if include_topic else None
    plan_out = ShotPlan(
        topic=plan.title or "videoclip",
        style=style,
        aspect=aspect,
        fps=fps,
        transition=transition,
        music_mood=mood_value,
        motion_offset=motion_offset % len(DEFAULT_MOTION_CYCLE),
    )
    scenes = {scene.index: scene for scene in plan.scenes}
    for slot in slots:
        scene = scenes[slot.scene_index]
        prompt = compose_prompt(
            scene.beat,
            topic=topic,
            keywords=slot.keywords[:4],
            atmosphere=MOOD_HINTS.get(mood_value) if mood_value else None,
            style_suffix=STYLE_SUFFIXES[style],
        )
        plan_out.shots.append(
            Shot(
                index=slot.index,
                prompt=prompt,
                motion=DEFAULT_MOTION_CYCLE[
                    (slot.index + motion_offset) % len(DEFAULT_MOTION_CYCLE)
                ],
                duration=max(slot.duration, MIN_SLOT_SECONDS),
                scene_index=slot.scene_index,
                beat=scene.beat.describe(),
            )
        )
    return plan_out
