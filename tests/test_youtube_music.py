"""Tests del cliente de YouTube Music y el importador CSV (sin red: ytmusicapi mockeado)."""

from pathlib import Path

import pytest

from youber.music.database import MusicDatabase
from youber.music.importers import (
    ImportResult,
    _parse_duration,
    import_csv,
    read_csv,
)
from youber.music.models import TrackSource
from youber.music.youtube_music import (
    YouTubeMusicClient,
    _track_from_ytmusic,
    import_ytmusic_library,
)
from youber.music.youtube_music import (
    _parse_duration as _parse_yt_duration,
)

SONG_ID = "dQw4w9WgXcQ"


class FakeYTMusic:
    """Fake de ytmusicapi.YTMusic: search/get_song/add_playlist_items/biblioteca."""

    def __init__(self, headers_file=None):
        self.headers_file = headers_file
        self.search_calls: list[tuple[str, str]] = []
        self.added: list[tuple[str, list[str]]] = []
        self.results: list[dict] = [
            {
                "videoId": SONG_ID,
                "title": "Never Gonna Give You Up",
                "artists": [{"name": "Rick Astley"}],
                "duration": 213,
                "album": {"name": "Whenever You Need Somebody"},
                "thumbnails": [{"url": "https://i.ytimg.com/vi/x/hqdefault.jpg"}],
            }
        ]
        self.library: list[dict] = [
            {
                "videoId": "lib3",
                "title": "Guardada Solo",
                "artists": [{"name": "Artista E"}],
                "duration": 210,
            },
            {
                "videoId": "lib4",
                "title": "Otra Guardada",
                "artists": [{"name": "Artista F"}],
                "duration": 195,
            },
        ]
        self.liked: list[dict] = [
            {
                "videoId": "lib1",
                "title": "Canción Guardada",
                "artists": [{"name": "Artista B"}],
                "duration": "3:45",
                "album": {"name": "Álbum B"},
            },
            {
                "videoId": "lib2",
                "title": "Otra Guardada",
                "artists": [{"name": "Artista C"}],
                "duration": 200,
            },
        ]
        self.playlists: list[dict] = [
            {"playlistId": "pl1", "title": "Mi Playlist"},
        ]
        self.playlist_songs: list[dict] = [
            {
                "videoId": "plsong1",
                "title": "Canción de Playlist",
                "artists": [{"name": "Artista D"}],
                "duration": 180,
            }
        ]
        self.uploads: list[dict] = [
            {
                "videoId": "up1",
                "title": "Subida Uno",
                "artists": [{"name": "Artista U"}],
                "duration": 240,
            },
            {
                "videoId": "up2",
                "title": "Subida Dos",
                "artists": [{"name": "Artista V"}],
                "duration": 260,
            },
        ]
        self.fail_liked: bool = False

    def search(self, query: str, filter: str = "songs"):
        self.search_calls.append((query, filter))
        return self.results

    def add_playlist_items(self, playlist_id: str, song_ids: list[str]):
        self.added.append((playlist_id, song_ids))

    def get_song(self, song_id: str):
        return {
            "videoId": song_id,
            "title": "Never Gonna Give You Up",
            "artist": {"name": "Rick Astley"},
            "duration": 213,
            "album": {"name": "Whenever You Need Somebody"},
        }

    def get_liked_songs(self, limit=500):
        if self.fail_liked:
            raise RuntimeError("sesión caducada (página Sign in)")
        return self.liked

    def get_library_songs(self, limit=500):
        return self.library

    def get_library_playlists(self, limit=100):
        return self.playlists

    def get_library_upload_songs(self, limit=500):
        return self.uploads

    def get_playlist(self, playlist_id: str):
        return {"id": playlist_id, "title": "Mi Playlist", "tracks": self.playlist_songs}


@pytest.fixture
def fake_ytmusic(monkeypatch):
    fake = FakeYTMusic()
    calls: list[tuple] = []

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        # Registrar el headers_file que recibe YTMusic(...) en cada llamada.
        fake.headers_file = args[0] if args else kwargs.get("headers_file")
        return fake

    monkeypatch.setattr("youber.music.youtube_music.YTMusic", factory)
    fake.calls = calls
    return fake


# ---------------------------------------------------------------------------
# YouTubeMusicClient
# ---------------------------------------------------------------------------


def test_init_with_headers_file(tmp_path: Path, fake_ytmusic):
    headers = tmp_path / "headers.json"
    headers.write_text("{}", encoding="utf-8")
    client = YouTubeMusicClient(headers_file=str(headers))
    assert client.ytmusic.headers_file == str(headers)


def test_init_uses_default_headers_if_exists(tmp_path: Path, monkeypatch, fake_ytmusic):
    headers = tmp_path / "ytmusic_headers.json"
    headers.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("youber.music.youtube_music.DEFAULT_HEADERS_FILE", headers)
    client = YouTubeMusicClient()
    assert client.ytmusic.headers_file == str(headers)


def test_init_anonymous_without_headers(tmp_path: Path, monkeypatch, fake_ytmusic):
    monkeypatch.setattr(
        "youber.music.youtube_music.DEFAULT_HEADERS_FILE", tmp_path / "no-existe.json"
    )
    client = YouTubeMusicClient()
    assert client.ytmusic.headers_file is None


async def test_search_song_found(fake_ytmusic):
    client = YouTubeMusicClient()
    result = await client.search_song("Never Gonna Give You Up", "Rick Astley")
    assert result is not None
    assert result["id"] == SONG_ID
    assert result["title"] == "Never Gonna Give You Up"
    assert result["artist"] == "Rick Astley"
    assert result["duration"] == 213
    assert result["album"] == "Whenever You Need Somebody"
    assert result["thumbnail"].startswith("https://")


async def test_search_song_not_found(fake_ytmusic):
    fake_ytmusic.results = []
    client = YouTubeMusicClient()
    result = await client.search_song("No Existe", "Nadie")
    assert result is None


async def test_add_to_library(fake_ytmusic):
    client = YouTubeMusicClient()
    ok = await client.add_to_library(SONG_ID)
    assert ok is True
    assert fake_ytmusic.added == [("LM", [SONG_ID])]


async def test_add_to_library_fails(fake_ytmusic, monkeypatch):
    def boom(playlist_id, song_ids):
        raise RuntimeError("no auth")

    fake_ytmusic.add_playlist_items = boom
    client = YouTubeMusicClient()
    assert await client.add_to_library(SONG_ID) is False


# ---------------------------------------------------------------------------
# Biblioteca personal (requiere headers) + importación
# ---------------------------------------------------------------------------


def _authed_client(tmp_path: Path, monkeypatch) -> YouTubeMusicClient:
    headers = tmp_path / "headers.json"
    headers.write_text("{}", encoding="utf-8")
    return YouTubeMusicClient(headers_file=str(headers))


async def test_ytmusic_library_methods(fake_ytmusic, tmp_path: Path):
    client = _authed_client(tmp_path, None)
    assert client.authenticated is True
    liked = await client.liked_songs()
    assert len(liked) == 2
    assert liked[0]["videoId"] == "lib1"
    library = await client.library_songs()
    assert len(library) == 2
    assert library[0]["videoId"] == "lib3"
    uploads = await client.upload_songs()
    assert len(uploads) == 2
    assert uploads[0]["videoId"] == "up1"
    playlists = await client.library_playlists()
    assert playlists[0]["playlistId"] == "pl1"
    tracks = await client.playlist_tracks("pl1")
    assert tracks[0]["videoId"] == "plsong1"


async def test_ytmusic_anonymous(fake_ytmusic, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "youber.music.youtube_music.DEFAULT_HEADERS_FILE", tmp_path / "no.json"
    )
    client = YouTubeMusicClient()
    assert client.authenticated is False


async def test_import_ytmusic_library(fake_ytmusic, tmp_path: Path):
    db = MusicDatabase(tmp_path / "catalogo.db")
    client = _authed_client(tmp_path, None)
    summary = await import_ytmusic_library(client=client, db=db)
    # liked (2) + library (2) + uploads (2) + playlist (1) = 7.
    assert summary["added"] == 7
    assert summary["total"] == 7
    assert "liked" in summary["sources"]
    assert "uploads" in summary["sources"]
    assert "playlists" in summary["sources"]
    assert db.count() == 7

    track = db.get_by_external_id(TrackSource.YOUTUBE, "lib1")
    assert track is not None
    assert track.title == "Canción Guardada"
    assert track.artist == "Artista B"
    assert track.album == "Álbum B"
    assert track.duration == 225.0  # "3:45" -> segundos
    assert track.source == TrackSource.YOUTUBE

    upload = db.get_by_external_id(TrackSource.YOUTUBE, "up1")
    assert upload is not None
    assert upload.title == "Subida Uno"


async def test_import_ytmusic_library_idempotente(fake_ytmusic, tmp_path: Path):
    db = MusicDatabase(tmp_path / "catalogo.db")
    client = _authed_client(tmp_path, None)
    first = await import_ytmusic_library(client=client, db=db)
    assert first["added"] == 7
    second = await import_ytmusic_library(client=client, db=db)
    assert second["added"] == 0
    assert second["skipped"] == 7
    assert db.count() == 7


async def test_import_ytmusic_library_fuente_caida_no_tumba(fake_ytmusic, tmp_path: Path):
    """Si una fuente falla (p. ej. sesión caducada en Me gusta), el resto importa."""
    db = MusicDatabase(tmp_path / "catalogo.db")
    client = _authed_client(tmp_path, None)
    fake_ytmusic.fail_liked = True
    summary = await import_ytmusic_library(client=client, db=db)
    # liked falla, pero library + uploads + playlist sí importan (2+2+1=5).
    assert summary["added"] == 5
    assert "liked" not in summary["sources"]
    assert "uploads" in summary["sources"]


async def test_import_ytmusic_library_todo_caido(fake_ytmusic, tmp_path: Path):
    """Si TODAS las fuentes fallan, avisa de sesión caducada."""
    db = MusicDatabase(tmp_path / "catalogo.db")
    client = _authed_client(tmp_path, None)
    fake_ytmusic.fail_liked = True
    fake_ytmusic.library = []
    fake_ytmusic.liked = []
    fake_ytmusic.uploads = []
    fake_ytmusic.playlists = []
    with pytest.raises(RuntimeError, match="sesión puede haber caducado"):
        await import_ytmusic_library(client=client, db=db)


async def test_import_ytmusic_library_sin_headers(fake_ytmusic, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "youber.music.youtube_music.DEFAULT_HEADERS_FILE", tmp_path / "no.json"
    )
    client = YouTubeMusicClient()
    with pytest.raises(RuntimeError, match="autenticar"):
        await import_ytmusic_library(client=client)


def test_track_from_ytmusic():
    track = _track_from_ytmusic(
        {
            "videoId": "abc123",
            "title": "Canción",
            "artists": [{"name": "Artista"}],
            "album": {"name": "Álbum"},
            "duration": "2:30",
        }
    )
    assert track.external_id == "abc123"
    assert track.duration == 150.0
    assert track.file_hash == "cloud:youtube:abc123"


def test_parse_duration_ytmusic():
    assert _parse_yt_duration("3:45") == 225.0
    assert _parse_yt_duration(200) == 200.0
    assert _parse_yt_duration("1:02:03") == 3723.0
    assert _parse_yt_duration(None) is None
    assert _parse_yt_duration("nope") is None


async def test_get_song_info(fake_ytmusic):
    client = YouTubeMusicClient()
    info = await client.get_song_info(SONG_ID)
    assert info["id"] == SONG_ID
    assert info["title"] == "Never Gonna Give You Up"
    assert info["artist"] == "Rick Astley"
    assert info["duration"] == 213
    assert info["album"] == "Whenever You Need Somebody"


# ---------------------------------------------------------------------------
# Importador CSV
# ---------------------------------------------------------------------------


def test_read_csv(tmp_path: Path):
    csv_path = tmp_path / "catalogo.csv"
    # BOM para comprobar utf-8-sig
    csv_path.write_bytes(
        "\ufeffTítulo,Artista,Álbum,Duración\n"
        "Canción Uno,Artista Uno,Álbum Uno,3:45\n"
        "Canción Dos,Artista Dos,,180\n".encode("utf-8")
    )
    rows = read_csv(csv_path)
    assert len(rows) == 2
    assert rows[0] == {
        "title": "Canción Uno",
        "artist": "Artista Uno",
        "album": "Álbum Uno",
        "duration": "3:45",
    }
    assert rows[1]["duration"] == "180"


def test_read_csv_missing():
    with pytest.raises(FileNotFoundError):
        read_csv("/no/existe.csv")


def test_parse_duration():
    assert _parse_duration("3:45") == 225
    assert _parse_duration("1:02:03") == 3723
    assert _parse_duration("180") == 180
    assert _parse_duration(None) is None
    assert _parse_duration("abc") is None


class FakeClient:
    """Cliente fake con búsquedas programadas."""

    def __init__(self, hits: dict[tuple[str, str], dict | None]):
        self.hits = hits

    async def search_song(self, title, artist):
        return self.hits.get((title, artist))


async def test_import_csv_matches(tmp_path: Path):
    csv_path = tmp_path / "c.csv"
    csv_path.write_text(
        "title,artist\n"
        "Never Gonna Give You Up,Rick Astley\n"
        "Canción Fantasma,Artista X\n",
        encoding="utf-8",
    )
    client = FakeClient(
        {
            ("Never Gonna Give You Up", "Rick Astley"): {
                "id": SONG_ID,
                "title": "Never Gonna Give You Up",
                "artist": "Rick Astley",
                "duration": 213,
                "album": "Whenever You Need Somebody",
            },
            ("Canción Fantasma", "Artista X"): None,
        }
    )
    result = await import_csv(csv_path, client=client)
    assert isinstance(result, ImportResult)
    assert result.total == 2
    assert result.matched == 1
    assert result.unmatched == 1
    assert result.errors == 0
    assert result.songs[0].matched is True
    assert result.songs[0].ytmusic_id == SONG_ID
    assert result.songs[1].matched is False


async def test_import_csv_no_match_mode(tmp_path: Path):
    """match=False solo lee el CSV sin buscar."""
    csv_path = tmp_path / "c.csv"
    csv_path.write_text("title,artist\nCanción Uno,Artista Uno\n", encoding="utf-8")

    class ExplodingClient:
        async def search_song(self, title, artist):
            raise AssertionError("no debe buscar con match=False")

    result = await import_csv(csv_path, client=ExplodingClient(), match=False)
    assert result.total == 1
    assert result.matched == 0
    assert result.songs[0].title == "Canción Uno"
    assert result.songs[0].matched is False


async def test_import_csv_missing_file():
    with pytest.raises(FileNotFoundError):
        await import_csv("/no/existe.csv")
