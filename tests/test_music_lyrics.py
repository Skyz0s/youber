"""Tests del análisis de letras (lyrics_analyzer) e integración con el catálogo.

Todo offline y determinista: léxicos propios + ficheros temporales, sin red.
"""

import asyncio
from pathlib import Path

import pytest

from youber.music.database import MusicDatabase
from youber.music.library import MusicLibrary
from youber.music.lyrics_analyzer import (
    EMOTION_LEXICON,
    LyricsAnalysis,
    LyricsAnalyzer,
    create_default_analyzer,
    read_lyrics_file,
)
from youber.music.matcher import score_track, search_tracks, suggest_tracks
from youber.music.models import Mood, Track
from youber.music.scanner import file_hash, probe_track

LYRICS_HAPPY_ES = """
Hoy me siento muy feliz y alegre
Bailando bajo el sol brillante
Mi corazón late fuerte de emoción
Nada puede apagar esta alegría
"""

LYRICS_SAD_EN = """
I'm feeling so lonely and blue
Tears are falling like rain from the skies
My heart is broken and I don't know what to do
This sadness won't go away
"""

LYRICS_MYSTERY_ES = """
En la noche oscura y silenciosa
Las sombras bailan sin hacer ruido
Un susurro llega desde el pasado
Nada es lo que parece ser
"""


def make_track(
    title: str = "Canción",
    artist: str | None = "Artista",
    lyrical_themes: dict[str, float] | None = None,
    lyrical_sentiment: str = "neutral",
) -> Track:
    return Track(
        id="id-" + title.lower().replace(" ", "-"),
        file_path=Path(f"/tmp/{title}.mp3"),
        title=title,
        artist=artist,
        duration=180.0,
        file_hash="abc123",
        lyrical_themes=lyrical_themes or {},
        lyrical_sentiment=lyrical_sentiment,
    )


# ---------------------------------------------------------------------------
# Análisis de letras
# ---------------------------------------------------------------------------


def test_analyze_happy_spanish():
    analysis = LyricsAnalyzer().analyze_lyrics(LYRICS_HAPPY_ES)
    assert analysis.language == "es"
    assert analysis.sentiment == "positive"
    assert analysis.dominant_theme == "felicidad"
    assert analysis.confidence > 0
    assert analysis.word_count > 0
    assert "feliz" in analysis.top_words


def test_analyze_sad_english():
    analysis = LyricsAnalyzer().analyze_lyrics(LYRICS_SAD_EN)
    assert analysis.language == "en"
    assert analysis.sentiment == "negative"
    assert "tristeza" in analysis.themes


def test_analyze_mystery_is_neutral():
    analysis = LyricsAnalyzer().analyze_lyrics(LYRICS_MYSTERY_ES)
    assert analysis.language == "es"
    assert analysis.dominant_theme == "misterio"
    # El misterio no fuerza polaridad positiva ni negativa.
    assert analysis.sentiment == "neutral"


def test_analyze_empty_lyrics():
    analysis = LyricsAnalyzer().analyze_lyrics("   \n  ")
    assert analysis == LyricsAnalysis()
    assert analysis.confidence == 0.0
    assert analysis.themes == {}
    assert analysis.dominant_theme is None
    assert analysis.moods() == []


def test_unknown_language():
    analysis = LyricsAnalyzer().analyze_lyrics("xyz qqq zzz")
    assert analysis.language == "unknown"
    assert analysis.sentiment == "neutral"


def test_theme_weights_bounded_and_sorted():
    analysis = LyricsAnalyzer().analyze_lyrics(LYRICS_HAPPY_ES)
    weights = list(analysis.themes.values())
    assert all(0.0 < weight <= 1.0 for weight in weights)
    assert weights == sorted(weights, reverse=True)


def test_moods_mapping():
    analysis = LyricsAnalyzer().analyze_lyrics(LYRICS_SAD_EN)
    assert Mood.SAD in analysis.moods()
    happy = LyricsAnalyzer().analyze_lyrics(LYRICS_HAPPY_ES)
    assert Mood.HAPPY in happy.moods()


def test_lexicon_is_reasonable():
    """Cada tema del léxico tiene palabras y ninguna vacía."""
    assert {"felicidad", "tristeza", "energia", "calma", "misterio", "amor"} <= set(
        EMOTION_LEXICON
    )
    for words in EMOTION_LEXICON.values():
        assert words


def test_create_default_analyzer():
    assert isinstance(create_default_analyzer(), LyricsAnalyzer)


def test_configurable_analyzer():
    analyzer = LyricsAnalyzer(top_words=2, min_word_length=20)
    analysis = analyzer.analyze_lyrics(LYRICS_HAPPY_ES)
    assert len(analysis.top_words) <= 2
    assert analysis.word_count == 0  # ninguna palabra llega a 20 letras


# ---------------------------------------------------------------------------
# Localización y lectura de ficheros
# ---------------------------------------------------------------------------


def test_read_lyrics_file_encodings(tmp_path: Path):
    utf8 = tmp_path / "utf8.txt"
    utf8.write_bytes(LYRICS_HAPPY_ES.encode("utf-8"))
    assert "feliz" in (read_lyrics_file(utf8) or "")

    latin = tmp_path / "latin.txt"
    latin.write_bytes("canción con acentos: corazón".encode("latin-1"))
    assert "corazón" in (read_lyrics_file(latin) or "")


def test_find_lyrics_file_exact_and_tolerant(tmp_path: Path):
    (tmp_path / "Mi Canción.txt").write_text(LYRICS_HAPPY_ES, encoding="utf-8")
    (tmp_path / "Otra - Otro Artista.txt").write_text(LYRICS_SAD_EN, encoding="utf-8")

    exact = LyricsAnalyzer.find_lyrics_file(make_track("Mi Canción"), tmp_path)
    assert exact is not None and exact.name == "Mi Canción.txt"

    # Sin acentos y con separadores distintos → coincidencia tolerante.
    tolerant = LyricsAnalyzer.find_lyrics_file(make_track("mi cancion"), tmp_path)
    assert tolerant is not None and tolerant.name == "Mi Canción.txt"

    combined = LyricsAnalyzer.find_lyrics_file(
        make_track("Otra", artist="Otro Artista"), tmp_path
    )
    assert combined is not None and combined.name == "Otra - Otro Artista.txt"

    assert LyricsAnalyzer.find_lyrics_file(make_track("Inexistente"), tmp_path) is None


def test_find_lyrics_file_missing_dir(tmp_path: Path):
    assert LyricsAnalyzer.find_lyrics_file(make_track(), tmp_path / "no-existe") is None


def test_analyze_track_lyrics(tmp_path: Path):
    (tmp_path / "Canción.txt").write_text(LYRICS_SAD_EN, encoding="utf-8")
    analysis = LyricsAnalyzer().analyze_track_lyrics(make_track("Canción"), tmp_path)
    assert analysis is not None
    assert analysis.sentiment == "negative"

    missing = LyricsAnalyzer().analyze_track_lyrics(make_track("Sin letra"), tmp_path)
    assert missing is None


# ---------------------------------------------------------------------------
# Persistencia y escaneo
# ---------------------------------------------------------------------------


def test_database_persists_lyrical_fields(tmp_path: Path):
    db = MusicDatabase(tmp_path / "c.db")
    track = make_track("Persistida", lyrical_themes={"amor": 0.8}, lyrical_sentiment="positive")
    db.add_track(track)

    loaded = db.get_track(track.id)
    assert loaded is not None
    assert loaded.lyrical_themes == {"amor": 0.8}
    assert loaded.lyrical_sentiment == "positive"

    loaded.lyrical_themes = {"calma": 0.5}
    loaded.lyrical_sentiment = "neutral"
    db.update_track(loaded)
    again = db.get_track(track.id)
    assert again is not None and again.lyrical_themes == {"calma": 0.5}


def test_database_defaults_without_lyrics(tmp_path: Path):
    db = MusicDatabase(tmp_path / "c.db")
    db.add_track(make_track("Simple"))
    loaded = db.get_track("id-simple")
    assert loaded is not None
    assert loaded.lyrical_themes == {}
    assert loaded.lyrical_sentiment == "neutral"


def test_probe_track_with_lyrics_dir(tmp_path: Path, monkeypatch):
    """probe_track enriquece la pista con el análisis de la letra (sin FFmpeg)."""
    audio = tmp_path / "Tema.mp3"
    audio.write_bytes(b"fake")
    lyrics_dir = tmp_path / "letras"
    lyrics_dir.mkdir()
    (lyrics_dir / "Tema.txt").write_text(LYRICS_HAPPY_ES, encoding="utf-8")

    async def fake_duration(path):
        return 12.5

    async def fake_tags(path):
        return {"title": "Tema", "artist": "Artista"}

    monkeypatch.setattr("youber.music.scanner.probe_duration", fake_duration)
    monkeypatch.setattr("youber.music.scanner._probe_tags", fake_tags)

    track = asyncio.run(
        probe_track(audio, lyrics_dir=lyrics_dir, lyrics_analyzer=LyricsAnalyzer())
    )
    assert track.title == "Tema"
    assert track.duration == 12.5
    assert track.lyrical_themes
    assert track.lyrical_sentiment == "positive"


def test_probe_track_without_lyrics(tmp_path: Path, monkeypatch):
    audio = tmp_path / "Sola.mp3"
    audio.write_bytes(b"fake")

    async def fake_duration(path):
        return 1.0

    async def fake_tags(path):
        return {}

    monkeypatch.setattr("youber.music.scanner.probe_duration", fake_duration)
    monkeypatch.setattr("youber.music.scanner._probe_tags", fake_tags)

    track = asyncio.run(probe_track(audio, lyrics_dir=tmp_path / "nada", lyrics_analyzer=LyricsAnalyzer()))
    assert track.lyrical_themes == {}
    assert track.lyrical_sentiment == "neutral"


def test_library_scan_with_lyrics_dir(tmp_path: Path):
    """scan(lyrics_dir=...) guarda el análisis en la base de datos."""
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / "Tema.mp3").write_bytes(b"audio")
    lyrics_dir = tmp_path / "letras"
    lyrics_dir.mkdir()
    (lyrics_dir / "Tema.txt").write_text(LYRICS_SAD_EN, encoding="utf-8")

    library = MusicLibrary(music_dir, db_path=tmp_path / "c.db")

    async def fake_probe(path, lyrics_dir=None, lyrics_analyzer=None):
        track = Track(
            id="",
            file_path=Path(path),
            title=Path(path).stem,
            artist="Artista",
            duration=1.0,
            file_hash=file_hash(path),
        )
        if lyrics_dir is not None and lyrics_analyzer is not None:
            analysis = lyrics_analyzer.analyze_track_lyrics(track, Path(lyrics_dir))
            if analysis is not None:
                track.lyrical_themes = analysis.themes
                track.lyrical_sentiment = analysis.sentiment
        return track

    import youber.music.scanner as scanner

    original = scanner.probe_track
    scanner.probe_track = fake_probe  # type: ignore[assignment]
    try:
        summary = asyncio.run(library.scan(lyrics_dir=lyrics_dir))
    finally:
        scanner.probe_track = original  # type: ignore[assignment]

    assert summary["added"] == 1
    stored = library.all()[0]
    assert stored.lyrical_sentiment == "negative"
    assert "tristeza" in stored.lyrical_themes

    found = library.search(lyrical_theme="tristeza")
    assert [track.id for track in found] == [stored.id]
    library.close()


def test_library_lyrics_helper(tmp_path: Path):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    lyrics_dir = tmp_path / "letras"
    lyrics_dir.mkdir()
    (lyrics_dir / "Tema.txt").write_text(LYRICS_MYSTERY_ES, encoding="utf-8")

    library = MusicLibrary(music_dir, db_path=tmp_path / "c.db")
    library.db.add_track(make_track("Tema"))
    analysis = library.lyrics("id-tema", lyrics_dir)
    assert analysis is not None and analysis.dominant_theme == "misterio"
    assert library.lyrics("no-existe", lyrics_dir) is None
    library.close()


# ---------------------------------------------------------------------------
# Búsqueda y sugerencias por letra
# ---------------------------------------------------------------------------


def test_search_by_lyrical_theme_and_sentiment():
    sad = make_track("Triste", lyrical_themes={"tristeza": 0.9}, lyrical_sentiment="negative")
    happy = make_track("Feliz", lyrical_themes={"felicidad": 0.7}, lyrical_sentiment="positive")
    plain = make_track("Neutra")

    tracks = [sad, happy, plain]
    assert search_tracks(tracks, lyrical_theme="tristeza") == [sad]
    assert search_tracks(tracks, lyrical_sentiment="positive") == [happy]
    assert search_tracks(tracks, lyrical_sentiment="neutral") == [plain]


def test_score_track_lyrical_bonus():
    base = make_track("Base")
    bonus = make_track("Bonus", lyrical_themes={"calma": 1.0})
    assert score_track(bonus, lyrical_theme="calma") > score_track(base, lyrical_theme="calma")
    # Sin tema pedido, el bonus no altera la puntuación.
    assert score_track(bonus) == score_track(base)


def test_suggest_prefers_matching_lyrics():
    matching = make_track("Coincide", lyrical_themes={"energia": 1.0})
    other = make_track("Otra", lyrical_themes={"calma": 1.0})
    ranked = suggest_tracks([other, matching], lyrical_theme="energia", limit=2)
    assert ranked[0] == matching


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_lyrics_subcommand():
    from youber.music.cli import build_parser

    args = build_parser().parse_args(["lyrics", "abc", "--lyrics-dir", "letras"])
    assert args.command == "lyrics"
    assert args.id == "abc"
    assert args.lyrics_dir == "letras"


def test_cli_search_and_suggest_lyric_options():
    from youber.music.cli import build_parser

    args = build_parser().parse_args(["search", "--lyric-theme", "amor"])
    assert args.lyric_theme == "amor"
    args = build_parser().parse_args(["search", "--lyric-sentiment", "negative"])
    assert args.lyric_sentiment == "negative"
    args = build_parser().parse_args(["suggest", "--lyric-theme", "calma", "-n", "2"])
    assert args.lyric_theme == "calma" and args.limit == 2
    args = build_parser().parse_args(["scan", "--lyrics-dir", "letras"])
    assert args.lyrics_dir == "letras"


def test_cli_lyrics_command_missing_track(tmp_path: Path, capsys, monkeypatch):
    """`lyrics` con un id inexistente sale con error (SystemExit)."""
    from youber.music.cli import run

    args = build_parser_args(tmp_path)
    with pytest.raises(SystemExit):
        run(args)


def build_parser_args(tmp_path: Path):
    from youber.music.cli import build_parser

    lyrics_dir = tmp_path / "letras"
    lyrics_dir.mkdir(exist_ok=True)
    return build_parser().parse_args(
        [
            "--library",
            str(tmp_path / "music"),
            "--db",
            str(tmp_path / "c.db"),
            "lyrics",
            "no-existe",
            "--lyrics-dir",
            str(lyrics_dir),
        ]
    )
