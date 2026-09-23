"""Tests del movimiento de cámara al compás (Fase 23).

El ciclo del Ken Burns (zoom/paneo) se mide en **compases medidos**: con la
rejilla de beats de la canción, el movimiento cierra su recorrido cada número
entero de compases, así "respira" al compás en vez de completar un único
barrido a lo largo del plano. Todo es puro salvo la integración con FFmpeg.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from youber.audio._ffmpeg import probe_duration, run_command
from youber.visuals.animate import animate_filter, animate_shot, motion_expressions
from youber.visuals.generator import StubGenerator
from youber.visuals.models import DEFAULT_MOTION_BARS, Motion, ShotPlan, VisualStyle
from youber.visuals.prompts import build_shot_plan
from youber.visuals.render import render_visuals
from youber.visuals.selector import (
    MOTION_BARS_ALLOWED,
    StyleSignals,
    choose_style,
    motion_bars_for,
)
from youber.visuals.tempo import BEATS_PER_BAR, BeatGrid

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

#: Rejilla de manual: 120 BPM → 0.5 s por pulso, 2.0 s por compás (4/4).
GRID_120 = BeatGrid(bpm=120.0, offset=0.25, confidence=0.6, phase_strength=0.4, seconds=60.0)


# ---------------------------------------------------------------------------
# Compases del ciclo
# ---------------------------------------------------------------------------


def test_bar_interval_son_cuatro_pulsos():
    assert BEATS_PER_BAR == 4
    assert GRID_120.interval == pytest.approx(0.5)
    assert GRID_120.bar_interval == pytest.approx(2.0)
    assert BeatGrid().bar_interval == 0.0


def test_cycle_seconds_por_compases():
    assert GRID_120.cycle_seconds(2) == pytest.approx(4.0)
    assert GRID_120.cycle_seconds(4) == pytest.approx(8.0)
    assert GRID_120.cycle_seconds(0) is None
    # Sin pulso no hay ciclo que medir.
    assert BeatGrid().cycle_seconds(4) is None


def test_motion_bars_por_estilo():
    # Vibrant respira rápido (2 compases); dreamy/minimal, despacio (8).
    assert motion_bars_for(VisualStyle.VIBRANT) == 2
    assert motion_bars_for(VisualStyle.CINEMATIC) == DEFAULT_MOTION_BARS == 4
    assert motion_bars_for(VisualStyle.DREAMY) == 8
    assert motion_bars_for(VisualStyle.MINIMAL) == 8
    assert motion_bars_for(VisualStyle.DARK) == 4


def test_motion_bars_la_energia_ajusta_el_ciclo():
    calm = StyleSignals(energy=0.1)
    neutral = StyleSignals(energy=0.5)
    fierce = StyleSignals(energy=0.9)
    assert motion_bars_for(VisualStyle.CINEMATIC, calm) == 8
    assert motion_bars_for(VisualStyle.CINEMATIC, neutral) == 4
    assert motion_bars_for(VisualStyle.CINEMATIC, fierce) == 2
    # Y nunca se sale de las cifras musicales.
    assert motion_bars_for(VisualStyle.DREAMY, calm) in MOTION_BARS_ALLOWED
    assert motion_bars_for(VisualStyle.VIBRANT, fierce) in MOTION_BARS_ALLOWED


def test_choose_style_trae_los_compases_del_ciclo():
    choice = choose_style(
        "auto",
        signals=StyleSignals(energy=0.9, tempo=0.9, valence=0.9, dance=0.8),
        variation_key="tema|16:9|1234",
    )
    assert choice.motion_bars in MOTION_BARS_ALLOWED
    assert choice.motion_bars == motion_bars_for(choice.style, choice.signals)
    # El estilo pedido a mano también se lleva sus compases.
    explicit = choose_style("dreamy", signals=StyleSignals(energy=0.5))
    assert explicit.motion_bars == 8


# ---------------------------------------------------------------------------
# El plan guarda el ciclo medido
# ---------------------------------------------------------------------------


def test_build_shot_plan_mide_el_ciclo_con_la_rejilla():
    plan = build_shot_plan(
        "tema",
        duration=30.0,
        shots=5,
        transition=0.5,
        motion_bars=2,
        beat_grid=GRID_120,
    )
    assert plan.motion_bars == 2
    assert plan.motion_period == pytest.approx(4.0)


def test_build_shot_plan_sin_pulso_no_hay_ciclo():
    plan = build_shot_plan("tema", duration=30.0, shots=5, transition=0.5)
    assert plan.motion_period is None
    assert plan.motion_bars == DEFAULT_MOTION_BARS
    assert ShotPlan(topic="x").motion_period is None


# ---------------------------------------------------------------------------
# Expresiones del filtro
# ---------------------------------------------------------------------------


def test_motion_expressions_sin_ciclo_mantiene_el_barrido():
    zoom_in = motion_expressions(Motion.ZOOM_IN, 30)
    assert "min(1+" in zoom_in[0]
    pan = motion_expressions(Motion.PAN_LEFT, 30)
    assert "1-on/30" in pan[1]


def test_motion_expressions_con_ciclo_es_periodico():
    zoom_in = motion_expressions(Motion.ZOOM_IN, 90, cycle_frames=60)
    # Ciclo de 60 fotogramas: la onda triangular va y vuelve dentro del ciclo.
    assert "mod(on,60)/60" in zoom_in[0]
    assert "min(" in zoom_in[0]
    zoom_out = motion_expressions(Motion.ZOOM_OUT, 90, cycle_frames=60)
    assert zoom_out[0].startswith("1.3-")
    pan_right = motion_expressions(Motion.PAN_RIGHT, 90, cycle_frames=60)
    assert "mod(on,60)/60" in pan_right[1]
    pan_left = motion_expressions(Motion.PAN_LEFT, 90, cycle_frames=60)
    assert "1-min(" in pan_left[1]
    tilt = motion_expressions(Motion.TILT_DOWN, 90, cycle_frames=60)
    assert "mod(on,60)/60" in tilt[2]
    static = motion_expressions(Motion.STATIC, 90, cycle_frames=60)
    assert static[0] == "1.04"


def test_animate_filter_con_periodo_usa_la_rejilla():
    chain = animate_filter(
        Motion.ZOOM_IN, duration=6.0, size=(640, 360), fps=30, motion_period=2.0
    )
    # 2 s a 30 fps = 60 fotogramas por ciclo.
    assert "mod(on,60)/60" in chain
    assert "zoompan" in chain
    # Sin periodo, el barrido clásico (sin mod).
    plain = animate_filter(Motion.ZOOM_IN, duration=6.0, size=(640, 360), fps=30)
    assert "mod(" not in plain


def _ffmpeg_mod(value: float, step: float) -> float:
    """``mod()`` de FFmpeg (resto siempre positivo) para evaluar expresiones."""
    return value % step


def _zoom_at(expression: str, frame: int) -> float:
    """Evalúa la expresión de zoom del filtro en un fotograma concreto.

    Solo se usa en los tests: reproduce el ``min``/``mod`` de FFmpeg para
    comprobar la forma de onda del movimiento sin abrir un vídeo.
    """
    return float(
        eval(  # noqa: S307 - expresión generada por el propio módulo en el test
            expression,
            {"min": min, "mod": _ffmpeg_mod, "iw": 100.0, "ih": 100.0, "zoom": 1.25},
            {"on": frame},
        )
    )


def test_la_onda_del_movimiento_va_y_vuelve_al_compas():
    # Ciclo completo de 60 fotogramas (2 s a 30 fps): el zoom sube hasta el
    # pico (mitad de ciclo) y vuelve al punto de partida al cerrarlo, ciclo
    # tras ciclo.
    zoom, _, _ = motion_expressions(Motion.ZOOM_IN, 240, cycle_frames=60)
    assert _zoom_at(zoom, 0) == pytest.approx(1.0)
    assert _zoom_at(zoom, 15) == pytest.approx(1.15)
    assert _zoom_at(zoom, 30) == pytest.approx(1.3)
    assert _zoom_at(zoom, 45) == pytest.approx(1.15)
    assert _zoom_at(zoom, 60) == pytest.approx(1.0)
    assert _zoom_at(zoom, 90) == pytest.approx(1.3)
    assert _zoom_at(zoom, 120) == pytest.approx(1.0)
    # El paneo recorre el encuadre y vuelve: x relativo 0 → 1 → 0 del margen
    # disponible (con iw=100 y zoom=1.25 el margen son 20 unidades).
    _, pan, _ = motion_expressions(Motion.PAN_RIGHT, 240, cycle_frames=60)
    positions = [_zoom_at(pan, frame) for frame in (0, 15, 30, 45, 60, 90)]
    assert positions[0] == pytest.approx(0.0)
    assert positions[1] == pytest.approx(10.0)
    assert positions[2] == pytest.approx(20.0)
    assert positions[3] == pytest.approx(10.0)
    assert positions[4] == pytest.approx(0.0)
    assert positions[5] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Integración con FFmpeg
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_animate_shot_con_ciclo_genera_el_clip(tmp_path: Path):
    image = tmp_path / "shot.png"
    image.write_bytes(StubGenerator().generate("plano", width=384, height=216, seed=7))
    clip = asyncio.run(
        animate_shot(
            image,
            tmp_path / "clip.mp4",
            duration=2.0,
            motion=Motion.ZOOM_IN,
            size=(384, 216),
            fps=15,
            motion_period=1.0,
        )
    )
    assert abs(asyncio.run(probe_duration(clip)) - 2.0) < 0.2


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_render_visuals_mueve_al_compas(tmp_path: Path):
    """El render completo mide el pulso y el plan guarda su ciclo."""
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
                "aevalsrc=0.8*sin(2*PI*1000*t)*between(mod(t\\,0.5)\\,0\\,0.03):s=22050:d=10",
                str(song),
            ]
        )
    )
    from youber.visuals.tempo import detect_grid

    grid = asyncio.run(detect_grid(song))
    assert grid.detected
    result = asyncio.run(
        render_visuals(
            topic="movimiento al compas",
            output=tmp_path / "out.mp4",
            song=song,
            shots=3,
            fps=15,
            generator=StubGenerator(),
            beat_grid=grid,
            motion_bars=2,
        )
    )
    plan = result.plan
    assert plan.motion_bars == 2
    assert plan.motion_period == pytest.approx(2 * grid.bar_interval, abs=1e-3)
    # El clip animado respeta la duración del plano y se puede medir.
    assert abs(asyncio.run(probe_duration(result.clips[0])) - plan.shots[0].duration) < 0.2
    # La señal de samples del filtro no debe romper el render de un plano largo.
    assert len(plan.shots) == 3


def test_motion_period_none_no_rompe_el_filtro(tmp_path: Path):
    chain = animate_filter(Motion.PAN_RIGHT, duration=1.0, size=(320, 180), fps=15)
    assert chain.endswith("format=yuv420p")
