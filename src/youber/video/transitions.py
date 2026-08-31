"""Transiciones entre clips del motor de edición de vídeo de BARF.

Construye las cadenas de filtros de FFmpeg para encadenar los streams de
vídeo (``xfade``) y de audio (``acrossfade``) de los clips de un proyecto,
respetando las transiciones definidas en el :class:`Project`.
"""

from __future__ import annotations

from youber.video.models import Transition, TransitionType
from youber.video.timeline import Timeline

# Mapeo de tipos de transición a nombres del filtro xfade de FFmpeg.
# "crossfade" se implementa con "fade" (fundido cruzado equivalente).
XFADE_NAMES: dict[TransitionType, str] = {
    TransitionType.FADE: "fade",
    TransitionType.CROSSFADE: "fade",
    TransitionType.WIPE: "wipeleft",
    TransitionType.SLIDE: "slideleft",
}


def _transitions_by_index(transitions: list[Transition]) -> dict[int, Transition]:
    """Mapa ``clip_index -> transition`` para consultas rápidas."""
    return {transition.clip_index: transition for transition in transitions}


def video_transition_chain(timeline: Timeline) -> tuple[str, str]:
    """Construye la cadena ``xfade``/``concat`` de vídeo.

    Returns:
        Tupla ``(filter_complex, etiqueta_final)``: el fragmento de
        ``filter_complex`` y la etiqueta del stream de vídeo resultante.
        Si hay un solo clip, el fragmento es vacío y la etiqueta es ``v0``.
    """
    segments = timeline.segments
    if len(segments) <= 1:
        return "", "v0"

    transitions = _transitions_by_index(timeline.transitions)
    parts: list[str] = []
    labels: list[str] = [f"v{i}" for i in range(len(segments))]

    # Duración acumulada del stream combinado (tras restar solapamientos).
    accumulated = segments[0].output_duration
    current_label = labels[0]

    for index in range(1, len(segments)):
        transition = transitions.get(index)
        next_label = f"vx{index}"

        if transition is not None and transition.type != TransitionType.NONE:
            name = XFADE_NAMES[transition.type]
            offset = accumulated - transition.duration
            parts.append(
                f"[{current_label}][{labels[index]}]"
                f"xfade=transition={name}:duration={transition.duration:.3f}:"
                f"offset={offset:.3f}[{next_label}]"
            )
            accumulated = accumulated + segments[index].output_duration - transition.duration
        else:
            parts.append(
                f"[{current_label}][{labels[index]}]"
                f"concat=n=2:v=1:a=0[{next_label}]"
            )
            accumulated += segments[index].output_duration

        current_label = next_label

    return ";".join(parts), current_label


def audio_transition_chain(timeline: Timeline) -> tuple[str, str]:
    """Construye la cadena ``acrossfade``/``concat`` de audio.

    Returns:
        Tupla ``(filter_complex, etiqueta_final)`` del stream de audio.
        Si hay un solo clip, el fragmento es vacío y la etiqueta es ``a0``.
    """
    segments = timeline.segments
    if len(segments) <= 1:
        return "", "a0"

    transitions = _transitions_by_index(timeline.transitions)
    parts: list[str] = []
    labels: list[str] = [f"a{i}" for i in range(len(segments))]
    current_label = labels[0]

    for index in range(1, len(segments)):
        transition = transitions.get(index)
        next_label = f"ax{index}"

        if transition is not None and transition.type != TransitionType.NONE:
            parts.append(
                f"[{current_label}][{labels[index]}]"
                f"acrossfade=d={transition.duration:.3f}[{next_label}]"
            )
        else:
            parts.append(
                f"[{current_label}][{labels[index]}]"
                f"concat=n=2:v=0:a=1[{next_label}]"
            )
        current_label = next_label

    return ";".join(parts), current_label


def expected_duration(timeline: Timeline) -> float:
    """Duración esperada del vídeo final (suma de clips − solapamientos)."""
    return timeline.total_duration


def transition_at(timeline: Timeline, clip_index: int) -> Transition | None:
    """Devuelve la transición que termina en ``clip_index`` (o ``None``)."""
    return _transitions_by_index(timeline.transitions).get(clip_index)
