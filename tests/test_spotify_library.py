"""Tests del conector OAuth de Spotify (biblioteca personal, dormante)."""

import json
from pathlib import Path

import httpx
import pytest

from youber.music.spotify_library import (
    SpotifyLibraryClient,
    import_spotify_library,
    track_from_api,
)


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


def _token_handler(url, params):
    if url.endswith("/api/token"):
        return FakeResponse(
            200,
            {
                "access_token": "tok",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "ref",
                "scope": "user-library-read",
            },
        )
    return FakeResponse(404)


def _make_client(tmp_path: Path, token: dict | None = None) -> SpotifyLibraryClient:
    token_file = tmp_path / "spotify_token.json"
    if token is not None:
        token_file.write_text(json.dumps(token), encoding="utf-8")
    return SpotifyLibraryClient(
        client_id="id",
        client_secret="secret",
        token_file=token_file,
    )


def test_authorization_url():
    client = _make_client(Path("."), token=None)
    url = client.authorization_url(state="abc")
    assert url.startswith("https://accounts.spotify.com/authorize?")
    assert "client_id=id" in url
    assert "redirect_uri=" in url
    assert "user-library-read" in url
    assert "state=abc" in url


def test_authorization_url_sin_credenciales(tmp_path: Path):
    client = SpotifyLibraryClient(
        client_id=None,
        client_secret=None,
        token_file=tmp_path / "t.json",
    )
    with pytest.raises(RuntimeError, match="credenciales"):
        client.authorization_url()


@pytest.mark.asyncio
async def test_exchange_code(monkeypatch, tmp_path: Path):
    fake = FakeAsyncClient(_token_handler)
    monkeypatch.setattr(
        "youber.music.spotify_library.httpx.AsyncClient", lambda **kw: fake
    )
    client = _make_client(tmp_path)
    data = await client.exchange_code("code123")
    assert data["access_token"] == "tok"
    assert client.connected is True
    # El token queda persistido.
    saved = json.loads((tmp_path / "spotify_token.json").read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "ref"


@pytest.mark.asyncio
async def test_import_sin_sesion(tmp_path: Path):
    client = _make_client(tmp_path, token=None)
    with pytest.raises(RuntimeError, match="conecta primero"):
        await import_spotify_library(client=client)


def test_track_from_api():
    track = track_from_api(
        {
            "id": "sp1",
            "name": "Canción",
            "artists": [{"name": "Artista"}],
            "album": {"name": "Álbum"},
            "duration_ms": 200000,
        }
    )
    assert track.external_id == "sp1"
    assert track.duration == 200.0
    assert track.artist == "Artista"
    assert track.album == "Álbum"
    assert track.file_hash == "cloud:spotify:sp1"
