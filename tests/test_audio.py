"""Tests del módulo de audio: modelos, formatos, editor, efectos y sync.

La mayoría de tests usan mocks de ``run_command``/``probe_duration`` para que
la suite pase en CI **sin** FFmpeg instalado. Si FFmpeg está disponible en el
sistema, además se ejecutan tests de integración reales (generando un WAV
sintético con el propio FFmpeg).
"""

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from youber.audio._ffmpeg import ensure_ffmpeg
from youber.audio.editor import add_background_music, extract_audio, replace_audio
from youber.audio.effects import adjust_volume, apply_fade, mix_audios
from youber.audio.formats import (
    audio_codec_for,
    is_audio_input,
    is_video_input,
    validate_audio_output,
    validate_video_input,
)
from youber.audio.models import AudioConfig, ProcessingResult
from youber.audio.sync import align_audio_to_video, detect_silence

HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_audio_config_defaults():
    config = AudioConfig(music_path=Path("musica.mp3"))
    assert config.volume == 0.3
    assert config.music_start == 0.0
    assert config.fade_in == 2.0
    assert config.fade_out == 2.0
    assert config.loop is True
    assert config.original_audio_volume == 0.7


def test_audio_config_validation():
    with pytest.raises(ValidationError):
        AudioConfig(music_path=Path("m.mp3"), volume=1.5)  # fuera de 0-1
    with pytest.raises(ValidationError):
        AudioConfig(music_path=Path("m.mp3"), original_audio_volume=-0.2)


def test_processing_result_defaults():
    result = ProcessingResult(success=True)
    assert result.output_path is None
    assert result.duration is None
    assert result.error is None


# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------


def test_is_video_input():
    assert is_video_input("video.mp4")
    assert is_video_input("video.MOV")
    assert is_video_input("video.mkv")
    assert not is_video_input("audio.mp3")


def test_is_audio_input():
    assert is_audio_input("musica.mp3")
    assert is_audio_input("musica.wav")
    assert is_audio_input("musica.m4a")
    assert is_audio_input("musica.flac")
    assert not is_audio_input("video.mp4")


def test_validate_video_input_raises():
    with pytest.raises(ValueError):
        validate_video_input("video.xyz")
    with pytest.raises(ValueError):
        validate_video_input("musica.mp3")


def test_validate_audio_output_raises():
    with pytest.raises(ValueError):
        validate_audio_output("salida.xyz")
    with pytest.raises(ValueError):
        validate_audio_output("salida.mp4")  # mp4 es salida de vídeo


def test_audio_codec_for():
    assert audio_codec_for("a.mp3") == "libmp3lame"
    assert audio_codec_for("a.wav") == "pcm_s16le"
    assert audio_codec_for("a.m4a") == "aac"
    assert audio_codec_for("a.flac") == "flac"
    with pytest.raises(ValueError):
        audio_codec_for("a.xyz")


# ---------------------------------------------------------------------------
# Editor (mocks, sin FFmpeg)
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, stderr: str = ""):
        self.returncode = 0
        self.stdout = ""
        self.stderr = stderr


@pytest.fixture
def mock_ffmpeg(monkeypatch):
    calls: list[list[str]] = []

    async def fake_run(cmd):
        calls.append(cmd)
        return FakeResult()

    async def fake_probe(path):
        return 60.0  # 60 s de vídeo

    monkeypatch.setattr("youber.audio.editor.run_command", fake_run)
    monkeypatch.setattr("youber.audio.editor.probe_duration", fake_probe)
    monkeypatch.setattr("youber.audio.effects.run_command", fake_run)
    monkeypatch.setattr("youber.audio.effects.probe_duration", fake_probe)
    monkeypatch.setattr("youber.audio.sync.run_command", fake_run)
    return calls


async def test_add_background_music_command(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await add_background_music("video.mp4", "musica.mp3", "salida.mp4")
    assert out == "salida.mp4"
    cmd = " ".join(calls[0])
    assert cmd.startswith("ffmpeg")
    assert "-stream_loop -1" in cmd  # loop por defecto
    assert "amix=inputs=2" in cmd
    assert "volume=0.3" in cmd  # música al 30 %
    assert "volume=0.7" in cmd  # audio original al 70 %
    assert "afade=t=in:st=0:d=2" in cmd


async def test_add_background_music_no_loop(mock_ffmpeg):
    calls = mock_ffmpeg
    await add_background_music(
        "video.mp4", "musica.mp3", "salida.mp4", loop=False, volume=0.5, fade_in=0
    )
    cmd = " ".join(calls[0])
    assert "-stream_loop" not in cmd
    assert "volume=0.5" in cmd
    assert "afade=t=in" not in cmd  # fade_in=0 → sin filtro


async def test_add_background_music_validation(mock_ffmpeg):
    with pytest.raises(ValueError):
        await add_background_music("video.xyz", "musica.mp3", "salida.mp4")
    with pytest.raises(ValueError):
        await add_background_music("video.mp4", "musica.xyz", "salida.mp4")
    with pytest.raises(ValueError):
        await add_background_music("video.mp4", "musica.mp3", "salida.xyz")


async def test_extract_audio_command(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await extract_audio("video.mp4", "audio.mp3")
    assert out == "audio.mp3"
    cmd = calls[0]
    assert "-vn" in cmd
    assert "libmp3lame" in cmd

async def test_replace_audio_command(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await replace_audio("video.mp4", "nuevo.mp3", "final.mp4")
    assert out == "final.mp4"
    cmd = calls[0]
    assert "-map" in cmd and "0:v" in cmd
    assert "1:a" in cmd


# ---------------------------------------------------------------------------
# Effects (mocks)
# ---------------------------------------------------------------------------


async def test_apply_fade_in(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await apply_fade("musica.mp3", 2.0, fade_type="in")
    assert out.endswith("_fadein.mp3")
    cmd = calls[0]
    assert "afade=t=in:st=0:d=2.000" in cmd


async def test_apply_fade_out_uses_probe(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await apply_fade("musica.mp3", 3.0, fade_type="out")
    assert out.endswith("_fadeout.mp3")
    cmd = calls[0]
    # probe devuelve 60 s → fade out empieza en 57 s
    assert "afade=t=out:st=57.000:d=3.000" in cmd


async def test_apply_fade_both(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await apply_fade("musica.mp3", 1.5, fade_type="both")
    assert out.endswith("_fadeboth.mp3")
    cmd = " ".join(calls[0])
    assert "afade=t=in" in cmd and "afade=t=out" in cmd


async def test_apply_fade_invalid(mock_ffmpeg):
    with pytest.raises(ValueError):
        await apply_fade("musica.mp3", 2.0, fade_type="sideways")
    with pytest.raises(ValueError):
        await apply_fade("musica.mp3", -1.0)


async def test_adjust_volume(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await adjust_volume("musica.mp3", 0.5, "baja.mp3")
    assert out == "baja.mp3"
    cmd = calls[0]
    assert "volume=0.500" in cmd


async def test_adjust_volume_out_of_range(mock_ffmpeg):
    with pytest.raises(ValueError):
        await adjust_volume("musica.mp3", 2.5, "baja.mp3")
    with pytest.raises(ValueError):
        await adjust_volume("musica.mp3", -0.1, "baja.mp3")


async def test_mix_audios(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await mix_audios("a.mp3", "b.mp3", "mezcla.mp3", ratio=0.3)
    assert out == "mezcla.mp3"
    cmd = " ".join(calls[0])
    assert "volume=0.3" in cmd
    assert "volume=0.7" in cmd
    assert "amix=inputs=2:duration=longest" in cmd


async def test_mix_audios_invalid_ratio(mock_ffmpeg):
    with pytest.raises(ValueError):
        await mix_audios("a.mp3", "b.mp3", "mezcla.mp3", ratio=1.5)


# ---------------------------------------------------------------------------
# Sync (mocks)
# ---------------------------------------------------------------------------


async def test_detect_silence_parses_stderr(monkeypatch):
    stderr = (
        "[silencedetect @ 0x1] silence_start: 0\n"
        "[silencedetect @ 0x1] silence_end: 1.5 | silence_duration: 1.5\n"
        "[silencedetect @ 0x1] silence_start: 4\n"
        "[silencedetect @ 0x1] silence_end: 4.8 | silence_duration: 0.8\n"
    )

    async def fake_run(cmd):
        return FakeResult(stderr=stderr)

    monkeypatch.setattr("youber.audio.sync.run_command", fake_run)
    silences = await detect_silence("musica.mp3")
    assert silences == [
        {"start": 0.0, "end": 1.5, "duration": 1.5},
        {"start": 4.0, "end": 4.8, "duration": 0.8},
    ]


async def test_align_audio_to_video(mock_ffmpeg):
    calls = mock_ffmpeg
    out = await align_audio_to_video("video.mp4", "audio.mp3", "alineado.mp4")
    assert out == "alineado.mp4"
    # El último comando es el mux final (extracción de audio y detección previas).
    cmd = " ".join(calls[-1])
    assert "-shortest" in cmd
    assert "atrim=start=" in cmd or "adelay=" in cmd or "anull" in cmd


# ---------------------------------------------------------------------------
# Integración real (solo si FFmpeg está instalado)
# ---------------------------------------------------------------------------


def test_ensure_ffmpeg_raises_without_ffmpeg(monkeypatch):
    if not HAS_FFMPEG:
        monkeypatch.setattr("shutil.which", lambda tool: None)
        with pytest.raises(RuntimeError, match="FFmpeg no está instalado"):
            ensure_ffmpeg()
    else:
        ensure_ffmpeg()  # no debe lanzar


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
async def test_integration_extract_and_volume(tmp_path: Path):
    """Genera un WAV sintético y prueba extracción + volumen de verdad."""
    source = tmp_path / "fuente.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:d=1",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(source),
    ]
    from youber.audio._ffmpeg import run_command as real_run

    await real_run(cmd)
    assert source.exists()

    extracted = await extract_audio(str(source), str(tmp_path / "extraido.mp3"))
    assert Path(extracted).exists()

    adjusted = await adjust_volume(extracted, 0.5, str(tmp_path / "bajo.mp3"))
    assert Path(adjusted).exists()

    mixed = await mix_audios(extracted, adjusted, str(tmp_path / "mezcla.mp3"))
    assert Path(mixed).exists()

    silences = await detect_silence(str(tmp_path / "extraido.mp3"))
    assert isinstance(silences, list)
