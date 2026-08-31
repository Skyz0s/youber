"""Tests del catálogo de música (models, database, scanner, matcher, library, cli)."""

import asyncio
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from youber.music.cli import _mood, build_parser
from youber.music.database import MusicDatabase
from youber.music.library import MusicLibrary
from youber.music.matcher import score_track, search_tracks, suggest_tracks
from youber.music.models import Mood, Track
from youber.music.scanner import file_hash, scan_directory

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def make_track(
    title: str = "Canción",
    moods: list[Mood] | None = None,
    favorite: bool = False,
    usage_count: int = 0,
    genre: str | None = "pop",
    bpm: int | None = 120,
) -> Track:
    return Track(
        id="id-" + title.lower().replace(" ", "-"),
        file_path=Path(f"/tmp/{title}.mp3"),
        title=title,
        artist="Artista",
        duration=180.0,
        genre=genre,
        moods=moods or [],
        bpm=bpm,
        favorite=favorite,
        usage_count=usage_count,
        file_hash="abc123",
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_mood_values():
    assert Mood.ENERGETIC == "energética"
    assert Mood.RELAXING == "relajante"
    assert Mood.EPIC == "épica"
    assert Mood.FOCUSED == "productiva"
    assert Mood.CUSTOM == "personalizada"


def test_track_defaults():
    track = make_track()
    assert track.moods == []
    assert track.favorite is False
    assert track.usage_count == 0
    assert track.last_used is None
    assert track.added_at is not None


def test_track_validation():
    with pytest.raises(ValidationError):
        Track(id="x", file_path=Path("a.mp3"), title="", duration=-1, file_hash="h")


# ---------------------------------------------------------------------------
# Database (SQLite)
# ---------------------------------------------------------------------------


def test_database_crud(tmp_path: Path):
    db = MusicDatabase(tmp_path / "catalogo.db")
    track = make_track("Test")
    db.add_track(track)

    assert db.count() == 1
    loaded = db.get_track(track.id)
    assert loaded is not None
    assert loaded.title == "Test"
    assert loaded.file_path == track.file_path

    assert db.get_by_path("/tmp/Test.mp3") is not None
    assert db.get_by_path("/tmp/No.mp3") is None

    db.delete_track(track.id)
    assert db.count() == 0
    assert db.delete_track(track.id) is False


def test_database_update_preserves_moods(tmp_path: Path):
    db = MusicDatabase(tmp_path / "c.db")
    track = make_track("T", moods=[Mood.HAPPY])
    db.add_track(track)

    track.title = "Título nuevo"
    db.update_track(track)

    loaded = db.get_track(track.id)
    assert loaded is not None
    assert loaded.title == "Título nuevo"
    assert loaded.moods == [Mood.HAPPY]


def test_database_usage_and_favorite(tmp_path: Path):
    db = MusicDatabase(tmp_path / "c.db")
    db.add_track(make_track("Uso"))

    assert db.set_favorite("id-uso", True) is True
    assert db.get_track("id-uso").favorite is True  # type: ignore[union-attr]
    assert db.set_favorite("no-existe", True) is False

    assert db.record_usage("id-uso") is True
    loaded = db.get_track("id-uso")
    assert loaded is not None
    assert loaded.usage_count == 1
    assert loaded.last_used is not None
    assert db.record_usage("no-existe") is False


def test_database_new_id_unique():
    assert MusicDatabase.new_id() != MusicDatabase.new_id()


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def test_scan_directory(tmp_path: Path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.wav").write_bytes(b"y")
    (tmp_path / "sub" / "nota.txt").write_text("hola", encoding="utf-8")
    (tmp_path / "video.mp4").write_bytes(b"z")

    files = scan_directory(tmp_path)
    names = {path.name for path in files}
    assert names == {"a.mp3", "b.wav"}


def test_scan_directory_invalid():
    with pytest.raises(ValueError):
        scan_directory("/no/existe")


def test_file_hash_stable(tmp_path: Path):
    path = tmp_path / "a.mp3"
    path.write_bytes(b"contenido" * 1000)
    assert file_hash(path) == file_hash(path)
    assert len(file_hash(path)) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


def test_search_by_mood():
    happy = make_track("Feliz", moods=[Mood.HAPPY])
    sad = make_track("Triste", moods=[Mood.SAD])
    result = search_tracks([happy, sad], mood=Mood.HAPPY)
    assert result == [happy]


def test_search_by_text_and_genre():
    tracks = [
        make_track("Amanecer", genre="ambient"),
        make_track("Tormenta", genre="metal"),
    ]
    assert search_tracks(tracks, text="amanecer") == [tracks[0]]
    assert search_tracks(tracks, genre="METAL") == [tracks[1]]
    assert search_tracks(tracks, text="no-existe") == []


def test_search_by_favorite_and_bpm():
    fav = make_track("Fav", favorite=True, bpm=90)
    nofav = make_track("NoFav", bpm=140)
    assert search_tracks([fav, nofav], favorite=True) == [fav]
    assert search_tracks([fav, nofav], bpm_min=100, bpm_max=150) == [nofav]


def test_score_track_mood_and_favorite():
    base = make_track("Base")
    happy = make_track("Feliz", moods=[Mood.HAPPY])
    fav = make_track("Fav", favorite=True)
    assert score_track(base, mood=Mood.HAPPY) == 0.0
    assert score_track(happy, mood=Mood.HAPPY) == 5.0
    assert score_track(fav, mood=Mood.HAPPY) == 2.0


def test_suggest_tracks_orders_by_score():
    happy_used = make_track("Feliz usada", moods=[Mood.HAPPY], usage_count=10)
    happy_fav = make_track("Feliz fav", moods=[Mood.HAPPY], favorite=True)
    other = make_track("Otra")
    suggested = suggest_tracks([other, happy_used, happy_fav], mood=Mood.HAPPY, limit=2)
    assert suggested[0] == happy_fav  # mood + favorita
    assert suggested[1] == happy_used  # mood, aunque usada


# ---------------------------------------------------------------------------
# Library (integración con database + scanner)
# ---------------------------------------------------------------------------


def test_library_scan_removes_missing(tmp_path: Path, monkeypatch):
    """Sin FFmpeg: se mockea probe_track; los ficheros que desaparecen se retiran."""
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / "a.mp3").write_bytes(b"a")
    (music_dir / "b.mp3").write_bytes(b"b")

    library = MusicLibrary(music_dir)

    async def fake_probe(path):
        from youber.music.scanner import file_hash as _hash

        return Track(
            id=MusicDatabase.new_id(),
            file_path=Path(path),
            title=Path(path).stem,
            artist="Artista",
            duration=1.0,
            file_hash=_hash(path),
        )

    monkeypatch.setattr("youber.music.scanner.probe_track", fake_probe)
    asyncio.run(library.scan())
    assert library.count() == 2
    assert library.search(text="a") != []

    # Desaparece un fichero → se elimina del catálogo
    (music_dir / "b.mp3").unlink()
    asyncio.run(library.scan())
    assert library.count() == 1


def test_library_suggest_and_favorite(tmp_path: Path):
    library = MusicLibrary(tmp_path / "lib", db_path=tmp_path / "c.db")
    track = make_track("Sugerida", moods=[Mood.RELAXING])
    library.db.add_track(track)

    suggestions = library.suggest(mood=Mood.RELAXING, limit=3)
    assert [t.id for t in suggestions] == [track.id]

    assert library.mark_favorite(track.id, True) is True
    assert library.get(track.id).favorite is True  # type: ignore[union-attr]
    assert library.record_usage(track.id) is True
    assert library.get(track.id).usage_count == 1  # type: ignore[union-attr]
    library.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_mood_parser():
    import argparse

    assert _mood("relajante") == Mood.RELAXING
    assert _mood("ENERGETIC") == Mood.ENERGETIC
    assert _mood(None) is None
    with pytest.raises(argparse.ArgumentTypeError):
        _mood("no-existe")


def test_cli_parser_commands():
    parser = build_parser()
    assert parser.parse_args(["scan"]).command == "scan"
    assert parser.parse_args(["list"]).command == "list"
    args = parser.parse_args(["search", "--mood", "épica", "--text", "trailer"])
    assert args.mood == Mood.EPIC
    assert args.text == "trailer"
    args = parser.parse_args(["suggest", "-n", "3"])
    assert args.limit == 3


# ---------------------------------------------------------------------------
# Integración real (solo si FFmpeg está instalado)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
async def test_integration_scan_real_audio(tmp_path: Path):
    """Genera 2 MP3 reales con FFmpeg y verifica el escaneo de verdad."""
    from youber.audio._ffmpeg import run_command

    music_dir = tmp_path / "music"
    music_dir.mkdir()
    for freq in (440, 523):
        await run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={freq}:duration=1",
                "-c:a",
                "libmp3lame",
                str(music_dir / f"tono_{freq}.mp3"),
            ]
        )

    library = MusicLibrary(music_dir, db_path=tmp_path / "c.db")
    summary = await library.scan()
    assert summary["added"] == 2
    assert library.count() == 2

    tracks = library.all()
    assert all(track.duration > 0.9 for track in tracks)
    assert all(track.file_hash for track in tracks)

    # Re-escaneo: sin cambios
    summary2 = await library.scan()
    assert summary2["unchanged"] == 2
    library.close()
