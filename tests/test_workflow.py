"""Tests del flujo completo de investigación + edición (workflow_cli)."""

import shutil
from pathlib import Path

import pytest

from youber.cli.workflow_cli import (
    build_parser,
    demo_channel,
    generate_test_music,
    generate_test_video,
    run_workflow,
)
from youber.research.data_models import ChannelData

HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.channel == "@python"
    assert args.max_videos == 10
    assert args.output_dir == "reports"
    assert args.video is None
    assert args.music is None
    assert args.duration == 30
    assert args.demo is False


def test_parser_flags():
    args = build_parser().parse_args(
        ["--channel", "@fastapi", "-n", "5", "-o", "out", "--demo", "--api"]
    )
    assert args.channel == "@fastapi"
    assert args.max_videos == 5
    assert args.output_dir == "out"
    assert args.demo is True
    assert args.api is True


def test_parser_api_html_mutually_exclusive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--api", "--html"])


# ---------------------------------------------------------------------------
# Canal sintético
# ---------------------------------------------------------------------------


def test_demo_channel():
    channel = demo_channel()
    assert isinstance(channel, ChannelData)
    assert len(channel.videos) == 4
    assert channel.handle == "canaldemo"
    titles = [video.title for video in channel.videos]
    assert any("TOP 10" in title for title in titles)
    assert any(title.startswith("¿Cómo") for title in titles)
    assert any("GUÍA COMPLETA" in title for title in titles)  # palabra en MAYÚSCULAS


# ---------------------------------------------------------------------------
# Generación de medios (mocks, sin FFmpeg)
# ---------------------------------------------------------------------------


async def test_generate_test_video_command(monkeypatch):
    calls: list[list[str]] = []

    async def fake_run(cmd):
        calls.append(cmd)

    monkeypatch.setattr("youber.cli.workflow_cli.run_command", fake_run)
    out = await generate_test_video("video.mp4", duration=10)
    assert out == "video.mp4"
    cmd = " ".join(calls[0])
    assert "testsrc=duration=10" in cmd
    assert "libx264" in cmd
    assert "aac" in cmd  # pista de audio para el amix posterior


async def test_generate_test_music_command(monkeypatch):
    calls: list[list[str]] = []

    async def fake_run(cmd):
        calls.append(cmd)

    monkeypatch.setattr("youber.cli.workflow_cli.run_command", fake_run)
    out = await generate_test_music("musica.mp3", duration=10)
    assert out == "musica.mp3"
    cmd = " ".join(calls[0])
    assert "sine=frequency=523" in cmd
    assert "libmp3lame" in cmd


# ---------------------------------------------------------------------------
# Flujo completo (mocks: sin red, sin FFmpeg)
# ---------------------------------------------------------------------------


async def test_run_workflow_demo_with_mocks(tmp_path: Path, monkeypatch):
    """Flujo completo en modo demo con FFmpeg mockeado (offline)."""
    calls: list[list[str]] = []

    async def fake_run(cmd):
        calls.append(cmd)

    async def fake_add_music(video, music, output, **kwargs):
        Path(output).write_bytes(b"fake-mp4")
        return output

    monkeypatch.setattr("youber.cli.workflow_cli.run_command", fake_run)
    monkeypatch.setattr("youber.cli.workflow_cli.add_background_music", fake_add_music)

    result = await run_workflow(demo=True, output_dir=str(tmp_path), duration=5)
    assert result["channel"].startswith("Canal Demo")
    assert result["videos"] == 4
    assert Path(result["final_video"]).exists()
    assert Path(result["json"]).exists()
    assert Path(result["csv"]).exists()
    assert Path(result["markdown"]).exists()
    # Se generaron vídeo y música de prueba
    assert Path(result["video"]).name == "test_video.mp4"
    assert Path(result["music"]).name == "test_music.mp3"


async def test_run_workflow_uses_local_media(tmp_path: Path, monkeypatch):
    """Si se pasan vídeo/música locales, no se generan con FFmpeg."""
    video = tmp_path / "mi_video.mp4"
    music = tmp_path / "mi_musica.mp3"
    video.write_bytes(b"v")
    music.write_bytes(b"m")

    async def fake_run(cmd):
        raise AssertionError("no debe generar medios si se pasan locales")

    async def fake_add_music(v, m, output, **kwargs):
        Path(output).write_bytes(b"fake-mp4")
        return output

    monkeypatch.setattr("youber.cli.workflow_cli.run_command", fake_run)
    monkeypatch.setattr("youber.cli.workflow_cli.add_background_music", fake_add_music)

    result = await run_workflow(
        demo=True,
        output_dir=str(tmp_path / "out"),
        video_path=str(video),
        music_path=str(music),
    )
    assert result["video"] == str(video)
    assert result["music"] == str(music)


# ---------------------------------------------------------------------------
# Integración real (solo si FFmpeg está instalado)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
async def test_run_workflow_demo_integration(tmp_path: Path):
    """Flujo completo real: genera vídeo+música con FFmpeg y los mezcla."""
    result = await run_workflow(demo=True, output_dir=str(tmp_path), duration=3)
    final = Path(result["final_video"])
    assert final.exists()
    assert final.stat().st_size > 0

    # El resultado debe ser un MP4 válido (comprobable con ffprobe).
    from youber.audio._ffmpeg import run_command

    probe = await run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration",
            "-of",
            "default=noprint_wrappers=1",
            str(final),
        ]
    )
    assert "mp4" in probe.stdout
