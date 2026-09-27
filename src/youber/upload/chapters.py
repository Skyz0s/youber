"""Capítulos para la descripción de YouTube.

YouTube detecta los capítulos si la descripción empieza con una marca de
tiempo ``00:00`` seguida de al menos **tres** capítulos, y cada uno dura
**10 s o más**; si no se cumple, los ignora y se queda el texto suelto. Aquí
se construyen (y se validan) a partir del guion o del plan de planos, para
que la descripción los lleve bien formados en vez de a ojo.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Mínimo de capítulos que exige YouTube (incluido el ``00:00``).
MIN_CHAPTERS = 3

#: Duración mínima de cada capítulo en segundos (requisito de YouTube).
MIN_CHAPTER_SECONDS = 10.0


def format_timestamp(seconds: float) -> str:
    """Formatea un instante como ``MM:SS`` (o ``H:MM:SS`` si pasa de una hora)."""
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _clean_title(title: str) -> str:
    """Normaliza el título de un capítulo a una sola línea corta."""
    clean = " ".join((title or "").split())
    if len(clean) > 80:
        clean = clean[:77].rstrip() + "…"
    return clean


def build_chapters(
    markers: Sequence[tuple[float, str]],
    *,
    min_chapters: int = MIN_CHAPTERS,
    min_length: float = MIN_CHAPTER_SECONDS,
) -> str:
    """Construye el bloque de capítulos para la descripción de YouTube.

    Descarta títulos vacíos, ordena por tiempo y garantiza que el primero
    empieza en ``00:00``. Devuelve cadena vacía si no se cumplen los
    requisitos de YouTube (menos de ``min_chapters`` capítulos o algún
    capítulo de menos de ``min_length`` segundos), de modo que el llamante
    pueda simplemente omitir el bloque.

    Args:
        markers: Pares ``(segundo, título)``.
        min_chapters: Mínimo de capítulos válidos.
        min_length: Duración mínima de cada capítulo (segundos).

    Returns:
        El texto de capítulos (``"{ts} {título}"`` por línea) o ``""``.
    """
    entries = [(float(t), _clean_title(title)) for t, title in markers if _clean_title(title)]
    if not entries:
        return ""
    entries.sort(key=lambda item: item[0])
    entries[0] = (0.0, entries[0][1])  # YouTube exige el 00:00 inicial

    if len(entries) < min_chapters:
        return ""

    lines: list[str] = []
    for index, (start, title) in enumerate(entries):
        end = entries[index + 1][0] if index + 1 < len(entries) else None
        if end is not None and end - start < min_length:
            return ""
        lines.append(f"{format_timestamp(start)} {title}")
    return "\n".join(lines)


def chapters_from_script(script: object, **kwargs: object) -> str:
    """Capítulos a partir de un :class:`~youber.script.models.Script`.

    Usa el ``timeline()`` del guion y el título de cada escena.
    """
    timeline = getattr(script, "timeline", None)
    scenes = getattr(script, "scenes", [])
    if not callable(timeline):
        return ""
    starts = [start for start, _ in timeline()]
    markers = [
        (start, getattr(scene, "title", "") or "")
        for start, scene in zip(starts, scenes, strict=False)
    ]
    return build_chapters(markers, **kwargs)  # type: ignore[arg-type]


def chapters_from_plan(plan: object, **kwargs: object) -> str:
    """Capítulos a partir de un plan de planos de :mod:`youber.visuals`.

    Cada plano lleva su instante de inicio (rejilla de cortes) y su prompt;
    se usa el principio del prompt como título legible.
    """
    shots = getattr(plan, "shots", [])
    starts = [getattr(plan, "shot_start", None)]
    markers: list[tuple[float, str]] = []
    start = 0.0
    for shot in shots:
        title = _clean_title(str(getattr(shot, "prompt", "")))
        markers.append((start, title[:60] if title else ""))
        start += float(getattr(shot, "duration", 0.0) or 0.0)
    del starts
    return build_chapters(markers, **kwargs)  # type: ignore[arg-type]
