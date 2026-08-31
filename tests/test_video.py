"""Tests del motor de edición de vídeo (models, timeline, effects, transitions, overlays, renderer, editor, cli)."""

import asyncio
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from youber.video.cli import _resolution, _transition_type, build_parser
from youber.video.editor import VideoEditor
from youber.video.effects import (
    clip_audio_filters,
    clip_video_filters,
    scale_filter,
    speed_audio_filter,
    speed_video_filter,
)
from youber.video.models import (
    Clip,
    ImageOverlay,
    Project,
    TextOverlay,
    TextPosition,
    Transition,
    TransitionType,
)
from youber.video.overlays import image_overlay_filter, text_overlay_filter
from youber.video.renderer import render_project
from youber.video.timeline import Timeline, TimelineSegment
from youber.video.transitions import audio_transition_chain, video_transition_chain

HAS_FFMPEG = shutil.which("ffmpeg") is not None

CLIP_A = "clip_a.mp4"
CLIP_B = "clip_b.mp4"


def make_project(**kwargs) -> Project:
    """Proyecto de prueba con 2 clips de 5 s cada uno."""
    defaults = {
        "title": "Proyecto test",
        "clips": [
            Clip(file_path=Path(CLIP_A), duration=5.0),
            Clip(file_path=Path(CLIP_B), duration=5.0),
        ],
        "resolution": (1280, 720),
        "fps": 30,
    }
    defaults.update(kwargs)
    return Project(**defaults)


def make_timeline(segments: list[TimelineSegment] | None = None, transitions: list[Transition] | None = None) -> Timeline:
    if segments is None:
        segments = [
            TimelineSegment(
                index=0,
                file_path=Path(CLIP_A),
                source_start=0.0,
                source_duration=5.0,
                output_duration=5.0,
                has_audio=True,
            ),
            TimelineSegment(
                index=1,
                file_path=Path(CLIP_B),
                source_start=0.0,
                source_duration=5.0,
                output_duration=5.0,
                has_audio=True,
            ),
        ]
    return Timeline(
        segments=segments,
        transitions=transitions or [],
        total_duration=sum(s.output_duration for s in segments),
        resolution=(1280, 720),
        fps=30,
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_transition_type_values():
    assert TransitionType.NONE == "none"
    assert TransitionType.FADE == "fade"
    assert TransitionType.CROSSFADE == "crossfade"
    assert TransitionType.WIPE == "wipe"
    assert TransitionType.SLIDE == "slide"


def test_text_position_values():
    assert TextPosition.BOTTOM_CENTER == "bottom_center"
    assert TextPosition.TOP_LEFT == "top_left"
    assert TextPosition.CENTER == "center"


def test_clip_defaults():
    clip = Clip(file_path=Path("a.mp4"))
    assert clip.start == 0.0
    assert clip.duration is None
    assert clip.volume == 1.0
    assert clip.speed == 1.0
    assert clip.crop is None


def test_clip_validation():
    with pytest.raises(ValidationError):
        Clip(file_path=Path("a.mp4"), volume=2.5)
    with pytest.raises(ValidationError):
        Clip(file_path=Path("a.mp4"), speed=0)


def test_project_defaults():
    project = Project(title="T")
    assert project.music_track_id is None
    assert project.music_volume == 0.3
    assert project.output_format == "mp4"
    assert project.resolution == (1920, 1080)
    assert project.fps == 30


def test_transition_validation():
    with pytest.raises(ValidationError):
        Transition(clip_index=0)  # ge=1
    with pytest.raises(ValidationError):
        Transition(clip_index=1, duration=0)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


async def test_timeline_build_with_durations():
    timeline = await Timeline.build(make_project())
    assert len(timeline.segments) == 2
    assert timeline.segments[0].output_duration == 5.0
    assert timeline.total_duration == 10.0


async def test_timeline_build_with_transition_reduces_total():
    project = make_project(
        transitions=[Transition(clip_index=1, type=TransitionType.FADE, duration=1.0)]
    )
    timeline = await Timeline.build(project)
    assert timeline.total_duration == 9.0


async def test_timeline_build_probes_duration(monkeypatch):
    """Clip sin duración → se consulta ffprobe (mockeado)."""
    async def fake_probe(path):
        return 12.0

    monkeypatch.setattr("youber.video.timeline.probe_duration", fake_probe)
    project = make_project(clips=[Clip(file_path=Path(CLIP_A))])
    timeline = await Timeline.build(project)
    assert timeline.segments[0].source_duration == 12.0
    assert timeline.segments[0].output_duration == 12.0


async def test_timeline_build_speed(monkeypatch):
    async def fake_probe(path):
        return 10.0

    monkeypatch.setattr("youber.video.timeline.probe_duration", fake_probe)
    project = make_project(clips=[Clip(file_path=Path(CLIP_A), speed=2.0)])
    timeline = await Timeline.build(project)
    # 10 s de fuente a 2× → 5 s de salida
    assert timeline.segments[0].output_duration == 5.0


def test_timeline_invalid_transitions_ignored(monkeypatch):
    """Las transiciones con clip_index fuera de rango se descartan en build."""
    async def fake_probe(path):
        return 5.0

    async def fake_has_audio(path):
        return True

    monkeypatch.setattr("youber.video.timeline.probe_duration", fake_probe)
    monkeypatch.setattr("youber.video.timeline._has_audio_stream", fake_has_audio)
    project = make_project(
        transitions=[Transition(clip_index=5, type=TransitionType.FADE)]
    )
    timeline = asyncio.run(Timeline.build(project))
    assert timeline.transitions == []


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------


def test_speed_video_filter():
    assert speed_video_filter(2.0) == "setpts=PTS/2.000000"
    assert speed_video_filter(0.5) == "setpts=PTS/0.500000"


def test_speed_audio_filter_chains():
    # atempo admite 0.5-2.0 por instancia; 4× requiere encadenar
    result = speed_audio_filter(4.0)
    assert "atempo=2.0,atempo=2.000000" in result


def test_speed_audio_filter_single():
    assert speed_audio_filter(1.5) == "atempo=1.500000"


def test_scale_filter():
    result = scale_filter(1280, 720)
    assert "scale=1280:720" in result
    assert "pad=1280:720" in result


def test_clip_video_filters_with_crop():
    filters = clip_video_filters((10, 20, 100, 50), 1.0, 1280, 720, 30)
    assert "crop=100:50:10:20" in filters
    assert any("scale=1280:720" in f for f in filters)
    assert any("fps=30" in f for f in filters)


def test_clip_audio_filters():
    filters = clip_audio_filters(0.5, 1.0)
    assert "volume=0.500000" in filters
    assert any("aresample=48000" in f for f in filters)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def test_video_transition_chain_xfade():
    timeline = make_timeline(
        transitions=[Transition(clip_index=1, type=TransitionType.FADE, duration=1.0)]
    )
    chain, label = video_transition_chain(timeline)
    assert "xfade=transition=fade:duration=1.000:offset=4.000" in chain
    assert label == "vx1"


def test_video_transition_chain_concat_when_none():
    timeline = make_timeline()  # sin transiciones
    chain, label = video_transition_chain(timeline)
    assert "concat=n=2:v=1:a=0" in chain
    assert label == "vx1"


def test_video_transition_chain_single_clip():
    timeline = make_timeline(segments=[timeline_single()])
    chain, label = video_transition_chain(timeline)
    assert chain == ""
    assert label == "v0"


def timeline_single() -> TimelineSegment:
    return TimelineSegment(
        index=0,
        file_path=Path(CLIP_A),
        source_start=0.0,
        source_duration=5.0,
        output_duration=5.0,
        has_audio=True,
    )


def test_video_transition_chain_three_clips_offsets():
    segments = [
        TimelineSegment(index=0, file_path=Path(CLIP_A), source_start=0, source_duration=5, output_duration=5, has_audio=True),
        TimelineSegment(index=1, file_path=Path(CLIP_B), source_start=0, source_duration=5, output_duration=5, has_audio=True),
        TimelineSegment(index=2, file_path=Path("c.mp4"), source_start=0, source_duration=5, output_duration=5, has_audio=True),
    ]
    timeline = make_timeline(
        segments=segments,
        transitions=[
            Transition(clip_index=1, type=TransitionType.FADE, duration=1.0),
            Transition(clip_index=2, type=TransitionType.WIPE, duration=1.0),
        ],
    )
    chain, label = video_transition_chain(timeline)
    assert "offset=4.000" in chain  # 5 - 1
    assert "offset=8.000" in chain  # 5+5-1-1 = 8
    assert "wipeleft" in chain
    assert label == "vx2"


def test_audio_transition_chain_acrossfade():
    timeline = make_timeline(
        transitions=[Transition(clip_index=1, type=TransitionType.FADE, duration=1.0)]
    )
    chain, label = audio_transition_chain(timeline)
    assert "acrossfade=d=1.000" in chain
    assert label == "ax1"


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------


def test_text_overlay_filter_default():
    overlay = TextOverlay(text="Hola")
    flt = text_overlay_filter(overlay, total_duration=10.0)
    assert "drawtext=" in flt
    assert "text='Hola'" in flt
    assert "fontsize=48" in flt
    assert "x=(w-text_w)/2" in flt  # bottom_center
    assert "enable='between(t,0.000,10.000)'" in flt


def test_text_overlay_filter_position_and_window():
    overlay = TextOverlay(text="X", position=TextPosition.TOP_LEFT, start_time=2.0, duration=3.0)
    flt = text_overlay_filter(overlay, total_duration=10.0)
    assert "x=10" in flt and "y=10" in flt
    assert "enable='between(t,2.000,5.000)'" in flt


def test_image_overlay_filter():
    overlay = ImageOverlay(image_path=Path("logo.png"), opacity=0.5)
    flt = image_overlay_filter(overlay, "vout", "vfinal", total_duration=10.0, image_index=2)
    assert "colorchannelmixer=aa=0.50" in flt
    assert "overlay=x=W-w-10:y=H-h-10" in flt
    assert "enable='between(t,0.000,10.000)'" in flt


# ---------------------------------------------------------------------------
# Renderer (mocks)
# ---------------------------------------------------------------------------


class FakeResult:
    returncode = 0
    stdout = ""
    stderr = ""


@pytest.fixture
def mock_render_deps(monkeypatch):
    calls: list[list[str]] = []

    async def fake_run(cmd):
        calls.append(cmd)
        return FakeResult()

    async def fake_probe(path):
        return 5.0

    async def fake_has_audio(path):
        return True

    monkeypatch.setattr("youber.video.renderer.run_command", fake_run)
    monkeypatch.setattr("youber.video.renderer.Timeline.build", fake_timeline_build)
    return calls


async def fake_timeline_build(project):
    return make_timeline(
        transitions=[
            Transition(clip_index=1, type=TransitionType.FADE, duration=1.0)
        ]
    )


async def test_render_project_command(mock_render_deps):
    calls = mock_render_deps
    project = make_project(
        transitions=[Transition(clip_index=1, type=TransitionType.FADE, duration=1.0)],
        text_overlays=[TextOverlay(text="Hola")],
    )
    out = await render_project(project, "salida.mp4")
    assert out == "salida.mp4"
    cmd = " ".join(calls[0])
    assert cmd.startswith("ffmpeg")
    assert "xfade=transition=fade" in cmd
    assert "drawtext=" in cmd
    assert "-map [vt0]" in cmd  # overlay de texto: vx1 → vt0
    assert "-map [ax1]" in cmd


async def test_render_project_with_music(mock_render_deps):
    calls = mock_render_deps
    project = make_project(music_volume=0.3)
    await render_project(project, "salida.mp4", music_path="musica.mp3")
    cmd = " ".join(calls[0])
    assert "-stream_loop -1 -i musica.mp3" in cmd
    assert "amix=inputs=2:duration=first" in cmd
    assert "volume=0.300" in cmd


async def test_render_project_no_clips(monkeypatch):
    """Sin clips → ValueError (Timeline.build real, sin probing)."""
    async def fake_run(cmd):
        return FakeResult()

    monkeypatch.setattr("youber.video.renderer.run_command", fake_run)
    with pytest.raises(ValueError, match="no tiene clips"):
        await render_project(Project(title="vacío"), "salida.mp4")


async def test_render_project_bad_format(mock_render_deps):
    project = make_project(output_format="avi")
    with pytest.raises(ValueError):
        await render_project(project, "salida.avi")


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------


def test_editor_new_project_and_roundtrip(tmp_path: Path):
    editor = VideoEditor()
    project = editor.new_project("Mi vídeo", resolution=(1280, 720), fps=24)
    assert project.title == "Mi vídeo"
    assert project.resolution == (1280, 720)
    assert project.created_at is not None

    path = editor.save(project, tmp_path / "p.json")
    loaded = VideoEditor.load(path)
    assert loaded.title == "Mi vídeo"
    assert loaded.resolution == (1280, 720)


def test_editor_build_project():
    editor = VideoEditor()
    project = editor.new_project("T")
    editor.add_clip(project, CLIP_A)
    editor.add_clip(project, CLIP_B, speed=1.5)
    editor.add_transition(project, clip_index=1, type="fade", duration=1.0)
    editor.add_text(project, "Hola", position="top_center")
    editor.add_image(project, "logo.png")
    editor.set_music(project, "track123", volume=0.2)

    assert len(project.clips) == 2
    assert project.clips[1].speed == 1.5
    assert project.transitions[0].type == TransitionType.FADE
    assert project.text_overlays[0].position == TextPosition.TOP_CENTER
    assert project.music_track_id == "track123"
    assert project.music_volume == 0.2
    assert project.updated_at is not None


def test_editor_add_transition_invalid_type():
    editor = VideoEditor()
    project = editor.new_project("T")
    with pytest.raises(ValueError):
        editor.add_transition(project, clip_index=1, type="explosion")


def test_editor_render_requires_library_for_music(monkeypatch):
    editor = VideoEditor(library=None)
    project = make_project(music_track_id="x")
    with pytest.raises(ValueError, match="music_track_id"):
        asyncio.run(editor.render(project, "out.mp4"))


def test_editor_render_resolves_music_from_library(monkeypatch, tmp_path: Path):
    from youber.music.library import MusicLibrary
    from youber.music.models import Track

    music_file = tmp_path / "musica.mp3"
    music_file.write_bytes(b"x")
    library = MusicLibrary(tmp_path, db_path=tmp_path / "c.db")
    track = Track(
        id="t1",
        file_path=music_file,
        title="Mi tema",
        duration=30.0,
        file_hash="abc",
    )
    library.db.add_track(track)

    editor = VideoEditor(library=library)
    project = make_project(music_track_id="t1")

    async def fake_render(proj, output, music_path=None):
        assert music_path == str(music_file)
        return output

    monkeypatch.setattr("youber.video.editor.render_project", fake_render)
    out = asyncio.run(editor.render(project, str(tmp_path / "out.mp4")))
    assert out == str(tmp_path / "out.mp4")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_resolution():
    import argparse

    assert _resolution("1920x1080") == (1920, 1080)
    with pytest.raises(argparse.ArgumentTypeError):
        _resolution("no")


def test_cli_transition_type():
    import argparse

    assert _transition_type("fade") == TransitionType.FADE
    assert _transition_type("WIPE") == TransitionType.WIPE
    with pytest.raises(argparse.ArgumentTypeError):
        _transition_type("explosion")


def test_cli_parser_commands():
    parser = build_parser()
    args = parser.parse_args(["new", "p.json", "--title", "T"])
    assert args.command == "new"
    args = parser.parse_args(["add-clip", "p.json", "a.mp4", "--speed", "1.5"])
    assert args.command == "add-clip"
    assert args.speed == 1.5
    args = parser.parse_args(
        ["add-transition", "p.json", "--clip-index", "2", "--type", "wipe"]
    )
    assert args.type == TransitionType.WIPE


# ---------------------------------------------------------------------------
# Integración real (solo si FFmpeg está instalado)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
async def test_integration_render_two_clips_with_transition(tmp_path: Path):
    """Genera 2 clips + música reales y renderiza un proyecto con transición, texto y música."""
    from youber.audio._ffmpeg import run_command

    clip_a = tmp_path / "a.mp4"
    clip_b = tmp_path / "b.mp4"
    music = tmp_path / "musica.mp3"

    for target, freq in ((clip_a, 440), (clip_b, 523)):
        await run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=duration=2:size=320x240:rate=30",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={freq}:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(target),
            ]
        )
    await run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:duration=4",
            "-c:a",
            "libmp3lame",
            str(music),
        ]
    )

    editor = VideoEditor()
    project = editor.new_project("Integración", resolution=(320, 240), fps=30)
    editor.add_clip(project, clip_a)
    editor.add_clip(project, clip_b)
    editor.add_transition(project, clip_index=1, type=TransitionType.CROSSFADE, duration=1.0)

    # drawtext necesita una fuente explícita en sistemas sin fontconfig
    # (p. ej. Windows); si no hay fuente disponible, se omite el texto.
    font = next(
        (
            candidate
            for candidate in (
                "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            )
            if Path(candidate).exists()
        ),
        None,
    )
    if font:
        editor.add_text(
            project,
            "Hola BARF",
            position=TextPosition.TOP_CENTER,
            font_size=24,
            font_file=font,
        )

    output = tmp_path / "final.mp4"
    await editor.render(project, str(output), music_path=str(music))
    assert output.exists()
    assert output.stat().st_size > 0

    # Verificar con ffprobe que es un MP4 válido con duración ≈ 3 s (2+2-1).
    probe = await run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(output),
        ]
    )
    duration = float(probe.stdout.strip())
    assert 2.5 <= duration <= 3.5, f"duración inesperada: {duration}"
