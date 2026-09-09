"""Tests de integración de sync en producción (pipeline + CLIs produce/workflow).

Estrategia: helpers puros offline; el flujo de los CLIs con mocks de catálogo
y del pipeline; una integración FFmpeg real (vídeo mudo + canción + letra)
con skipif cuando no hay FFmpeg.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from youber.music.library import find_track
from youber.sync.pipeline import (
    build_sync_document,
    find_sidecar_lyrics,
    sync_video_with_track,
)
from youber.sync.renderer import SUBTITLE_STYLE_PRESETS, subtitle_style_preset
from youber.sync.timestamps import SyncError

HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# find_track (catálogo)
# ---------------------------------------------------------------------------


def test_find_track_por_id_exacto():
    track = SimpleNamespace(id="ID1", title="Tema")

    class Fake:
        def get(self, query):
            return track if query == "ID1" else None

        def search(self, text=None, **kwargs):
            return []

    assert find_track(Fake(), "ID1") is track


def test_find_track_por_texto_si_no_hay_id():
    track = SimpleNamespace(id="abc", title="Bohemian Rhapsody")

    class Fake:
        def get(self, query):
            return None

        def search(self, text=None, **kwargs):
            return [track] if text == "bohemian" else []

    assert find_track(Fake(), "bohemian") is track


def test_find_track_sin_coincidencias_devuelve_none():
    class Fake:
        def get(self, query):
            return None

        def search(self, text=None, **kwargs):
            return []

    assert find_track(Fake(), "nada") is None
    assert find_track(Fake(), "  ") is None


# ---------------------------------------------------------------------------
# find_sidecar_lyrics
# ---------------------------------------------------------------------------


def test_sidecar_prefiere_lrc(tmp_path: Path):
    audio = tmp_path / "cancion.mp3"
    audio.write_bytes(b"x")
    (tmp_path / "cancion.lrc").write_text("[00:01.00]hola", encoding="utf-8")
    (tmp_path / "cancion.txt").write_text("hola", encoding="utf-8")
    assert find_sidecar_lyrics(audio) == tmp_path / "cancion.lrc"


def test_sidecar_txt_si_no_hay_lrc(tmp_path: Path):
    audio = tmp_path / "cancion.mp3"
    audio.write_bytes(b"x")
    (tmp_path / "cancion.txt").write_text("hola", encoding="utf-8")
    assert find_sidecar_lyrics(audio) == tmp_path / "cancion.txt"


def test_sidecar_sin_letra_devuelve_none(tmp_path: Path):
    audio = tmp_path / "cancion.mp3"
    audio.write_bytes(b"x")
    assert find_sidecar_lyrics(audio) is None


# ---------------------------------------------------------------------------
# build_sync_document
# ---------------------------------------------------------------------------


async def _fake_probe(_path) -> float:
    return 30.0


async def test_build_doc_sidecar_lrc_se_usa_tal_cual(tmp_path: Path, monkeypatch):
    import youber.sync.aligner as aligner

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    audio = tmp_path / "cancion.mp3"
    audio.write_bytes(b"x")
    (tmp_path / "cancion.lrc").write_text(
        "[00:01.00]Primera\n[00:02.00]Segunda", encoding="utf-8"
    )
    doc = await build_sync_document(audio)
    assert doc.source == "lrc"
    assert doc.lines[0].start == pytest.approx(1.0)


async def test_build_doc_sidecar_txt_usa_rough(tmp_path: Path, monkeypatch):
    import youber.sync.aligner as aligner

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    audio = tmp_path / "cancion.mp3"
    audio.write_bytes(b"x")
    (tmp_path / "cancion.txt").write_text("linea uno\nlinea dos", encoding="utf-8")
    doc = await build_sync_document(audio)
    assert doc.source == "rough"
    assert len(doc.lines) == 2


async def test_build_doc_letra_explicita_inexistente_raise(tmp_path: Path):
    audio = tmp_path / "cancion.mp3"
    audio.write_bytes(b"x")
    with pytest.raises(SyncError, match="Letra no encontrada"):
        await build_sync_document(audio, tmp_path / "nope.lrc")


async def test_build_doc_sin_letra_y_sin_whisper_raise(tmp_path: Path):
    audio = tmp_path / "cancion.mp3"
    audio.write_bytes(b"x")
    with pytest.raises(SyncError, match="--whisper"):
        await build_sync_document(audio)


async def test_build_doc_whisper_sin_letra_transcribe(tmp_path: Path, monkeypatch):
    import youber.sync.aligner as aligner

    async def fake_transcribe(_audio, model_size="small", language=None):
        return [
            SimpleNamespace(start=0.0, end=1.0, text="hola"),
            SimpleNamespace(start=1.0, end=2.0, text="mundo"),
        ]

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    monkeypatch.setattr(aligner, "transcribe_segments", fake_transcribe)
    audio = tmp_path / "cancion.mp3"
    audio.write_bytes(b"x")
    doc = await build_sync_document(audio, whisper=True, model="base")
    assert doc.source == "whisper"
    assert doc.lines[0].text == "hola"


# ---------------------------------------------------------------------------
# Presets de estilo
# ---------------------------------------------------------------------------


def test_preset_clean_por_defecto():
    style = subtitle_style_preset()
    assert style == subtitle_style_preset("clean")


def test_preset_box_tiene_caja():
    style = subtitle_style_preset("box")
    assert style.border_style == 3
    assert style.back_colour is not None


def test_preset_desconocido_raise():
    with pytest.raises(SyncError, match="Estilo de subtítulos desconocido"):
        subtitle_style_preset("glitch")


def test_presets_devuelven_copias():
    first = subtitle_style_preset("clean")
    first.font_size = 99
    assert subtitle_style_preset("clean").font_size != 99
    assert set(SUBTITLE_STYLE_PRESETS) >= {"clean", "classic", "box", "minimal"}


# ---------------------------------------------------------------------------
# youber-produce --sync
# ---------------------------------------------------------------------------


class _FakeAdapterOk:
    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir

    async def produce(self, plan):
        if plan.output_path is not None:
            plan.output_path.write_bytes(b"fake-mp4")
        return SimpleNamespace(
            success=True,
            output_path=plan.output_path,
            duration=10.0,
            resolution=(640, 360),
            error=None,
        )


async def test_produce_sync_ok(tmp_path: Path, monkeypatch):
    import youber.montage.cli as cli

    monkeypatch.setattr(cli, "OpenMontageAdapter", _FakeAdapterOk)

    track_file = tmp_path / "cancion.mp3"
    track_file.write_bytes(b"fake-audio")

    class FakeLibrary:
        def __init__(self, library_dir: str | Path):
            self.library_dir = library_dir

        def get(self, query):
            return None

        def search(self, text=None, **kwargs):
            return [SimpleNamespace(file_path=track_file, title="Tema", artist="Banda")]

        def close(self):
            return None

    monkeypatch.setattr("youber.music.library.MusicLibrary", FakeLibrary)

    calls: dict = {}

    async def fake_sync(video, audio, output=None, **kwargs):
        calls["video"] = Path(video)
        calls["audio"] = Path(audio)
        calls["kwargs"] = kwargs
        Path(output).write_bytes(b"final")
        return SimpleNamespace(
            output_path=Path(output), duration=9.5, resolution=(640, 360)
        )

    monkeypatch.setattr(
        "youber.sync.pipeline.sync_video_with_track", fake_sync
    )

    out_file = tmp_path / "final.mp4"
    args = cli.build_parser().parse_args(
        [
            "--topic", "Python tutorial", "--pipeline", "screen-demo",
            "--track", "Mi cancion", "--sync", "--style", "box",
            "-o", str(out_file),
        ]
    )
    code = await cli._run_produce(args)
    assert code == 0
    assert calls["audio"] == track_file
    assert calls["kwargs"]["add_audio"] is True
    assert calls["kwargs"]["style"].border_style == 3
    assert calls["kwargs"]["lyrics_file"] is None


async def test_produce_sync_sin_track_devuelve_1(tmp_path: Path, monkeypatch):
    import youber.montage.cli as cli

    monkeypatch.setattr(cli, "OpenMontageAdapter", _FakeAdapterOk)
    out_file = tmp_path / "final.mp4"
    args = cli.build_parser().parse_args(
        ["--topic", "Python tutorial", "--sync", "-o", str(out_file)]
    )
    code = await cli._run_produce(args)
    assert code == 1


async def test_produce_sin_sync_no_toca_catalogo(tmp_path: Path, monkeypatch):
    import youber.montage.cli as cli

    monkeypatch.setattr(cli, "OpenMontageAdapter", _FakeAdapterOk)
    out_file = tmp_path / "final.mp4"
    args = cli.build_parser().parse_args(
        ["--topic", "Python tutorial", "-o", str(out_file)]
    )
    code = await cli._run_produce(args)
    assert code == 0
    assert out_file.exists()


# ---------------------------------------------------------------------------
# youber-workflow --sync --upload
# ---------------------------------------------------------------------------


async def test_workflow_sync_y_upload(tmp_path: Path, monkeypatch):
    import youber.cli.workflow_cli as wf

    track_file = tmp_path / "cancion.mp3"
    track_file.write_bytes(b"fake-audio")

    class FakeLibrary:
        def __init__(self, library_dir: str | Path):
            self.library_dir = library_dir

        def get(self, query):
            return None

        def search(self, text=None, **kwargs):
            return [
                SimpleNamespace(file_path=track_file, title="Tema", artist="Banda")
            ]

        def close(self):
            return None

    async def fake_gen(path: str, duration: int = 30) -> str:
        Path(path).write_bytes(b"x")
        return path

    async def fake_mix(video_path, music_path, output_path, **kwargs):
        Path(output_path).write_bytes(b"x")
        return str(output_path)

    sync_calls: dict = {}

    async def fake_sync(video, audio, output=None, **kwargs):
        sync_calls["audio"] = Path(audio)
        sync_calls["kwargs"] = kwargs
        return SimpleNamespace(output_path=Path(output), duration=6.0, resolution=(1280, 720))

    upload_calls: dict = {}

    async def fake_upload(video_path, *, title, description, tags, privacy):
        upload_calls.update(
            video=Path(video_path), title=title, tags=tags, privacy=privacy
        )
        return "https://youtu.be/abc123"

    monkeypatch.setattr(wf, "MusicLibrary", FakeLibrary)
    monkeypatch.setattr(wf, "generate_test_video", fake_gen)
    monkeypatch.setattr(wf, "generate_test_music", fake_gen)
    monkeypatch.setattr(wf, "add_background_music", fake_mix)
    monkeypatch.setattr(wf, "sync_video_with_track", fake_sync)
    monkeypatch.setattr(wf, "_upload_video", fake_upload)

    result = await wf.run_workflow(
        channel_ref="@python",
        output_dir=str(tmp_path),
        duration=6,
        demo=True,
        track="Mi cancion",
        sync_lyrics=True,
        style="box",
        upload=True,
        privacy="unlisted",
    )

    assert sync_calls["audio"] == track_file
    assert sync_calls["kwargs"]["add_audio"] is False
    assert sync_calls["kwargs"]["style"].border_style == 3
    assert upload_calls["privacy"] == "unlisted"
    assert upload_calls["video"].name.endswith(".mp4")
    assert result["synced"] is True
    assert result["subtitles_style"] == "box"
    assert result["upload_url"] == "https://youtu.be/abc123"


async def test_workflow_track_no_encontrado_raise(tmp_path: Path, monkeypatch):
    import youber.cli.workflow_cli as wf

    class FakeLibrary:
        def __init__(self, library_dir: str | Path):
            self.library_dir = library_dir

        def get(self, query):
            return None

        def search(self, text=None, **kwargs):
            return []

        def close(self):
            return None

    async def fake_gen(path: str, duration: int = 30) -> str:
        Path(path).write_bytes(b"x")
        return path

    monkeypatch.setattr(wf, "MusicLibrary", FakeLibrary)
    monkeypatch.setattr(wf, "generate_test_video", fake_gen)
    monkeypatch.setattr(wf, "generate_test_music", fake_gen)
    with pytest.raises(RuntimeError, match="Pista no encontrada"):
        await wf.run_workflow(
            channel_ref="@python", output_dir=str(tmp_path), demo=True, track="nada"
        )


# ---------------------------------------------------------------------------
# Integración real: vídeo mudo + canción + letra (FFmpeg)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requiere FFmpeg en el sistema")
async def test_sync_video_with_track_integracion_real(tmp_path: Path):
    from youber.audio._ffmpeg import run_command

    # Vídeo mudo 4s (como el montaje de youber-produce).
    video = tmp_path / "silent.mp4"
    await run_command(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24",
            "-t", "4", "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-an", str(video),
        ]
    )
    # Canción sintética 4s.
    audio = tmp_path / "cancion.mp3"
    await run_command(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:a", "libmp3lame", str(audio),
        ]
    )
    lyrics = tmp_path / "cancion.txt"
    lyrics.write_text("linea uno\nlinea dos\nlinea tres", encoding="utf-8")
    output = tmp_path / "final.mp4"

    result = await sync_video_with_track(
        video, audio, output=output, lyrics_file=lyrics, style=subtitle_style_preset("clean")
    )
    assert output.is_file()
    assert result.output_path == output
    assert result.duration == pytest.approx(4.0, abs=0.8)
    # El vídeo final tiene pista de audio (la canción sustituyó al mudo).
    probe = await run_command(
        [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0", str(output),
        ]
    )
    assert probe.stdout.strip() != ""
