"""Detecta los **tramos** de la canción y elige los *mejores momentos*.

Como la letra no trae marcas de sección fiables (los ficheros usan ``[Chorus]``
como anotación de producción y el parser las descarta), los tramos se deducen
de la propia letra: un tramo **repetido** es un estribillo; el resto, versos.
Es una heurística, pero es determinista, funciona igual con LRC que con texto
plano y no inventa secciones que la canción no tiene.

El **mejor momento** es el tramo que más se repite y más suena (estribillo):
de ahí sale el corte vertical de promoción. Si no hay repeticiones
(canciones sin estribillo), manda la energía medida.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from youber.musicvideo.lexicon import normalize
from youber.musicvideo.models import Highlight, LyricScene, SectionSpan, SongSection
from youber.sync.timestamps import LyricsDocument, clean_lyric_line

#: Proporción mínima de líneas repetidas para considerar un tramo estribillo.
CHORUS_REPEAT_RATIO = 0.6

#: Duración máxima de un tramo de borde para poder ser intro/outro.
EDGE_MAX_SECONDS = 20.0

#: Pesos del score de un tramo (repetición + energía).
REPETITION_WEIGHT = 0.6
ENERGY_WEIGHT = 0.4

#: Bonus por papel del tramo: el estribillo es el gancho aunque no se repita
#: (canciones through-composed con la sección marcada en el fichero de letra).
KIND_BONUS: dict[SongSection, float] = {
    SongSection.CHORUS: 0.35,
    SongSection.PRE_CHORUS: 0.12,
}

#: Repeticiones que saturan la parte de repetición del score.
MAX_REPETITION = 4

#: Umbral de puntuación relativa para sumar un tramo vecino a un momento.
NEIGHBOUR_RATIO = 0.6

#: Separación mínima entre dos momentos para no solaparse (segundos).
HIGHLIGHT_GAP = 5.0


def line_repetition(scenes: Sequence[LyricScene]) -> dict[str, int]:
    """Cuántas veces aparece cada línea (normalizada) en la canción."""
    return dict(Counter(normalize(scene.text) for scene in scenes))


def score_section(section: SectionSpan) -> float:
    """Puntuación de un tramo: repetición (60 %), energía (40 %) y papel.

    El estribillo suma un bonus: hay canciones donde no se repite al pie de la
    letra pero quien la escribió lo marcó como ``[Chorus]`` — ese es el gancho.
    """
    repetition = min(section.repetition, MAX_REPETITION) / MAX_REPETITION
    energy = section.energy if section.energy is not None else 0.5
    bonus = KIND_BONUS.get(section.kind, 0.0)
    return round(REPETITION_WEIGHT * repetition + ENERGY_WEIGHT * energy + bonus, 4)


def _runs(scenes: Sequence[LyricScene], repeated: Sequence[bool]) -> list[list[int]]:
    """Grupos de escenas contiguas con el mismo carácter (repetida o no)."""
    groups: list[list[int]] = []
    for index, is_repeated in enumerate(repeated):
        if groups and repeated[groups[-1][-1]] == is_repeated:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def _energy_of(scenes: Sequence[LyricScene], indexes: Sequence[int]) -> float | None:
    """Energía media de las escenas del tramo (``None`` si no se midió)."""
    values: list[float] = []
    for index in indexes:
        energy = scenes[index].energy
        if energy is not None:
            values.append(energy)
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def detect_sections(scenes: Sequence[LyricScene]) -> list[SectionSpan]:
    """Reparte la canción en tramos (intro/verso/estribillo/outro).

    Un tramo es **estribillo** cuando al menos
    :data:`CHORUS_REPEAT_RATIO` de sus líneas se cantan más de una vez; el
    resto son versos. El primer y el último tramo pasan a intro/outro si son
    cortos. La repetición de un estribillo es cuántas veces se canta su línea
    más repetida.
    """
    if not scenes:
        return []
    counts = line_repetition(scenes)
    normalized = [normalize(scene.text) for scene in scenes]
    repeated = [counts[text] > 1 for text in normalized]

    sections: list[SectionSpan] = []
    for group in _runs(scenes, repeated):
        lines = [normalized[i] for i in group]
        repeat_ratio = sum(1 for text in lines if counts[text] > 1) / len(lines)
        is_chorus = repeat_ratio >= CHORUS_REPEAT_RATIO
        repetition = max((counts[text] for text in lines), default=1) if is_chorus else 1
        sections.append(
            SectionSpan(
                kind=SongSection.CHORUS if is_chorus else SongSection.VERSE,
                start=scenes[group[0]].start,
                end=scenes[group[-1]].end,
                lines=lines,
                repetition=repetition,
                energy=_energy_of(scenes, group),
            )
        )

    # Bordes: el primer y el último tramo pasan a intro/outro si son cortos y
    # no son ya estribillos (un estribillo corto sigue siendo estribillo).
    if len(sections) >= 2:
        first = sections[0]
        if first.kind == SongSection.VERSE and first.duration <= EDGE_MAX_SECONDS:
            sections[0] = first.model_copy(update={"kind": SongSection.INTRO})
        last = sections[-1]
        if last.kind == SongSection.VERSE and last.duration <= EDGE_MAX_SECONDS:
            sections[-1] = last.model_copy(update={"kind": SongSection.OUTRO})
    return sections


def _build_window(
    sections: Sequence[SectionSpan],
    start_index: int,
    *,
    target: float,
    min_seconds: float,
    max_seconds: float,
) -> tuple[int, int]:
    """Ventana de tramos contiguos alrededor del tramo ``start_index``.

    Crece hacia el vecino de más puntuación mientras merezca la pena (su score
    es al menos :data:`NEIGHBOUR_RATIO` del mejor) y quepa; si la ventana aún
    no llega al mínimo, se estira con cualquier vecino. Devuelve ``(lo, hi)``
    inclusive.
    """
    scores = [score_section(section) for section in sections]
    best = scores[start_index]
    lo = hi = start_index
    total = sections[start_index].duration

    def higher_neighbour() -> int | None:
        candidates = [index for index in (lo - 1, hi + 1) if 0 <= index < len(sections)]
        if not candidates:
            return None
        return max(candidates, key=lambda index: (scores[index], -index))

    while True:
        index = higher_neighbour()
        if index is None:
            break
        candidate = sections[index]
        if total + candidate.duration > max_seconds:
            break
        if total >= target and scores[index] < best * NEIGHBOUR_RATIO:
            break
        if total >= min_seconds and scores[index] < best * NEIGHBOUR_RATIO:
            break
        if index < lo:
            lo = index
        else:
            hi = index
        total += candidate.duration

    # Aún por debajo del mínimo: estira con el vecino que sea (aunque no destaque).
    while total < min_seconds:
        index = higher_neighbour()
        if index is None:
            break
        candidate = sections[index]
        if total + candidate.duration > max_seconds:
            break
        if index < lo:
            lo = index
        else:
            hi = index
        total += candidate.duration
    return lo, hi


def _reason(section: SectionSpan, score: float) -> str:
    """Motivo legible de la elección de un momento."""
    energy = f", energía {section.energy:.2f}" if section.energy is not None else ""
    if section.kind == SongSection.CHORUS:
        repeat = f" repetido ×{section.repetition}" if section.repetition > 1 else ""
        return f"estribillo{repeat}{energy} (score {score:.2f})"
    if section.kind == SongSection.PRE_CHORUS:
        return f"pre-estribillo{energy} (score {score:.2f})"
    return f"tramo de mayor energía ({section.kind.value}{energy}, score {score:.2f})"


def _clamp_window(
    start: float, end: float, *, target: float, min_seconds: float, max_seconds: float
) -> tuple[float, float]:
    """Recorta la ventana a ``[min_seconds, max_seconds]`` alrededor de ``start``."""
    duration = end - start
    if duration > max_seconds:
        return start, start + max_seconds
    if duration < min_seconds:
        return start, min(start + min_seconds, target)
    return start, end


def find_highlights(
    sections: Sequence[SectionSpan],
    *,
    target: float = 45.0,
    min_seconds: float = 20.0,
    max_seconds: float = 60.0,
    max_highlights: int = 2,
) -> list[Highlight]:
    """Elige los mejores momentos de la canción (el corto sale del primero).

    Los tramos se ordenan por :func:`score_section`; de cada uno se crece una
    ventana contigua de hasta ``target`` segundos. Se devuelven como mucho
    ``max_highlights`` momentos que no se solapen (separados por
    :data:`HIGHLIGHT_GAP`).

    Args:
        sections: Tramos detectados.
        target: Duración deseada del corte (segundos).
        min_seconds: Duración mínima del corte.
        max_seconds: Duración máxima del corte.
        max_highlights: Número máximo de momentos a devolver.

    Returns:
        Los mejores momentos, del mejor al peor (vacío si no hay tramos).
    """
    if not sections:
        return []
    scores = [score_section(section) for section in sections]
    ranked = sorted(range(len(sections)), key=lambda index: (-scores[index], -sections[index].duration))

    highlights: list[Highlight] = []
    for index in ranked:
        if len(highlights) >= max_highlights:
            break
        section = sections[index]
        lo, hi = _build_window(
            sections, index, target=target, min_seconds=min_seconds, max_seconds=max_seconds
        )
        start, end = sections[lo].start, sections[hi].end
        if any(
            not (end <= chosen.start - HIGHLIGHT_GAP or start >= chosen.end + HIGHLIGHT_GAP)
            for chosen in highlights
        ):
            continue
        start, end = _clamp_window(
            start, end, target=target, min_seconds=min_seconds, max_seconds=max_seconds
        )
        highlights.append(
            Highlight(
                start=round(start, 3),
                end=round(end, 3),
                reason=_reason(section, scores[index]),
                section=section.kind,
                score=scores[index],
                repetition=section.repetition,
                energy=section.energy,
            )
        )
    return highlights


# ---------------------------------------------------------------------------
# Marcas de sección del fichero de letra
# ---------------------------------------------------------------------------

#: Marca de sección: una línea que es solo ``[algo]`` (``[Chorus]``, ``[Verse 1]``).
_MARKER = re.compile(r"^\s*\[(?P<label>[^\]]+)\]\s*$")

#: Palabras de la etiqueta que identifican el papel del tramo.
_OUTRO_WORDS = frozenset({"outro", "ending", "finale", "coda"})
_BRIDGE_WORDS = frozenset({"bridge", "breakdown", "interlude"})


def _kind_from_label(label: str) -> SongSection:
    """Papel de un tramo a partir de su etiqueta (``[Chorus | unstable]``)."""
    words = set(normalize(label).split())
    if not words:
        return SongSection.UNKNOWN
    if "chorus" in words:
        return SongSection.PRE_CHORUS if "pre" in words else SongSection.CHORUS
    if words & _BRIDGE_WORDS:
        return SongSection.BRIDGE
    if "intro" in words:
        return SongSection.INTRO
    if words & _OUTRO_WORDS:
        return SongSection.OUTRO
    if "verse" in words:
        return SongSection.VERSE
    return SongSection.UNKNOWN


def parse_section_markers(text: str) -> list[tuple[str | None, str]]:
    """Empareja cada línea de letra con la **sección vigente** según las marcas.

    Las marcas (``[Verse 1]``, ``[Chorus | unstable]``) son anotaciones de
    producción que el parser normal descarta; aquí sí se usan: son la
    estructura real de la canción escrita por quien la compuso.

    Returns:
        Lista de ``(etiqueta_de_sección_o_None, línea)`` en orden.
    """
    pairs: list[tuple[str | None, str]] = []
    current: str | None = None
    for raw in text.splitlines():
        match = _MARKER.match(raw)
        if match:
            current = match.group("label").strip()
            continue
        cleaned = clean_lyric_line(raw)
        if cleaned is not None:
            pairs.append((current, cleaned))
    return pairs


def sections_from_markers(
    document: LyricsDocument, text: str, *, duration: float | None = None
) -> list[SectionSpan]:
    """Tramos a partir de las **marcas de sección** del fichero de letra.

    Devuelve ``[]`` cuando la letra no trae marcas o no cuadra con las líneas
    temporizadas (entonces el director usa la heurística por repetición).

    Args:
        document: Letra (con o sin tiempos).
        text: Texto crudo del fichero de letra (con las marcas).
        duration: Duración de la canción (para cerrar el último tramo).

    Returns:
        Los tramos con papel, tiempos y repetición (la energía se rellena luego).
    """
    pairs = parse_section_markers(text)
    timed = [line for line in document.lines if line.text.strip()]
    if not pairs or len(pairs) != len(timed):
        return []
    total = duration or document.duration
    counts = Counter(normalize(line.text) for line in timed)

    spans: list[SectionSpan] = []
    index = 0
    while index < len(pairs):
        label = pairs[index][0]
        start_index = index
        while index < len(pairs) and pairs[index][0] == label:
            index += 1
        end_index = index - 1
        kind = _kind_from_label(label) if label else SongSection.UNKNOWN
        if kind == SongSection.UNKNOWN:
            continue
        lines = [normalize(timed[i].text) for i in range(start_index, end_index + 1)]
        start = timed[start_index].start
        if end_index + 1 < len(timed):
            end = timed[end_index + 1].start
        else:
            end = total if total else timed[end_index].start + 2.0
        spans.append(
            SectionSpan(
                kind=kind,
                start=round(start, 3),
                end=round(max(end, start + 0.1), 3),
                lines=lines,
                repetition=max((counts[line] for line in lines), default=1),
            )
        )
    return spans
