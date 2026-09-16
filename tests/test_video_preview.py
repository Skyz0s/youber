"""Tests de las versiones ligeras para compartir (``youber.video.preview``)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from youber.video.preview import (
    DEFAULT_PREVIEW_AUDIO_BITRATE,
    make_preview,
    preview_path,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None


class _FakeResult:
    returncode = 0
    stdout = ""
    stderr = ""


def test_preview_path_junto_al_original():
    assert preview_path("salida/final.mp4").name == "final_preview.mp4"


async def test_make_preview_comando_por_defecto(tmp_path: Path, monkeypatch):
    src = tmp_path / "final.mp4"
    src.write_bytes(b"fake")
    calls: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> _FakeResult:
        calls.append(cmd)
        return _FakeResult()

    monkeypatch.setattr("youber.video.preview.ensure_ffmpeg", lambda: None)
    monkeypatch.setattr("youber.video.preview.run_command", fake_run)

    out = await make_preview(src)
    assert out == str(tmp_path / "final_preview.mp4")
    cmd = " ".join(calls[0])
    assert "scale=-2:480" in cmd
    assert "-b:a 128k" in cmd  # estéreo de calidad: no mono a 48 kbps
    assert "-ac 2" in cmd
    assert "+faststart" in cmd


async def test_make_preview_opciones(tmp_path: Path, monkeypatch):
    src = tmp_path / "final.mp4"
    src.write_bytes(b"fake")
    calls: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> _FakeResult:
        calls.append(cmd)
        return _FakeResult()

    monkeypatch.setattr("youber.video.preview.ensure_ffmpeg", lambda: None)
    monkeypatch.setattr("youber.video.preview.run_command", fake_run)

    out = await make_preview(
        src, tmp_path / "mini.mp4", height=360, audio_bitrate="192k"
    )
    assert out == str(tmp_path / "mini.mp4")
    cmd = " ".join(calls[0])
    assert "scale=-2:360" in cmd
    assert "-b:a 192k" in cmd


async def test_make_preview_fichero_inexistente(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("youber.video.preview.ensure_ffmpeg", lambda: None)

    async def fake_run(cmd: list[str]) -> _FakeResult:  # pragma: no cover
        raise AssertionError("no debería ejecutar FFmpeg")

    monkeypatch.setattr("youber.video.preview.run_command", fake_run)
    with pytest.raises(FileNotFoundError):
        await make_preview(tmp_path / "no-existe.mp4")


async def test_make_preview_parametros_invalidos(tmp_path: Path):
    with pytest.raises(ValueError, match="altura"):
        await make_preview(tmp_path / "x.mp4", height=0)
    with pytest.raises(ValueError, match="CRF"):
        await make_preview(tmp_path / "x.mp4", video_crf=-1)


def test_bitrate_por_defecto_es_estereo_decente():
    # Un preview con audio mono y <96 kbps suena metálico (lo que pasó con
    # preview_full270.mp4); el default debe evitarlo.
    assert DEFAULT_PREVIEW_AUDIO_BITRATE.endswith("k")
    assert int(DEFAULT_PREVIEW_AUDIO_BITRATE[:-1]) >= 96


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
async def test_integracion_preview_estereo(tmp_path: Path):
    """Renderiza un clip real y comprueba que el preview es 480p estéreo."""
    from youber.audio._ffmpeg import run_command

    src = tmp_path / "src.mp4"
    await run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=640x480:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            "2",
            str(src),
        ]
    )
    out = await make_preview(src, tmp_path / "preview.mp4", height=240)
    assert Path(out).exists()
    probe = await run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=channels,sample_rate",
            "-of",
            "default=noprint_wrappers=1",
            out,
        ]
    )
    assert "channels=2" in probe.stdout
    probe_v = await run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=height",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            out,
        ]
    )
    assert probe_v.stdout.strip() == "240"
