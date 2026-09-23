"""Tests del estilo variable por escena (Fase 24).

Hoy el estilo (`cinematic`, `dreamy`, `vibrant`...) es **uno para todo el
vídeo**. Aquí se mide el tramo de canción que cubre cada escena del guion y se
elige un estilo por escena: una intro floja no se ve igual que un estribillo a
tope. Todo es determinista y offline salvo la integración con FFmpeg.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from youber.audio._ffmpeg import probe_duration, run_command
from youber.script.models import Scene, SceneType
from youber.visuals.generator import StubGenerator
from youber.visuals.models import STYLE_SUFFIXES, VisualStyle
from youber.visuals.prompts import build_shot_plan
from youber.visuals.render import render_visuals
from youber.visuals.selector import (
    SECTION_ENERGY_WEIGHT,
    StyleSignals,
    build_signals,
    scene_choices,
    scene_section_energies,
    section_energy,
    signals_for_section,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _scenes(*durations: float) -> list[Scene]:
    """Escenas sencillas (una por duración) con nombres distintos."""
    types = [SceneType.HOOK, SceneType.CONTENT, SceneType.CTA, SceneType.CLIMAX]
    return [
        Scene(
            type=types[index % len(types)],
            title=f"Escena {index}",
            duration=duration,
            text=f"Texto {index}",
        )
        for index, duration in enumerate(durations)
    ]


# ---------------------------------------------------------------------------
# Energía por tramo
# ---------------------------------------------------------------------------


def test_section_energy_promedia_el_tramo():
    profile = [8000.0] * 4 + [2000.0] * 4
    assert section_energy(profile, 0.0, 4.0) == pytest.approx(1.0)
    assert section_energy(profile, 4.0, 4.0) == pytest.approx(0.25)
    # Tramo a caballo entre los dos: mezcla de ventanas.
    assert section_energy(profile, 3.0, 2.0) == pytest.approx(0.625)
    # Sin datos no hay energía que medir.
    assert section_energy([], 0.0, 5.0) is None
    assert section_energy(profile, 0.0, 0.0) is None
    assert section_energy([0.0, 0.0], 0.0, 2.0) is None


def test_scene_section_energies_reparte_las_escenas_en_orden():
    profile = [8000.0] * 10 + [1000.0] * 10
    scenes = _scenes(10.0, 10.0)
    measured = scene_section_energies(scenes, profile)
    assert measured[0] == pytest.approx(1.0)
    assert measured[1] == pytest.approx(0.125)


def test_signals_for_section_mezcla_la_energia_del_tramo():
    base = StyleSignals(energy=0.5, valence=0.2)
    mixed = signals_for_section(base, 1.0)
    assert mixed.energy == pytest.approx(0.5 * (1 - SECTION_ENERGY_WEIGHT) + 1.0 * SECTION_ENERGY_WEIGHT)
    # El resto de ejes del tema no se toca.
    assert mixed.valence == base.valence
    # Sin medida de la sección se queda el tema tal cual.
    assert signals_for_section(base, None) is base


# ---------------------------------------------------------------------------
# Estilo por escena
# ---------------------------------------------------------------------------


def test_scene_choices_la_intro_floja_no_es_el_estribillo():
    # Mitad tranquila, mitad a tope. Las señales del tema van neutras a
    # propósito: así el test mide la energía **del tramo** y no la tensión que
    # se deduce de las dinámicas (un escalón de volumen la dispara).
    profile = [1500.0] * 10 + [9000.0] * 10
    base = StyleSignals(energy=0.65)
    choices = scene_choices(base, _scenes(10.0, 10.0), energies=profile, variation_key="tema|1")

    quieta, fuerte = choices[0], choices[1]
    assert fuerte.style == VisualStyle.VIBRANT
    assert quieta.style != fuerte.style
    assert quieta.style in {VisualStyle.MINIMAL, VisualStyle.CINEMATIC, VisualStyle.DREAMY}
    # Determinista: mismas señales ⇒ mismos estilos.
    again = scene_choices(base, _scenes(10.0, 10.0), energies=profile, variation_key="tema|1")
    assert [choice.style for choice in again] == [choice.style for choice in choices]


def test_scene_choices_sin_perfil_repiten_el_estilo_base():
    base = StyleSignals(energy=0.5)
    choices = scene_choices(base, _scenes(5.0, 5.0), energies=None, variation_key="x")
    assert len(choices) == 2
    assert len({choice.style for choice in choices}) == 1


# ---------------------------------------------------------------------------
# Plan de planos
# ---------------------------------------------------------------------------


def test_build_shot_plan_aplica_el_estilo_de_cada_escena():
    scenes = _scenes(10.0, 10.0)
    plan = build_shot_plan(
        "tema",
        scenes,
        duration=20.0,
        shots=4,
        transition=0.5,
        style=VisualStyle.CINEMATIC,
        scene_styles=[VisualStyle.DREAMY, VisualStyle.VIBRANT],
    )
    assert plan.scene_styles == ["dreamy", "vibrant"]
    styles = [shot.style for shot in plan.shots]
    assert styles[: len(styles) // 2] == [VisualStyle.DREAMY] * (len(styles) // 2)
    assert set(styles[len(styles) // 2 :]) == {VisualStyle.VIBRANT}
    # El prompt lleva el sufijo del estilo de su escena (no el del plan).
    assert STYLE_SUFFIXES[VisualStyle.DREAMY] in plan.shots[0].prompt
    assert STYLE_SUFFIXES[VisualStyle.VIBRANT] in plan.shots[-1].prompt


def test_build_shot_plan_sin_estilos_de_escena_no_marca_planos():
    plan = build_shot_plan("tema", _scenes(5.0), duration=5.0, shots=2)
    assert plan.scene_styles == []
    assert all(shot.style is None for shot in plan.shots)


def test_cli_visuals_tiene_no_scene_style():
    from youber.visuals.cli import build_parser

    args = build_parser().parse_args(["--topic", "t", "--song", "x.wav"])
    assert args.no_scene_style is False
    assert build_parser().parse_args(
        ["--topic", "t", "--song", "x.wav", "--no-scene-style"]
    ).no_scene_style


# ---------------------------------------------------------------------------
# Integración con FFmpeg
# ---------------------------------------------------------------------------


def _ramp_song(path: Path, *, quiet: float = 0.1, loud: float = 0.9, seconds: float = 10.0) -> None:
    """Canción sintética: primera mitad floja, segunda a tope."""
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
                (
                    f"aevalsrc=({quiet}*sin(2*PI*220*t))*between(t\\,0\\,{seconds / 2})"
                    f"+({loud}*sin(2*PI*220*t))*between(t\\,{seconds / 2}\\,{seconds})"
                    f":d={seconds}:s=22050"
                ),
                str(path),
            ]
        )
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_render_visuals_cambia_de_estilo_por_escena(tmp_path: Path):
    song = tmp_path / "ramp.wav"
    _ramp_song(song)
    # Señales del tema y perfil inyectados (como los mediría el CLI sobre este
    # audio): así el test fija el mecanismo (tramo flojo ≠ tramo fuerte) sin
    # depender de las peculiaridades del audio sintético.
    profile = [1500.0] * 5 + [9000.0] * 5
    result = asyncio.run(
        render_visuals(
            topic="estilo por escena",
            output=tmp_path / "out.mp4",
            song=song,
            scenes=_scenes(5.0, 5.0),
            signals=build_signals(energies=profile),
            loudness=profile,
            shots=4,
            fps=15,
            generator=StubGenerator(),
        )
    )
    plan = result.plan
    assert len(plan.scene_styles) == 2
    assert plan.scene_styles[0] != plan.scene_styles[1]
    assert plan.scene_styles[1] == VisualStyle.VIBRANT.value
    assert len(plan.scene_reasons) == 2
    assert len(plan.section_energies) == 2
    assert plan.section_energies[0] < plan.section_energies[1]
    assert abs(asyncio.run(probe_duration(result.video)) - 10.0) < 0.4


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_render_visuals_sin_estilo_por_escena(tmp_path: Path):
    song = tmp_path / "ramp.wav"
    _ramp_song(song)
    result = asyncio.run(
        render_visuals(
            topic="estilo unico",
            output=tmp_path / "out.mp4",
            song=song,
            scenes=_scenes(5.0, 5.0),
            shots=4,
            fps=15,
            generator=StubGenerator(),
            per_scene_style=False,
        )
    )
    assert result.plan.scene_styles == []
    assert all(shot.style is None for shot in result.plan.shots)
