"""Tests del módulo de generación visual (`youber.visuals`).

Cubren el plan de planos, el generador *stub* (sin GPU), la animación Ken
Burns, el montaje y el corte del Short. Los que necesitan FFmpeg van con
``skipif``; ninguno necesita GPU ni red.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from youber.audio._ffmpeg import probe_duration, run_command
from youber.script.models import Scene, SceneType
from youber.video.models import TextPosition
from youber.visuals.animate import animate_filter, animate_shot, motion_expressions
from youber.visuals.generator import StubGenerator, create_generator, diffusers_available
from youber.visuals.models import Aspect, Motion, VisualStyle
from youber.visuals.prompts import (
    build_shot_plan,
    fit_durations,
    plan_shots_count,
    scene_shot_counts,
    shot_prompt,
)
from youber.visuals.render import (
    VisualResult,
    build_visual_project,
    generate_images,
    render_visuals,
)
from youber.visuals.short import (
    best_window_start,
    extract_window,
    loudness_profile,
    window_energies,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _scenes() -> list[Scene]:
    """Tres escenas de guion (gancho, desarrollo y cierre)."""
    return [
        Scene(
            type=SceneType.HOOK,
            title="Gancho",
            duration=10.0,
            text="Empieza aquí",
            position=TextPosition.CENTER,
        ),
        Scene(type=SceneType.CONTENT, title="Desarrollo", duration=20.0, text="El detalle"),
        Scene(type=SceneType.CTA, title="Cierre", duration=10.0, text="Suscríbete"),
    ]


async def _make_tone(path: Path, seconds: float, audio_filter: str | None = None) -> None:
    """Genera un tono sintético con FFmpeg (para los tests de audio)."""
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={seconds}",
    ]
    if audio_filter:
        cmd += ["-af", audio_filter]
    cmd += ["-ac", "2", "-ar", "44100", str(path)]
    await run_command(cmd)


# ---------------------------------------------------------------------------
# Formatos y plan de planos (offline)
# ---------------------------------------------------------------------------


def test_aspect_tamanos_y_ratio():
    assert Aspect("16:9") is Aspect.LANDSCAPE
    assert Aspect("9:16") is Aspect.VERTICAL
    assert Aspect.LANDSCAPE.generate_size() == (1344, 768)
    assert Aspect.VERTICAL.generate_size() == (768, 1344)
    assert Aspect.VERTICAL.render_size() == (1080, 1920)
    assert Aspect.VERTICAL.is_vertical is True
    assert Aspect.LANDSCAPE.is_vertical is False
    assert 1.7 < Aspect.LANDSCAPE.ratio < 1.8


def test_fit_durations_cuadra_con_el_objetivo():
    durations = fit_durations(215.0, 14, 0.8)
    assert len(durations) == 14
    total = sum(durations) - 0.8 * (len(durations) - 1)
    assert total == pytest.approx(215.0, abs=1e-6)
    assert min(durations) > 2.0


def test_fit_durations_no_caben():
    with pytest.raises(ValueError, match="No caben"):
        fit_durations(6.0, 10, 0.8)


def test_plan_shots_count_auto_y_explicito():
    assert plan_shots_count(215.0) == 13
    assert plan_shots_count(20.0) == 4  # mínimo
    assert plan_shots_count(600.0) == 38
    assert plan_shots_count(215.0, shots=7) == 7


def test_scene_shot_counts_reparte_y_minimo_uno():
    scenes = _scenes()
    counts = scene_shot_counts(scenes, 9)
    assert sum(counts) == 9
    assert len(counts) == len(scenes)
    assert all(count >= 1 for count in counts)
    assert counts[1] >= counts[0]  # el desarrollo es más largo
    assert scene_shot_counts(scenes, 2) == [1, 1, 1]


def test_build_shot_plan_determinista_y_atado_al_guion():
    plan = build_shot_plan(
        "el paso del tiempo",
        _scenes(),
        duration=40.0,
        aspect=Aspect.VERTICAL,
        style=VisualStyle.DREAMY,
        mood="tristeza",
        tone="melancólico y nostálgico",
        keywords=["tiempo", "reloj"],
        transition=0.8,
    )
    assert plan.aspect is Aspect.VERTICAL
    assert plan.total_duration == pytest.approx(40.0, abs=1e-6)
    assert plan.shots[0].scene_index == 0
    assert plan.shots[-1].scene_index == 2
    assert all("el paso del tiempo" in shot.prompt for shot in plan.shots)
    assert all("dreamlike" in shot.prompt for shot in plan.shots)
    assert "cold blue tones" in plan.shots[0].prompt  # mood tristeza
    # Mismo plan si se repite la llamada.
    again = build_shot_plan(
        "el paso del tiempo",
        _scenes(),
        duration=40.0,
        aspect=Aspect.VERTICAL,
        style=VisualStyle.DREAMY,
        mood="tristeza",
        tone="melancólico y nostálgico",
        keywords=["tiempo", "reloj"],
        transition=0.8,
    )
    assert [shot.prompt for shot in plan.shots] == [shot.prompt for shot in again.shots]


def test_build_shot_plan_sin_escenas():
    plan = build_shot_plan("tema", duration=32.0, shots=4)
    assert len(plan.shots) == 4
    assert all(shot.scene_index is None for shot in plan.shots)
    assert plan.total_duration == pytest.approx(32.0, abs=1e-6)
    assert plan.shot_start(0) == 0.0
    assert plan.shot_start(1) == pytest.approx(8.6 - 0.8, abs=1e-6)


def test_shot_prompt_incluye_pistas():
    prompt = shot_prompt(
        "wide shot of {topic}",
        topic="la lluvia",
        style=VisualStyle.CINEMATIC,
        mood="misterio",
        tone="intrigante",
        keywords=["niebla", "noche"],
    )
    assert "la lluvia" in prompt
    assert "niebla" in prompt
    assert "fog" in prompt
    assert "intrigante" in prompt
    assert "no text" in prompt


# ---------------------------------------------------------------------------
# Generador de imágenes
# ---------------------------------------------------------------------------


def test_stub_generator_determinista_y_png_valido():
    generator = StubGenerator()
    first = generator.generate("un plano", width=64, height=32, seed=7)
    second = generator.generate("un plano", width=64, height=32, seed=7)
    other = generator.generate("otro plano", width=64, height=32, seed=7)
    assert first == second
    assert first != other
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    # El IHDR del PNG lleva ancho/alto en big-endian.
    assert int.from_bytes(first[16:20], "big") == 64
    assert int.from_bytes(first[20:24], "big") == 32


def test_create_generator_stub_y_sin_dependencias(monkeypatch):
    assert isinstance(create_generator(None), StubGenerator)
    assert isinstance(create_generator("stub"), StubGenerator)
    assert isinstance(create_generator(""), StubGenerator)
    monkeypatch.setattr("youber.visuals.generator.diffusers_available", lambda: True)
    assert create_generator("stabilityai/sdxl-turbo").name == "stabilityai/sdxl-turbo"
    monkeypatch.setattr("youber.visuals.generator.diffusers_available", lambda: False)
    with pytest.raises(RuntimeError, match="torch y diffusers"):
        create_generator("stabilityai/sdxl-turbo")
    assert isinstance(diffusers_available(), bool)


def test_generate_images_reutiliza_los_existentes(tmp_path: Path):
    class CountingGenerator(StubGenerator):
        calls = 0

        def generate(self, prompt, *, width, height, seed):
            CountingGenerator.calls += 1
            return super().generate(prompt, width=width, height=height, seed=seed)

    plan = build_shot_plan("tema", duration=10.0, shots=2)
    generator = CountingGenerator()
    paths = asyncio.run(generate_images(plan, tmp_path, generator, seed=3))
    assert CountingGenerator.calls == 2
    assert all(path.exists() for path in paths)
    assert plan.shots[0].image == paths[0]
    # Segunda pasada: no vuelve a generar.
    again = asyncio.run(generate_images(plan, tmp_path, generator, seed=3))
    assert CountingGenerator.calls == 2
    assert again == paths


# ---------------------------------------------------------------------------
# Animación (Ken Burns)
# ---------------------------------------------------------------------------


def test_motion_expressions_por_movimiento():
    zoom_in = motion_expressions(Motion.ZOOM_IN, 30)
    assert "min(1+" in zoom_in[0]
    pan = motion_expressions(Motion.PAN_LEFT, 30)
    assert pan[0] == "1.25"
    assert "on/30" in pan[1]
    static = motion_expressions(Motion.STATIC, 30)
    assert static[0] == "1.04"
    assert Motion.ZOOM_IN.is_zoom is True
    assert Motion.PAN_LEFT.is_zoom is False


def test_animate_filter_usa_tamanos_pares():
    chain = animate_filter(Motion.ZOOM_IN, duration=3.0, size=(1080, 1920), fps=30)
    assert "zoompan" in chain
    assert "s=1080x1920" in chain
    assert "format=yuv420p" in chain
    # 1080 * 1.3 = 1404 (par) y 1920 * 1.3 = 2496 (par).
    assert "scale=1404:2496" in chain


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_animate_shot_genera_clip_de_la_duracion_pedida(tmp_path: Path):
    image = tmp_path / "shot.png"
    image.write_bytes(StubGenerator().generate("plano", width=768, height=1344, seed=1))
    clip = asyncio.run(
        animate_shot(image, tmp_path / "clip.mp4", duration=2.0, motion=Motion.PAN_RIGHT,
                     size=(540, 960), fps=15)
    )
    duration = asyncio.run(probe_duration(clip))
    assert abs(duration - 2.0) < 0.2


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_animate_shot_sin_imagen(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        asyncio.run(animate_shot(tmp_path / "no.png", tmp_path / "clip.mp4", duration=1.0))


# ---------------------------------------------------------------------------
# Montaje
# ---------------------------------------------------------------------------


def test_build_visual_project_clips_transiciones_y_textos(tmp_path: Path):
    plan = build_shot_plan("tema", _scenes(), duration=40.0, shots=3, transition=0.5)
    clips = [tmp_path / f"clip_{index}.mp4" for index in range(len(plan.shots))]
    project = build_visual_project(
        plan, clips, scenes=_scenes(), texts=True, music_volume=1.0
    )
    assert len(project.clips) == 3
    assert len(project.transitions) == 2
    assert project.transitions[0].duration == 0.5
    assert project.music_volume == 1.0
    assert [overlay.text for overlay in project.text_overlays] == [
        "Empieza aquí",
        "El detalle",
        "Suscríbete",
    ]
    assert project.text_overlays[0].start_time == 0.0
    assert project.text_overlays[1].start_time == pytest.approx(plan.shot_start(1))


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_render_visuals_end_to_end_con_stub(tmp_path: Path):
    song = tmp_path / "song.wav"
    asyncio.run(_make_tone(song, 6.0))

    result = asyncio.run(
        render_visuals(
            topic="prueba offline",
            output=tmp_path / "out.mp4",
            song=song,
            aspect=Aspect.SQUARE,
            shots=3,
            fps=15,
            generator=StubGenerator(),
            seed=11,
        )
    )
    assert isinstance(result, VisualResult)
    assert result.video.exists() and result.video.stat().st_size > 1000
    assert len(result.images) == 3
    assert len(result.clips) == 3
    assert result.generator == "stub"
    assert result.plan.total_duration == pytest.approx(6.0, abs=0.05)
    duration = asyncio.run(probe_duration(result.video))
    assert abs(duration - 6.0) < 0.5
    assert result.preview is None


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_render_visuals_sin_cancion_ni_duracion(tmp_path: Path):
    with pytest.raises(ValueError, match="duración o pasa una canción"):
        asyncio.run(
            render_visuals(topic="x", output=tmp_path / "x.mp4", generator=StubGenerator())
        )


# ---------------------------------------------------------------------------
# Short (corte del estribillo)
# ---------------------------------------------------------------------------


def test_window_energies_y_best_window_start():
    import array

    samples = array.array("h", [0] * 8000 + [30000] * 8000)
    energies = window_energies(samples, sample_rate=8000, window=1.0)
    assert energies == [0.0, 30000.0]
    assert best_window_start(energies, 1.0) == 1.0
    assert best_window_start(energies, 5.0) == 0.0  # no cabe: devuelve el inicio


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_loudness_profile_detecta_el_trozo_fuerte(tmp_path: Path):
    song = tmp_path / "song.wav"
    # 4 s flojos y 4 s fuertes: el mejor corte de 3 s debe empezar en 4 s.
    asyncio.run(_make_tone(song, 8.0, "volume='if(lt(t,4),0.05,1)':eval=frame"))
    profile = asyncio.run(loudness_profile(song))
    assert len(profile) >= 7
    assert best_window_start(profile, 3.0) == pytest.approx(4.0, abs=1.0)


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_extract_window_recorta_con_fundidos(tmp_path: Path):
    song = tmp_path / "song.wav"
    asyncio.run(_make_tone(song, 10.0))
    cut = asyncio.run(
        extract_window(song, tmp_path / "cut.m4a", start=2.0, duration=4.0)
    )
    assert cut.exists()
    duration = asyncio.run(probe_duration(cut))
    assert abs(duration - 4.0) < 0.3


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_loudness_profile_sin_fichero(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        asyncio.run(loudness_profile(tmp_path / "no.wav"))


# ---------------------------------------------------------------------------
# CLI y flujo --lyrics-video --visuals ai
# ---------------------------------------------------------------------------


def test_cli_visuals_parser():
    from youber.visuals.cli import build_parser

    args = build_parser().parse_args(["--topic", "tema", "--song", "x.wav"])
    assert args.aspect == "16:9"
    assert args.style == "cinematic"
    assert args.short is None
    args = build_parser().parse_args(
        ["--topic", "tema", "--song", "x.wav", "--aspect", "9:16", "--short", "75", "--model", "stub"]
    )
    assert args.aspect == "9:16"
    assert args.short == 75.0
    assert args.model == "stub"
    assert build_parser().parse_args(["--topic", "t", "--song", "x.wav", "--short"]).short == 75.0


def test_workflow_parser_visuals_ai():
    from youber.cli.workflow_cli import build_parser

    args = build_parser().parse_args(["--lyrics-video", "--visuals", "ai", "--short"])
    assert args.visuals == "ai"
    assert args.short == 75.0
    assert args.ai_aspect == "16:9"
    assert build_parser().parse_args([]).visuals == "off"


def test_run_lyrics_video_con_visuals_ai(monkeypatch, tmp_path: Path):
    """El flujo usa la ruta IA: pide planos al módulo visual y anota el plan."""
    import youber.cli.workflow_cli as workflow_cli
    import youber.visuals.render as visuals_render
    from youber.music.models import Track
    from youber.research.data_models import ChannelData, VideoData

    track = Track(
        id="t1",
        file_path=tmp_path / "music" / "t1.wav",
        title="La noche",
        duration=120.0,
        file_hash="h",
        lyrical_themes={"tristeza": 0.9},
        lyrical_sentiment="negative",
    )

    class FakeLibrary:
        def __init__(self, library_dir, db_path=None):
            self.library_dir = Path(library_dir)

        async def scan(self, lyrics_dir=None):
            return {"added": 1, "updated": 0, "unchanged": 0, "removed": 0, "errors": 0}

        def all(self):
            return [track]

        def count(self):
            return 1

        def get(self, track_id):
            return track if track_id == track.id else None

        def search(self, text=None):
            return [track]

        def close(self):
            pass

    channel = ChannelData(
        name="Canal Triste",
        url="https://www.youtube.com/@triste",
        handle="triste",
        subscribers="1 K",
        videos=[
            VideoData(
                title="La soledad de la noche",
                url="https://www.youtube.com/watch?v=1",
                video_id="t1",
                views="1 K",
                channel_name="Canal Triste",
                channel_url="https://www.youtube.com/@triste",
                description="Sobre la tristeza y el adiós.",
                hashtags=["tristeza"],
            )
        ],
    )
    monkeypatch.setattr(workflow_cli, "MusicLibrary", FakeLibrary)
    monkeypatch.setattr(workflow_cli, "demo_channel", lambda: channel)

    captured: dict[str, object] = {}

    async def fake_render_visuals(**kwargs):
        captured.update(kwargs)
        output = Path(kwargs["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-mp4")
        plan = build_shot_plan(
            kwargs["topic"], kwargs["scenes"], duration=kwargs["duration"] or 30.0, shots=3
        )
        return VisualResult(
            video=output,
            plan=plan,
            images=[tmp_path / "shot_00.png"],
            clips=[tmp_path / "clip_00.mp4"],
            song=Path(kwargs["song"]),
            duration=plan.total_duration,
            generator=str(kwargs["generator"].name),
        )

    monkeypatch.setattr(visuals_render, "render_visuals", fake_render_visuals)

    result = asyncio.run(
        run_lyrics_video_for_test(workflow_cli, tmp_path)
    )
    assert result["visuals"] == "ai"
    assert result["clip_source"].startswith("ai:stub")
    assert Path(result["final_video"]).exists()
    assert Path(result["plan"]).exists()
    assert captured["aspect"] == "9:16"
    assert captured["texts"] is True
    assert result["short_video"] is None


async def run_lyrics_video_for_test(workflow_cli, tmp_path: Path) -> dict:
    """Ejecuta el flujo con la ruta IA y el generador de prueba."""
    return await workflow_cli.run_lyrics_video(
        demo=True,
        topic="La noche",
        output_dir=str(tmp_path / "out"),
        library_dir=str(tmp_path / "music"),
        visuals="ai",
        ai_model="stub",
        ai_shots=3,
        aspect="9:16",
        ai_texts=True,
        journal=False,
    )
