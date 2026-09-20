"""Tests de los cortes al pulso (`youber.visuals.tempo` + plan de planos).

La fase del beat, la rejilla y el reparto de duraciones son puros (sin FFmpeg);
la integración mide un tren de clics real y comprueba que los cortes del plan
caen sobre el beat. Nada toca la red.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from youber.script.models import Scene, SceneType
from youber.video.models import TextPosition
from youber.visuals.generator import StubGenerator
from youber.visuals.prompts import beat_durations, build_shot_plan, fit_durations, plan_durations
from youber.visuals.render import render_visuals
from youber.visuals.tempo import (
    BeatGrid,
    attack_envelope,
    beat_offset,
    detect_grid,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

#: Rejilla de manual: 120 BPM (0.5 s por pulso) con el primer beat en 0.25 s.
GRID_120 = BeatGrid(bpm=120.0, offset=0.25, confidence=0.6, phase_strength=0.4, seconds=60.0)


def _click_samples(offset: float, period: float, *, seconds: float, sample_rate: int = 8000):
    """Tren de clics: un golpe en ``offset + k * period``."""
    import array

    samples = array.array("h", [0] * int(round(seconds * sample_rate)))
    time = offset
    while time < seconds:
        start = int(round(time * sample_rate))
        for index in range(start, min(start + 40, len(samples))):
            samples[index] = 20000 if (index - start) % 2 == 0 else -20000
        time += period
    return samples


# ---------------------------------------------------------------------------
# Fase del pulso y rejilla
# ---------------------------------------------------------------------------


def test_beat_offset_encuentra_la_fase():
    samples = _click_samples(0.3, 0.5, seconds=20.0)
    envelope = attack_envelope(samples, sample_rate=8000)
    offset, strength = beat_offset(envelope, rate=8000 / 128, interval=0.5)
    # El pico cae en el fotograma en el que el clic entra en la ventana: el
    # offset medido va algo por delante del golpe real.
    assert offset <= 0.3
    assert abs(offset - 0.3) <= 0.06
    assert strength > 0.0


def test_beat_offset_sin_tempo():
    assert beat_offset([1.0, 0.0, 1.0], rate=100.0, interval=0.0) == (0.0, 0.0)
    assert beat_offset([], rate=100.0, interval=0.5) == (0.0, 0.0)


def test_beat_grid_rejilla():
    assert GRID_120.interval == pytest.approx(0.5)
    assert GRID_120.detected and GRID_120.reliable()
    assert GRID_120.next_beat(0.3) == pytest.approx(0.75)
    assert GRID_120.next_beat(0.25) == pytest.approx(0.25)
    assert GRID_120.nearest_beat(0.6) == pytest.approx(0.75)
    assert GRID_120.beat_times(start=0.0, end=2.0) == [0.25, 0.75, 1.25, 1.75]


def test_beat_grid_shifted_recoloca_la_fase():
    shifted = GRID_120.shifted(1.25)
    # 0.25 - 1.25 = -1.00 → +2 * 0.5 = 0.0: los beats vuelven a caer donde toca.
    assert shifted.offset == pytest.approx(0.0)
    assert shifted.bpm == GRID_120.bpm
    assert GRID_120.shifted(0.0).offset == GRID_120.offset


def test_beat_grid_vacia_no_se_fia():
    empty = BeatGrid()
    assert not empty.detected and not empty.reliable()
    assert empty.beat_times() == []
    assert empty.shifted(1.0).offset == 0.0


def test_beat_grid_confianza_baja_no_es_fiable():
    weak = BeatGrid(bpm=120.0, offset=0.0, confidence=0.1, phase_strength=0.5)
    assert not weak.reliable()
    faint = BeatGrid(bpm=120.0, offset=0.0, confidence=0.5, phase_strength=0.02)
    assert not faint.reliable()


# ---------------------------------------------------------------------------
# Duraciones con los cortes sobre el pulso
# ---------------------------------------------------------------------------


def test_beat_durations_cortes_en_el_pulso():
    durations = beat_durations(30.0, 5, 0.5, GRID_120)
    assert durations is not None
    plan = build_shot_plan(
        "tema", duration=30.0, shots=5, transition=0.5, beat_grid=GRID_120
    )
    assert plan.beat_aligned
    assert plan.total_duration == pytest.approx(30.0, abs=1e-6)
    # Los cortes (arranque de cada plano) caen en múltiplos del pulso.
    for index in range(1, len(plan.shots)):
        start = plan.shot_start(index)
        assert start == pytest.approx(GRID_120.nearest_beat(start), abs=1e-6)
    assert durations == [shot.duration for shot in plan.shots]


def test_beat_durations_devuelve_none_si_el_ultimo_no_cabe():
    # 8 BPM de 60 con 3 planos en 5 s: el último quedaría por debajo del mínimo.
    grid = BeatGrid(bpm=60.0, offset=0.0, confidence=0.6, phase_strength=0.4)
    assert beat_durations(5.0, 3, 0.8, grid) is None
    # Sin rejilla caen las duraciones uniformes (que sí caben).
    assert plan_durations(5.0, 3, 0.8) == fit_durations(5.0, 3, 0.8)
    assert plan_durations(5.0, 3, 0.8, grid) == fit_durations(5.0, 3, 0.8)


def test_beat_durations_sin_rejilla_o_sin_tempo():
    assert beat_durations(30.0, 5, 0.5, BeatGrid()) is None


def test_build_shot_plan_sin_rejilla_no_marca_beat():
    plan = build_shot_plan("tema", duration=30.0, shots=5, transition=0.5)
    assert plan.beat_bpm is None and not plan.beat_aligned
    # Reparto uniforme: 30 s + 4 fundidos → 6.4 s por plano menos el solape.
    assert plan.shot_start(1) == pytest.approx(5.9, abs=1e-6)


def test_build_shot_plan_con_escenas_alinea_los_cortes():
    scenes = [
        Scene(
            type=SceneType.HOOK,
            title="Gancho",
            duration=10.0,
            text="Empieza aquí",
            position=TextPosition.CENTER,
        ),
        Scene(type=SceneType.CONTENT, title="Desarrollo", duration=10.0, text="El detalle"),
        Scene(type=SceneType.CTA, title="Cierre", duration=10.0, text="Suscríbete"),
    ]
    plan = build_shot_plan(
        "tema", scenes, duration=30.0, shots=6, transition=0.5, beat_grid=GRID_120
    )
    assert plan.beat_bpm == 120.0 and plan.beat_offset == 0.25
    assert plan.beat_aligned
    assert plan.total_duration == pytest.approx(30.0, abs=1e-6)
    for index in range(1, len(plan.shots)):
        start = plan.shot_start(index)
        assert start == pytest.approx(GRID_120.nearest_beat(start), abs=1e-3)


def test_cli_visuals_tiene_no_beat():
    from youber.visuals.cli import build_parser

    args = build_parser().parse_args(["--topic", "t", "--song", "x.wav"])
    assert args.no_beat is False
    assert build_parser().parse_args(["--topic", "t", "--song", "x.wav", "--no-beat"]).no_beat


# ---------------------------------------------------------------------------
# Integración: clics reales y render con cortes al pulso
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_detect_grid_sobre_clics_reales(tmp_path: Path):
    from youber.audio._ffmpeg import run_command

    song = tmp_path / "clicks.wav"
    asyncio.run(
        run_command(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "aevalsrc=0.8*sin(2*PI*1000*t)*between(mod(t\\,0.5)\\,0\\,0.03):s=22050:d=20",
                str(song),
            ]
        )
    )
    grid = asyncio.run(detect_grid(song))
    assert grid.detected and grid.reliable()
    assert grid.bpm == pytest.approx(120.0, abs=4.0)
    assert 0.0 <= grid.offset <= grid.interval


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_render_visuals_alinea_los_cortes(tmp_path: Path):
    from youber.audio._ffmpeg import probe_duration, run_command

    song = tmp_path / "clicks.wav"
    asyncio.run(
        run_command(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "aevalsrc=0.8*sin(2*PI*1000*t)*between(mod(t\\,0.5)\\,0\\,0.03):s=22050:d=12",
                str(song),
            ]
        )
    )
    grid = asyncio.run(detect_grid(song))
    result = asyncio.run(
        render_visuals(
            topic="prueba al beat",
            output=tmp_path / "out.mp4",
            song=song,
            shots=3,
            fps=15,
            generator=StubGenerator(),
            beat_grid=grid,
        )
    )
    assert result.plan.beat_aligned
    assert result.plan.beat_bpm == pytest.approx(120.0, abs=4.0)
    assert result.plan.total_duration == pytest.approx(12.0, abs=0.05)
    # Cada corte cae en el beat de la rejilla medida (¡no necesariamente 0,5 s
    # exactos: la medición dio 120,2 BPM!).
    for index in range(1, len(result.plan.shots)):
        start = result.plan.shot_start(index)
        assert start == pytest.approx(grid.nearest_beat(start), abs=0.02)
    duration = asyncio.run(probe_duration(result.video))
    assert abs(duration - 12.0) < 0.5
