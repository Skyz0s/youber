"""Tests del renderer de subtítulos (filtro libass + integración FFmpeg real).

Los tests de construcción del filtro son puros (sin FFmpeg). La integración
real (generar un vídeo sintético, quemar subtítulos y validar la salida con
ffprobe) se ejecuta solo si FFmpeg está disponible.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from youber.audio._ffmpeg import run_command
from youber.sync.renderer import (
    SubtitleRenderer,
    SubtitleStyle,
    build_subtitles_filter,
)
from youber.sync.timestamps import LyricsDocument, SyncError, SyncLine, to_lrc

HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# Construcción del filtro (puro)
# ---------------------------------------------------------------------------


def test_build_filter_estilo_explicito():
    vf = build_subtitles_filter(
        "subtitles.srt", SubtitleStyle(font_name="Arial"), 1080, None
    )
    assert vf.startswith("subtitles=filename='subtitles.srt'")
    assert "FontName=Arial" in vf
    assert "FontSize=54" in vf  # auto: 1080 * 0.05
    assert "MarginV=54" in vf
    assert "fontsdir" not in vf


def test_build_filter_valores_explicitos():
    vf = build_subtitles_filter(
        "s.srt", SubtitleStyle(font_name="Arial", font_size=20, margin_v=10), 1080, None
    )
    assert "FontSize=20" in vf
    assert "MarginV=10" in vf


def test_build_filter_escapa_ruta_fuentes_windows():
    vf = build_subtitles_filter(
        "s.srt", SubtitleStyle(font_name="Arial"), 720, "C:/Windows/Fonts"
    )
    assert "fontsdir='C\\:/Windows/Fonts'" in vf


def test_build_filter_sin_fuente_no_incluye_fontname(monkeypatch):
    import youber.sync.renderer as renderer

    # Neutraliza el default por plataforma (Arial en Windows).
    monkeypatch.setattr(renderer, "_default_font_name", lambda: None)
    vf = build_subtitles_filter("s.srt", SubtitleStyle(font_name=None), 720, None)
    assert "FontName=" not in vf
    assert "FontSize=" in vf


# ---------------------------------------------------------------------------
# Integración real (FFmpeg + libass)
# ---------------------------------------------------------------------------


async def _make_test_video(path: Path, seconds: float = 3.0) -> None:
    """Genera un vídeo sintético pequeño (testsrc2 + sine)."""
    await run_command(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-t", f"{seconds}",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(path),
        ]
    )


def _timed_doc() -> LyricsDocument:
    return LyricsDocument(
        lines=[
            SyncLine(start=0.5, end=1.5, text="Primera linea"),
            SyncLine(start=1.7, end=2.7, text="Segunda linea"),
        ],
        timed=True,
        source="lrc",
        duration=3.0,
    )


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requiere FFmpeg en el sistema")
async def test_render_integracion_real(tmp_path: Path):
    video = tmp_path / "video.mp4"
    await _make_test_video(video)

    lrc = tmp_path / "letra.lrc"
    lrc.write_text(to_lrc(_timed_doc()), encoding="utf-8")
    output = tmp_path / "video_sub.mp4"

    renderer = SubtitleRenderer()
    try:
        result = await renderer.render(video, lrc, output=output)
    except SyncError as exc:
        if "libass" in str(exc) or "subtitles" in str(exc):
            pytest.skip(f"FFmpeg sin libass: {exc}")
        raise

    assert output.is_file()
    assert result.output_path == output
    assert result.duration == pytest.approx(3.0, abs=0.8)
    assert result.resolution == (320, 240)


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requiere FFmpeg en el sistema")
async def test_render_documento_sin_timestamps_raise(tmp_path: Path):
    video = tmp_path / "video.mp4"
    await _make_test_video(video)
    doc = LyricsDocument(lines=[SyncLine(start=0.0, text="sin marcas")], timed=False)
    with pytest.raises(SyncError, match="timestamps"):
        await SubtitleRenderer().render(video, doc)


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requiere FFmpeg en el sistema")
def test_cli_burn_real(tmp_path: Path, capsys):
    from youber.sync.cli import main

    video = tmp_path / "video.mp4"
    asyncio.run(_make_test_video(video))
    lrc = tmp_path / "letra.lrc"
    lrc.write_text(to_lrc(_timed_doc()), encoding="utf-8")
    output = tmp_path / "out.mp4"

    try:
        code = main(["burn", "--video", str(video), "--lyrics", str(lrc), "-o", str(output)])
    except SyncError as exc:
        if "libass" in str(exc) or "subtitles" in str(exc):
            pytest.skip(f"FFmpeg sin libass: {exc}")
        raise
    assert code == 0
    assert output.is_file()
    assert "Subtítulos quemados" in capsys.readouterr().out
