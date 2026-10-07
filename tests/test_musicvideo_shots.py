"""Tests del guion repartido en planos (``youber.musicvideo.shots``).

Todo offline y determinista: se construye un plan a mano (tramos + escenas) y se
comprueba que el reparto **cubre la canción**, que cada plano cae en su tramo y
que el motivo solo aparece donde la canción **se repite de verdad**.
"""

from __future__ import annotations

import pytest

from youber.musicvideo.cli import build_parser
from youber.musicvideo.models import (
    LyricScene,
    MusicVideoError,
    MusicVideoPlan,
    SectionSpan,
    SongSection,
)
from youber.musicvideo.shots import (
    DEFAULT_SLOTS,
    MAX_MOTIF_RUN,
    allocate_slots,
    build_shot_slots,
    distinct_count,
    section_signature,
    slot_coverage,
    slots_to_shot_plan,
)
from youber.visuals.models import VisualStyle
from youber.visuals.tempo import BeatGrid

DURATION = 140.0


def _plan() -> MusicVideoPlan:
    """Plan con dos versos distintos y dos estribillos idénticos.

    Es el caso que rompía el piloto: dos tramos del mismo tipo (`verse`) con
    **letra distinta** no se pueden reutilizar, pero los dos estribillos sí.
    """
    sections = [
        SectionSpan(kind=SongSection.INTRO, start=0.0, end=20.0, lines=["uno"], repetition=1),
        SectionSpan(kind=SongSection.VERSE, start=20.0, end=50.0, lines=["dos", "tres"], repetition=1),
        SectionSpan(
            kind=SongSection.CHORUS, start=50.0, end=80.0, lines=["gancho", "gancho"], repetition=2
        ),
        SectionSpan(
            kind=SongSection.VERSE, start=80.0, end=110.0, lines=["cuatro", "cinco"], repetition=1
        ),
        SectionSpan(
            kind=SongSection.CHORUS, start=110.0, end=140.0, lines=["gancho", "gancho"], repetition=2
        ),
    ]
    rows = [
        (0.0, 10.0, "uno"),
        (10.0, 20.0, "uno"),
        (20.0, 35.0, "dos"),
        (35.0, 50.0, "tres"),
        (50.0, 65.0, "gancho"),
        (65.0, 80.0, "gancho"),
        (80.0, 95.0, "cuatro"),
        (95.0, 110.0, "cinco"),
        (110.0, 125.0, "gancho"),
        (125.0, 140.0, "gancho"),
    ]
    section_of = {
        0: (SongSection.INTRO, 0),
        1: (SongSection.INTRO, 0),
        2: (SongSection.VERSE, 1),
        3: (SongSection.VERSE, 1),
        4: (SongSection.CHORUS, 2),
        5: (SongSection.CHORUS, 2),
        6: (SongSection.VERSE, 3),
        7: (SongSection.VERSE, 3),
        8: (SongSection.CHORUS, 4),
        9: (SongSection.CHORUS, 4),
    }
    scenes = []
    for index, (start, end, text) in enumerate(rows):
        kind, section_index = section_of[index]
        scenes.append(
            LyricScene(
                index=index,
                text=text,
                start=start,
                end=end,
                section=kind,
                section_index=section_index,
                keywords=[text],
            )
        )
    return MusicVideoPlan(title="prueba", duration=DURATION, timed=True, scenes=scenes, sections=sections)


# --- reparto de huecos ------------------------------------------------------


def test_allocate_slots_reparte_proporcional_y_minimo_uno() -> None:
    assert allocate_slots([30.0, 30.0, 30.0, 30.0], 40) == [10, 10, 10, 10]
    assert sum(allocate_slots([20.0, 30.0, 30.0, 30.0, 30.0], 40)) == 40
    # con menos huecos que tramos, cada tramo sigue teniendo el suyo
    assert allocate_slots([1.0, 1.0, 1.0], 2) == [1, 1, 1]


def test_allocate_slots_sin_tramos_falla() -> None:
    with pytest.raises(ValueError):
        allocate_slots([], 10)


def test_build_shot_slots_cubre_la_cancion_entera() -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 40)
    report = slot_coverage(slots, plan)
    assert report.slots == 40
    assert report.gaps == []
    assert report.overlaps == []
    assert report.missing_scenes == []
    assert report.stray_slots == []
    assert report.bad_repeats == []
    assert report.covered == pytest.approx(DURATION, abs=1e-3)
    assert report.ok
    assert slots[0].start == 0.0
    assert slots[-1].end == pytest.approx(DURATION)


def test_cada_plano_cae_en_su_tramo() -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 17)
    for slot in slots:
        scene = plan.scenes[slot.scene_index]
        assert scene.section_index == slot.section_index
        span = plan.sections[slot.section_index]
        assert slot.start >= span.start - 1e-6
        assert slot.end <= span.end + 1e-6


def test_los_huecos_no_se_solapan_y_son_crecientes() -> None:
    slots = build_shot_slots(_plan(), 23)
    for previous, current in zip(slots[:-1], slots[1:], strict=True):
        assert current.start == pytest.approx(previous.end)
        assert current.duration >= 2.0


# --- motivo: solo donde la canción se repite --------------------------------


def test_el_estribillo_reutiliza_los_planos_del_primero() -> None:
    """El segundo estribillo usa las imágenes del primero (motivo de sección)."""
    plan = _plan()
    slots = build_shot_slots(plan, 40)
    chorus_1 = [slot for slot in slots if slot.section_index == 2]
    chorus_2 = [slot for slot in slots if slot.section_index == 4]
    assert chorus_1 and chorus_2
    first = {slot.index for slot in chorus_1}
    assert all(slot.repeat_of in first for slot in chorus_2)
    assert any(slot.generated for slot in chorus_1)


def test_nunca_se_reutiliza_un_plano_de_otro_tramo() -> None:
    """El fallo del piloto: «verse» 2 y 3 son el mismo tipo pero no la misma letra.

    La única reutilización cruzada legítima es entre tramos con la **letra
    idéntica** (el estribillo que vuelve); dentro de un tramo, por la línea.
    """
    plan = _plan()
    slots = build_shot_slots(plan, 40)
    for slot in slots:
        if slot.repeat_of is None:
            continue
        source = slots[slot.repeat_of]
        same_lyrics = section_signature(plan.sections[source.section_index]) == section_signature(
            plan.sections[slot.section_index]
        )
        assert same_lyrics or source.section_index == slot.section_index
    verse_1 = {slot.index for slot in slots if slot.section_index == 1}
    assert not any(slot.repeat_of in verse_1 for slot in slots if slot.section_index == 3)


def test_sin_motivo_todos_los_planos_se_generan() -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 40, motif=False)
    assert all(slot.repeat_of is None for slot in slots)
    assert distinct_count(slots) == 40
    assert slot_coverage(slots, plan).ok


def test_una_linea_repetida_comparte_plano_por_bloques() -> None:
    """La misma línea repetida comparte imagen, pero en bloques cortos.

    Es el caso de «to be like that.» al final de la canción: no pide un plano
    por hueco, pero tampoco deja la pantalla congelada medio minuto.
    """
    plan = _plan()
    slots = [slot for slot in build_shot_slots(plan, 40) if slot.section_index == 3]
    assert slots
    run = 0
    longest = 0
    for slot in slots:
        run = run + 1 if slot.repeat_of is not None else 0
        longest = max(longest, run)
    assert any(slot.repeat_of is not None for slot in slots)
    assert longest <= MAX_MOTIF_RUN - 1


def test_distinct_count_cuenta_los_que_hay_que_generar() -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 40)
    report = slot_coverage(slots, plan)
    assert report.generated == distinct_count(slots)
    assert report.generated + report.repeated == 40
    assert 0 < report.generated < 40


# --- cortes al pulso --------------------------------------------------------


def test_los_cortes_caen_en_el_pulso() -> None:
    grid = BeatGrid(bpm=120.0, offset=0.0, confidence=0.9, phase_strength=0.8)
    plan = _plan()
    slots = build_shot_slots(plan, 40, grid=grid)
    for slot in slots[1:-1]:
        beats = slot.start / grid.interval
        assert beats == pytest.approx(round(beats), abs=1e-6)
    assert slot_coverage(slots, plan).gaps == []


def test_sin_pulso_los_cortes_salen_de_las_lineas() -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 10)
    assert any(slot.start in {scene.start for scene in plan.scenes} for slot in slots)


def test_demasiados_planos_para_la_cancion() -> None:
    with pytest.raises(ValueError):
        build_shot_slots(_plan(), 200)


# --- errores y plan de planos ----------------------------------------------


def test_plan_sin_escenas_falla() -> None:
    empty = MusicVideoPlan(title="vacio", duration=10.0)
    with pytest.raises(MusicVideoError):
        build_shot_slots(empty, 4)


def test_slots_to_shot_plan_un_plano_por_hueco() -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 12)
    shot_plan = slots_to_shot_plan(plan, slots, style=VisualStyle.DARK, include_topic=True)
    assert len(shot_plan.shots) == 12
    assert shot_plan.topic == "prueba"
    for shot, slot in zip(shot_plan.shots, slots, strict=True):
        assert shot.prompt
        assert shot.duration == pytest.approx(max(slot.duration, 2.0))
        assert shot.scene_index == slot.scene_index


def test_cli_musicvideo_tiene_shots() -> None:
    parser = build_parser()
    args = parser.parse_args(["shots", "cancion.mp3", "--slots", "12", "--json"])
    assert args.command == "shots"
    assert args.slots == 12
    assert args.json is True
    assert args.no_motif is False
    assert parser.parse_args(["shots", "cancion.mp3"]).slots == DEFAULT_SLOTS
