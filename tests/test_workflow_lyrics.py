"""Tests del flujo «metadatos → letras → prompt → vídeo local + canción»."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from youber.cli.workflow_cli import build_parser, run_lyrics_video
from youber.music.models import Track
from youber.research.data_models import ChannelData, VideoData
from youber.video.editor import VideoEditor

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

SAD_TEXT = (
    "La noche cae y el dolor no se va, lágrimas en la soledad, "
    "todo está perdido, adiós, la tristeza me acompaña."
)


def _track(track_id: str, title: str, themes: dict[str, float], sentiment: str) -> Track:
    return Track(
        id=track_id,
        file_path=Path("music") / f"{track_id}.mp3",
        title=title,
        duration=120.0,
        file_hash=f"hash-{track_id}",
        lyrical_themes=themes,
        lyrical_sentiment=sentiment,
    )


TRACKS = [
    _track("sad", "Adiós", {"tristeza": 0.9}, "negative"),
    _track("happy", "Alegría", {"felicidad": 0.9}, "positive"),
]


class FakeLibrary:
    """Catálogo falso (sin SQLite ni audio) para los tests offline."""

    last: FakeLibrary | None = None

    def __init__(self, library_dir: str | Path, db_path: str | Path | None = None) -> None:
        self.library_dir = Path(library_dir)
        self.scanned: str | None = None
        self.closed = False
        FakeLibrary.last = self

    async def scan(self, lyrics_dir: str | Path | None = None) -> dict[str, int]:
        self.scanned = str(lyrics_dir) if lyrics_dir else None
        return {"added": 2, "updated": 0, "unchanged": 0, "removed": 0, "errors": 0}

    def all(self) -> list[Track]:
        return list(TRACKS)

    def count(self) -> int:
        return len(TRACKS)

    def get(self, track_id: str) -> Track | None:
        return next((track for track in TRACKS if track.id == track_id), None)

    def search(self, text: str | None = None) -> list[Track]:
        return [track for track in TRACKS if text and text.lower() in track.title.lower()]

    def close(self) -> None:
        self.closed = True


def _sad_channel() -> ChannelData:
    """Canal sintético con metadatos de tono triste (matching con la letra)."""
    return ChannelData(
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
                description="Un vídeo sobre la tristeza y las lágrimas del adiós.",
                hashtags=["tristeza", "soledad"],
            )
        ],
    )


@pytest.fixture
def offline(monkeypatch, tmp_path: Path):
    """Aísla el flujo: catálogo fake, stock fake y render fake."""
    import youber.cli.workflow_cli as workflow_cli
    import youber.video.stock as stock

    monkeypatch.setattr(workflow_cli, "MusicLibrary", FakeLibrary)
    monkeypatch.setattr(workflow_cli, "demo_channel", _sad_channel)

    async def fake_fetch(scenes, dest_dir, bank="auto", per_scene=1):
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, list[Path]] = {}
        for index, _scene in enumerate(scenes):
            clip = dest_dir / f"clip{index}.mp4"
            clip.write_bytes(b"fake-clip")
            result[f"escena{index + 1}"] = [clip]
        return result

    monkeypatch.setattr(stock, "available", lambda: {"pexels": True, "pixabay": False})
    monkeypatch.setattr(stock, "fetch_clips_for_scenes", fake_fetch)

    rendered: dict[str, object] = {}

    async def fake_render(self, project, output_path, music_path=None):
        rendered["project"] = project
        Path(output_path).write_bytes(b"fake-mp4")
        return str(output_path)

    monkeypatch.setattr(VideoEditor, "render", fake_render)

    async def fake_run(cmd):
        target = Path(cmd[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake")

    monkeypatch.setattr(workflow_cli, "run_command", fake_run)
    return {"rendered": rendered, "tmp": tmp_path}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parser_lyrics_video_flags():
    args = build_parser().parse_args(
        ["--lyrics-video", "--demo", "--topic", "Mi vídeo", "--stock", "pexels"]
    )
    assert args.lyrics_video is True
    assert args.topic == "Mi vídeo"
    assert args.stock == "pexels"
    assert args.clips == []


def test_parser_lyrics_video_defaults():
    args = build_parser().parse_args([])
    assert args.lyrics_video is False
    assert args.stock == "auto"
    assert args.lyrics_dir is None
    assert args.no_render is False


# ---------------------------------------------------------------------------
# Flujo completo (offline)
# ---------------------------------------------------------------------------


async def test_lyrics_video_elige_cancion_y_renderiza(offline) -> None:
    result = await run_lyrics_video(
        demo=True,
        topic="La noche",
        output_dir=str(offline["tmp"] / "out"),
        library_dir=str(offline["tmp"] / "music"),
        lyrics_dir=str(offline["tmp"] / "letras"),
        stock="pexels",
        duration=30,
    )

    # La canción triste gana porque los metadatos del canal son tristes.
    assert result["track"] is not None
    assert result["track"]["id"] == "sad"
    assert "tristeza" in result["themes"]
    assert result["clips"], "el flujo debe usar clips (stock fake)"
    assert result["final_video"] is not None
    assert Path(result["final_video"]).is_file()

    project = offline["rendered"]["project"]
    assert project.music_track_id == "sad"
    assert project.clips
    assert result["track"]["title"] in result["prompt"]

    # El catálogo se escaneó con el directorio de letras y quedó cerrado.
    library = FakeLibrary.last
    assert library is not None
    assert library.scanned == str(offline["tmp"] / "letras")
    assert library.closed is True


async def test_lyrics_video_sin_stock_genera_clip_sintetico(offline) -> None:
    result = await run_lyrics_video(
        demo=True,
        topic="Demo",
        output_dir=str(offline["tmp"] / "out2"),
        library_dir=str(offline["tmp"] / "music2"),
        stock="none",
        duration=10,
    )
    assert result["clips"]
    assert any("clip_base" in clip for clip in result["clips"])


async def test_lyrics_video_no_render_exporta_brief_y_guion(offline) -> None:
    result = await run_lyrics_video(
        demo=True,
        topic="Solo guion",
        output_dir=str(offline["tmp"] / "out3"),
        library_dir=str(offline["tmp"] / "music3"),
        stock="none",
        render=False,
    )
    assert result["final_video"] is None
    assert Path(result["brief"]).is_file()
    assert Path(result["script"]).is_file()
    assert "PROMPT DE PRODUCCIÓN" in result["prompt"]


async def test_lyrics_video_track_forzado(offline) -> None:
    result = await run_lyrics_video(
        demo=True,
        topic="Forzado",
        output_dir=str(offline["tmp"] / "out4"),
        library_dir=str(offline["tmp"] / "music4"),
        stock="pexels",
        track="happy",
        render=False,
    )
    assert result["track"] is not None
    assert result["track"]["id"] == "happy"
    assert "a mano" in result["track"]["reason"]


async def test_lyrics_video_track_inexistente_falla(offline) -> None:
    with pytest.raises(RuntimeError):
        await run_lyrics_video(
            demo=True,
            topic="Nope",
            output_dir=str(offline["tmp"] / "out5"),
            library_dir=str(offline["tmp"] / "music5"),
            track="no-existe",
            render=False,
        )


# ---------------------------------------------------------------------------
# Integración real (FFmpeg): biblioteca + letras + render
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requiere FFmpeg/ffprobe")
async def test_lyrics_video_integracion_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    """Con catálogo real (2 pistas + letras), renderiza el vídeo con FFmpeg."""
    import youber.cli.workflow_cli as workflow_cli

    library_dir = tmp_path / "music"
    library_dir.mkdir()
    lyrics_dir = tmp_path / "letras"
    lyrics_dir.mkdir()
    for name, freq in (("Adios", 220), ("Alegria", 660)):
        await workflow_cli.run_command(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=8",
                "-c:a", "libmp3lame", str(library_dir / f"{name}.mp3"),
            ]
        )
    (lyrics_dir / "Adios.txt").write_text(SAD_TEXT, encoding="utf-8")
    (lyrics_dir / "Alegria.txt").write_text(
        "Hoy es un día feliz, alegría y risas, celebramos el amor.", encoding="utf-8"
    )

    monkeypatch.setattr(workflow_cli, "demo_channel", _sad_channel)
    result = await run_lyrics_video(
        demo=True,
        topic="La noche",
        output_dir=str(tmp_path / "out"),
        library_dir=str(library_dir),
        lyrics_dir=str(lyrics_dir),
        stock="none",
        duration=6,
    )
    assert result["track"] is not None
    assert Path(result["final_video"]).is_file()
    assert Path(result["final_video"]).stat().st_size > 1000
