"""Tests de los proveedores de catálogo cloud (Apple/iTunes y Spotify)."""

import sqlite3
from pathlib import Path

import httpx
import pytest

from youber.music.audio_features.spotify import SpotifyClient
from youber.music.database import MusicDatabase
from youber.music.models import Track, TrackSource
from youber.music.providers import (
    CloudHit,
    cloud_path,
    import_cloud,
    search,
    search_itunes,
    search_spotify,
    to_track,
)
from youber.music.scanner import scan_library


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json


class FakeAsyncClient:
    """Cliente async fake que responde según la URL."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict]] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append(("GET", url, params or {}))
        return self.handler(url, params or {})

    async def post(self, url, headers=None, data=None):
        self.calls.append(("POST", url, {}))
        return self.handler(url, {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _itunes_handler(url, params):
    if not url.startswith("https://itunes.apple.com/search"):
        return FakeResponse(404)
    term = params.get("term", "")
    if term == "nada":
        return FakeResponse(200, {"results": []})
    return FakeResponse(
        200,
        {
            "results": [
                {
                    "trackId": 1001,
                    "trackName": "Canción Uno",
                    "artistName": "Artista A",
                    "collectionName": "Álbum Uno",
                    "trackTimeMillis": 200000,
                    "primaryGenreName": "pop",
                    "artworkUrl100": "https://img/1001.jpg",
                    "previewUrl": "https://preview/1001.m4a",
                },
                {
                    "trackId": 1002,
                    "trackName": "Canción Dos",
                    "artistName": "Artista B",
                    "trackTimeMillis": 180000,
                },
            ]
        },
    )


@pytest.mark.asyncio
async def test_search_itunes(monkeypatch):
    fake = FakeAsyncClient(_itunes_handler)
    monkeypatch.setattr(
        "youber.music.providers.httpx.AsyncClient", lambda **kw: fake
    )
    hits = await search_itunes("lofi")
    assert len(hits) == 2
    first = hits[0]
    assert first.source == TrackSource.APPLE
    assert first.external_id == "1001"
    assert first.title == "Canción Uno"
    assert first.artist == "Artista A"
    assert first.album == "Álbum Uno"
    assert first.duration_s == 200.0
    assert first.genre == "pop"
    assert first.artwork_url == "https://img/1001.jpg"
    assert first.preview_url == "https://preview/1001.m4a"


@pytest.mark.asyncio
async def test_search_itunes_empty(monkeypatch):
    fake = FakeAsyncClient(_itunes_handler)
    monkeypatch.setattr(
        "youber.music.providers.httpx.AsyncClient", lambda **kw: fake
    )
    assert await search_itunes("nada") == []


@pytest.mark.asyncio
async def test_search_spotify(monkeypatch):
    class FakeSpotifyClient:
        available = True

        async def search_tracks(self, query, limit=5):
            assert limit == 10
            return [
                {
                    "track_id": "sp1",
                    "title": "Canción Uno",
                    "artist": "Artista A",
                    "album": "Álbum Uno",
                    "duration_ms": 200000,
                }
            ]

    hits = await search_spotify("lofi", limit=10, client=FakeSpotifyClient())
    assert len(hits) == 1
    assert hits[0].source == TrackSource.SPOTIFY
    assert hits[0].external_id == "sp1"
    assert hits[0].duration_s == 200.0


@pytest.mark.asyncio
async def test_search_spotify_sin_credenciales():
    client = SpotifyClient(client_id=None, client_secret=None)
    with pytest.raises(RuntimeError, match="credenciales"):
        await search_spotify("lofi", client=client)


@pytest.mark.asyncio
async def test_search_dispatch(monkeypatch):
    fake = FakeAsyncClient(_itunes_handler)
    monkeypatch.setattr(
        "youber.music.providers.httpx.AsyncClient", lambda **kw: fake
    )
    hits = await search("apple", "lofi")
    assert hits[0].source == TrackSource.APPLE
    with pytest.raises(ValueError, match="Fuente no soportada"):
        await search("tidal", "lofi")


def test_cloud_path_and_to_track():
    hit = CloudHit(
        source=TrackSource.APPLE,
        external_id="1001",
        title="Canción Uno",
        artist="Artista A",
        album="Álbum Uno",
        duration_s=200.0,
        genre="pop",
        artwork_url="https://img/1001.jpg",
        preview_url="https://preview/1001.m4a",
    )
    assert str(cloud_path(TrackSource.APPLE, "1001")) == "cloud:apple:1001"
    track = to_track(hit)
    assert track.source == TrackSource.APPLE
    assert track.external_id == "1001"
    assert track.album == "Álbum Uno"
    assert track.file_hash == "cloud:apple:1001"
    assert not Path(track.file_path).exists()  # ruta sintética, no un fichero


def test_set_genre_y_best_genre(tmp_path: Path):
    from youber.music.providers import _best_genre

    db = MusicDatabase(tmp_path / "c.db")
    db.add_track(
        Track(
            id="t1",
            file_path=Path("/tmp/x.mp3"),
            title="Canción Uno",
            artist="Artista A",
            duration=200.0,
            file_hash="h",
        )
    )
    assert db.set_genre("t1", "pop") is True
    assert db.get_track("t1").genre == "pop"
    assert db.set_genre("no-existe", "pop") is False

    hit = CloudHit(
        source=TrackSource.APPLE,
        external_id="1",
        title="Canción Uno",
        artist="Artista A",
        genre="rock",
    )
    track = to_track(hit)
    track.id = "t2"
    assert _best_genre(track, [hit]) == "rock"


@pytest.mark.asyncio
async def test_enrich_genres_actualiza(monkeypatch, tmp_path: Path):
    """enrich_genres asigna género automático desde iTunes (fakes)."""
    from youber.music.providers import enrich_genres

    db = MusicDatabase(tmp_path / "c.db")
    db.add_track(
        Track(
            id="t1",
            file_path=Path("/tmp/a.mp3"),
            title="Canción Uno",
            artist="Artista A",
            duration=200.0,
            file_hash="h",
        )
    )
    db.add_track(
        Track(
            id="t2",
            file_path=Path("/tmp/b.mp3"),
            title="Ya Con Género",
            artist="Artista B",
            duration=180.0,
            file_hash="h2",
            genre="pop",
        )
    )

    async def fake_search_itunes(query, limit=10):
        return [
            CloudHit(
                source=TrackSource.APPLE,
                external_id="1",
                title="Canción Uno",
                artist="Artista A",
                genre="rock",
            )
        ]

    monkeypatch.setattr("youber.music.providers.search_itunes", fake_search_itunes)
    summary = await enrich_genres(db)
    assert summary["total"] == 1  # solo la pendiente (t2 ya tiene género)
    assert summary["updated"] == 1
    assert db.get_track("t1").genre == "rock"


# ---------------------------------------------------------------------------
# Importación (idempotente)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_cloud_añade_y_no_duplica(monkeypatch, tmp_path: Path):
    fake = FakeAsyncClient(_itunes_handler)
    monkeypatch.setattr(
        "youber.music.providers.httpx.AsyncClient", lambda **kw: fake
    )
    db = MusicDatabase(tmp_path / "catalogo.db")

    first = await import_cloud("lofi", "apple", limit=10, db=db)
    assert first["added"] == 2
    assert first["skipped"] == 0
    assert db.count() == 2

    second = await import_cloud("lofi", "apple", limit=10, db=db)
    assert second["added"] == 0
    assert second["skipped"] == 2
    assert db.count() == 2

    track = db.get_by_external_id(TrackSource.APPLE, "1001")
    assert track is not None
    assert track.title == "Canción Uno"


@pytest.mark.asyncio
async def test_import_cloud_db_propia_en_memoria(monkeypatch):
    fake = FakeAsyncClient(_itunes_handler)
    monkeypatch.setattr(
        "youber.music.providers.httpx.AsyncClient", lambda **kw: fake
    )
    summary = await import_cloud("lofi", "apple", limit=10)
    assert summary["added"] == 2


# ---------------------------------------------------------------------------
# Integración: migración, scanner y editor
# ---------------------------------------------------------------------------


def test_db_migracion_esquema_viejo(tmp_path: Path):
    """Una DB creada con el esquema viejo gana las columnas nuevas."""
    db_file = tmp_path / "viejo.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE tracks (
            id TEXT PRIMARY KEY,
            file_path TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            artist TEXT,
            duration REAL NOT NULL,
            genre TEXT,
            moods TEXT NOT NULL DEFAULT '[]',
            bpm INTEGER,
            key TEXT,
            favorite INTEGER NOT NULL DEFAULT 0,
            usage_count INTEGER NOT NULL DEFAULT 0,
            last_used TEXT,
            added_at TEXT NOT NULL,
            file_hash TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    db = MusicDatabase(db_file)
    db.add_track(
        Track(
            id="t1",
            file_path=Path("/tmp/x.mp3"),
            title="X",
            duration=10.0,
            file_hash="h",
            source=TrackSource.APPLE,
            external_id="abc",
        )
    )
    track = db.get_track("t1")
    assert track is not None
    assert track.source == TrackSource.APPLE
    assert track.external_id == "abc"


@pytest.mark.asyncio
async def test_scan_no_borra_pistas_cloud(tmp_path: Path):
    db = MusicDatabase(tmp_path / "c.db")
    db.add_track(
        Track(
            id="cloud1",
            file_path=Path("cloud:apple:1001"),
            title="Cloud",
            duration=100.0,
            file_hash="cloud:apple:1001",
            source=TrackSource.APPLE,
            external_id="1001",
        )
    )
    # Directorio vacío (debe existir): el scan no debe eliminar pistas cloud.
    empty_dir = tmp_path / "vacio"
    empty_dir.mkdir()
    summary = await scan_library(empty_dir, db)
    assert db.count() == 1
    assert summary["removed"] == 0


def test_editor_rechaza_pista_cloud(tmp_path: Path):
    from youber.music.library import MusicLibrary
    from youber.video.editor import VideoEditor
    from youber.video.models import Project

    library = MusicLibrary(tmp_path, db_path=tmp_path / "c.db")
    library.db.add_track(
        Track(
            id="cloud1",
            file_path=Path("cloud:spotify:sp1"),
            title="Cloud",
            duration=100.0,
            file_hash="cloud:spotify:sp1",
            source=TrackSource.SPOTIFY,
            external_id="sp1",
        )
    )
    editor = VideoEditor(library=library)
    project = Project(title="p", output_path=str(tmp_path / "p.mp4"))
    editor.set_music(project, track_id="cloud1")
    with pytest.raises(ValueError, match="sin fichero local"):
        editor._resolve_music(project)
    library.close()
