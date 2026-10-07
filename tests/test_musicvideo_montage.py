"""Tests del montaje guiado por el guion (``youber.musicvideo.montage``).

Todo offline: se comprueba el **plan de segmentos** (frames exactos, motivo
resuelto) y los comandos de FFmpeg, sin ejecutar ni FFmpeg ni la GPU.
"""

from __future__ import annotations

import pytest

from youber.musicvideo.models import (
    LyricScene,
    MusicVideoError,
    MusicVideoPlan,
    SectionSpan,
    SongSection,
)
from youber.musicvideo.montage import (
    boundary_frames,
    concat_file_text,
    mux_command,
    resolve_origins,
    slot_segments,
    total_frames,
    trim_command,
)
from youber.musicvideo.shots import DEFAULT_SLOTS, build_shot_slots, distinct_count


def _plan() -> MusicVideoPlan:
    """Plan pequeño con dos versos distintos y dos estribillos idénticos."""
    sections = [
        SectionSpan(kind=SongSection.VERSE, start=0.0, end=40.0, lines=["uno"], repetition=1),
        SectionSpan(kind=SongSection.CHORUS, start=40.0, end=80.0, lines=["gancho"], repetition=2),
        SectionSpan(kind=SongSection.CHORUS, start=80.0, end=120.0, lines=["gancho"], repetition=2),
    ]
    rows = [
        (0.0, 20.0, "uno", 0),
        (20.0, 40.0, "dos", 0),
        (40.0, 60.0, "gancho", 1),
        (60.0, 80.0, "gancho", 1),
        (80.0, 100.0, "gancho", 2),
        (100.0, 120.0, "gancho", 2),
    ]
    kinds = [SongSection.VERSE, SongSection.CHORUS, SongSection.CHORUS]
    scenes = [
        LyricScene(
            index=index,
            text=text,
            start=start,
            end=end,
            section=kinds[section_index],
            section_index=section_index,
        )
        for index, (start, end, text, section_index) in enumerate(rows)
    ]
    return MusicVideoPlan(
        title="prueba", duration=120.0, timed=True, scenes=scenes, sections=sections
    )

FPS = 24


def _clips(slots, tmp_path) -> dict[int, object]:
    """Un clip falso por cada hueco que hay que generar (los motivos no llevan)."""
    return {
        slot.index: tmp_path / f"clip{slot.index:02d}.mp4"
        for slot in slots
        if slot.repeat_of is None
    }


def test_boundary_frames_cuentan_toda_la_cancion(tmp_path) -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 23)
    marks = boundary_frames(slots, fps=FPS)
    assert marks[0] == 0
    assert marks[-1] == round(plan.duration * FPS)
    assert marks == sorted(marks)


def test_los_segmentos_suman_el_total_sin_deriva(tmp_path) -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 40)
    segments = slot_segments(slots, _clips(slots, tmp_path), fps=FPS)
    assert len(segments) == len(slots)
    assert total_frames(segments) == round(plan.duration * FPS)
    # sin deriva: cada frontera cae en un frame (absoluta), no en un acumulado
    cursor = 0
    for segment in segments:
        assert segment.start == pytest.approx(cursor / FPS, abs=1e-3)
        cursor += segment.frames
    assert cursor == round(plan.duration * FPS)


def test_el_motivo_reutiliza_el_clip_del_hueco_original(tmp_path) -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 40)
    clips = _clips(slots, tmp_path)
    segments = slot_segments(slots, clips, fps=FPS)
    origins = resolve_origins(slots)
    repeats = [slot for slot in slots if slot.repeat_of is not None]
    assert repeats
    for slot in repeats:
        segment = segments[slot.index]
        assert origins[slot.index] in clips          # la cadena acaba donde genera
        assert segment.slot_index == origins[slot.index]
        assert segment.clip == clips[origins[slot.index]]


def test_falta_el_clip_de_un_hueco_que_genera(tmp_path) -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 12)
    clips = _clips(slots, tmp_path)
    assert len(clips) == distinct_count(slots)
    clips.pop(0)
    with pytest.raises(MusicVideoError):
        slot_segments(slots, clips, fps=FPS)


def test_sin_huecos_no_hay_montaje() -> None:
    with pytest.raises(MusicVideoError):
        boundary_frames([], fps=FPS)


def test_el_recorte_usa_frames_no_segundos(tmp_path) -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 12)
    segment = slot_segments(slots, _clips(slots, tmp_path), fps=FPS)[3]
    cmd = trim_command(segment, tmp_path / "out.mp4", fps=FPS)
    assert "-frames:v" in cmd
    assert cmd[cmd.index("-frames:v") + 1] == str(segment.frames)
    assert "-t" not in cmd
    assert cmd[cmd.index("-r") + 1] == str(FPS)


def test_el_recorte_respeta_el_frame_de_entrada(tmp_path) -> None:
    plan = _plan()
    slots = build_shot_slots(plan, 12)
    clips = _clips(slots, tmp_path)
    entries = {next(iter(clips)): 5}
    segments = slot_segments(slots, clips, fps=FPS, entry_frames=entries)
    first = segments[0]
    assert first.source_frame == 5
    assert f"{5 / FPS:.6f}" in trim_command(first, tmp_path / "o.mp4", fps=FPS)


def test_fichero_de_concatenacion_y_mux(tmp_path) -> None:
    parts = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    text = concat_file_text(parts)
    assert text.count("file '") == 2
    assert text.endswith("\n")
    cmd = mux_command(tmp_path / "concat.txt", tmp_path / "song.wav", tmp_path / "out.mp4")
    assert "-f" in cmd and "concat" in cmd
    assert "1:a:0" in cmd
    assert cmd[-1].endswith("out.mp4")


def test_el_default_de_planos_es_40() -> None:
    assert DEFAULT_SLOTS == 40
    slots = build_shot_slots(_plan(), DEFAULT_SLOTS)
    assert len(slots) == DEFAULT_SLOTS
