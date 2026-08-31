"""Tests del módulo de subida a YouTube (auth, metadata, youtube, cli).

Se usa un cliente HTTP fake (``FakeAsyncClient``) para no tocar red ni
necesitar credenciales reales de Google.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from youber.upload.auth import YouTubeAuth
from youber.upload.cli import _privacy, _publish_at, build_parser
from youber.upload.metadata import PrivacyStatus, VideoMetadata
from youber.upload.youtube import YouTubeUploader

VIDEO_ID = "abc123XYZ"


# ---------------------------------------------------------------------------
# HTTP fake
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=self
            )

    def json(self):
        return self._json


class FakeAsyncClient:
    """Cliente async fake que registra llamadas y devuelve respuestas programadas."""

    def __init__(self, responses):
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _record(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses[method](method, url, kwargs)

    async def post(self, url, **kwargs):
        return await self._record("post", url, kwargs)

    async def put(self, url, **kwargs):
        return await self._record("put", url, kwargs)

    async def get(self, url, **kwargs):
        return await self._record("get", url, kwargs)


def make_fake_client(monkeypatch, responses):
    client = FakeAsyncClient(responses)

    def factory(**kwargs):
        return client

    monkeypatch.setattr("youber.upload.youtube.httpx.AsyncClient", factory)
    monkeypatch.setattr("youber.upload.auth.httpx.AsyncClient", factory)
    return client


def auth_with_token(monkeypatch, tmp_path: Path, token: str = "tok123") -> YouTubeAuth:
    auth = YouTubeAuth(
        client_id="id", client_secret="secret", credentials_dir=tmp_path
    )
    auth.token_file.write_text(
        f'{{"access_token": "{token}", "refresh_token": "ref", "expires_at": 9999999999}}',
        encoding="utf-8",
    )
    return auth


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata_defaults():
    meta = VideoMetadata(title="Mi video")
    assert meta.description == ""
    assert meta.tags == []
    assert meta.category_id == "22"
    assert meta.privacy_status == PrivacyStatus.PRIVATE
    assert meta.publish_at is None


def test_metadata_tags_parsing():
    meta = VideoMetadata(title="T", tags="python, tutorial,  bar")
    assert meta.tags == ["python", "tutorial", "bar"]
    meta2 = VideoMetadata(title="T", tags=["a", "b"])
    assert meta2.tags == ["a", "b"]


def test_metadata_validation():
    with pytest.raises(ValidationError):
        VideoMetadata(title="")
    with pytest.raises(ValidationError):
        VideoMetadata(title="T", category_id="abc")


def test_metadata_to_snippet_and_status():
    meta = VideoMetadata(
        title="T",
        description="D",
        tags=["a"],
        privacy_status=PrivacyStatus.PUBLIC,
    )
    assert meta.to_snippet() == {"title": "T", "description": "D", "tags": ["a"], "categoryId": "22"}
    assert meta.to_status() == {"privacyStatus": "public"}


def test_metadata_publish_at_forces_private():
    meta = VideoMetadata(
        title="T",
        privacy_status=PrivacyStatus.PUBLIC,
        publish_at=datetime(2026, 9, 15, 10, 0, 0),
    )
    status = meta.to_status()
    assert status["privacyStatus"] == "private"
    assert "publishAt" in status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_auth_requires_client():
    auth = YouTubeAuth(client_id="", client_secret="")
    with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
        auth.get_authorization_url()


def test_auth_authorization_url():
    auth = YouTubeAuth(client_id="cid", client_secret="csecret")
    url = auth.get_authorization_url(state="s1")
    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=cid" in url
    assert "scope=" in url
    assert "access_type=offline" in url
    assert "state=s1" in url


def test_auth_no_token():
    auth = YouTubeAuth(client_id="id", client_secret="sec", credentials_dir=Path("/no/existe"))
    assert auth.has_token() is False
    with pytest.raises(ValueError, match="youber-upload auth"):
        asyncio.run(auth.get_access_token())


def test_auth_exchange_code(monkeypatch, tmp_path: Path):
    def handler(method, url, kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        assert kwargs["data"]["grant_type"] == "authorization_code"
        assert kwargs["data"]["code"] == "code123"
        return FakeResponse(json_data={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})

    client = make_fake_client(monkeypatch, {"post": handler})
    auth = YouTubeAuth(client_id="id", client_secret="sec", credentials_dir=tmp_path)

    tokens = asyncio.run(auth.exchange_code("code123"))
    assert tokens["access_token"] == "at"
    assert tokens["refresh_token"] == "rt"
    assert auth.has_token() is True
    assert client.calls[0][0] == "post"


def test_auth_refresh_token(monkeypatch, tmp_path: Path):
    def handler(method, url, kwargs):
        assert kwargs["data"]["grant_type"] == "refresh_token"
        return FakeResponse(json_data={"access_token": "new", "expires_in": 3600})

    make_fake_client(monkeypatch, {"post": handler})
    auth = auth_with_token(monkeypatch, tmp_path)
    # expires_at en el pasado → fuerza refresh
    auth.token_file.write_text(
        '{"access_token": "old", "refresh_token": "ref", "expires_at": 1}',
        encoding="utf-8",
    )
    token = asyncio.run(auth.get_access_token())
    assert token == "new"


# ---------------------------------------------------------------------------
# YouTubeUploader
# ---------------------------------------------------------------------------


def test_upload_video_resumable(monkeypatch, tmp_path: Path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake-video-bytes")

    def handler(method, url, kwargs):
        if method == "post":
            assert kwargs["params"]["uploadType"] == "resumable"
            assert kwargs["params"]["part"] == "snippet,status"
            assert kwargs["json"]["snippet"]["title"] == "Mi video"
            return FakeResponse(
                status_code=200,
                headers={"Location": "https://upload.example/session"},
            )
        if method == "put":
            assert url == "https://upload.example/session"
            assert kwargs["content"] == b"fake-video-bytes"
            return FakeResponse(json_data={"id": VIDEO_ID, "status": {"uploadStatus": "uploaded"}})
        raise AssertionError(f"método inesperado: {method}")

    make_fake_client(monkeypatch, {"post": handler, "put": handler})
    auth = auth_with_token(monkeypatch, tmp_path)
    uploader = YouTubeUploader(auth)

    resource = asyncio.run(
        uploader.upload_video(str(video), VideoMetadata(title="Mi video"))
    )
    assert resource["id"] == VIDEO_ID


def test_upload_video_missing_file(monkeypatch, tmp_path: Path):
    make_fake_client(monkeypatch, {"post": lambda *a: None})
    auth = auth_with_token(monkeypatch, tmp_path)
    uploader = YouTubeUploader(auth)
    with pytest.raises(FileNotFoundError):
        asyncio.run(uploader.upload_video(str(tmp_path / "no.mp4"), VideoMetadata(title="T")))


def test_check_status(monkeypatch, tmp_path: Path):
    def handler(method, url, kwargs):
        assert method == "get"
        assert kwargs["params"]["id"] == VIDEO_ID
        return FakeResponse(
            json_data={
                "items": [
                    {"id": VIDEO_ID, "status": {"uploadStatus": "processed", "privacyStatus": "private"}}
                ]
            }
        )

    make_fake_client(monkeypatch, {"get": handler})
    auth = auth_with_token(monkeypatch, tmp_path)
    item = asyncio.run(YouTubeUploader(auth).check_status(VIDEO_ID))
    assert item["status"]["uploadStatus"] == "processed"


def test_check_status_not_found(monkeypatch, tmp_path: Path):
    make_fake_client(monkeypatch, {"get": lambda *a: FakeResponse(json_data={"items": []})})
    auth = auth_with_token(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="no encontrado"):
        asyncio.run(YouTubeUploader(auth).check_status(VIDEO_ID))


def test_get_video_url():
    assert YouTubeUploader.get_video_url(VIDEO_ID) == f"https://www.youtube.com/watch?v={VIDEO_ID}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_privacy():
    import argparse

    assert _privacy("public") == PrivacyStatus.PUBLIC
    assert _privacy("UNLISTED") == PrivacyStatus.UNLISTED
    with pytest.raises(argparse.ArgumentTypeError):
        _privacy("secreto")


def test_cli_publish_at():
    import argparse

    parsed = _publish_at("2026-09-15 10:00:00")
    assert parsed.year == 2026
    assert parsed.month == 9
    assert parsed.day == 15
    with pytest.raises(argparse.ArgumentTypeError):
        _publish_at("no-es-fecha")


def test_cli_parser_commands():
    parser = build_parser()
    assert parser.parse_args(["auth"]).command == "auth"
    args = parser.parse_args(
        ["upload", "v.mp4", "--title", "T", "--tags", "a,b", "--privacy", "public"]
    )
    assert args.command == "upload"
    assert args.tags == "a,b"
    assert args.privacy == PrivacyStatus.PUBLIC
    args = parser.parse_args(
        ["schedule", "v.mp4", "--title", "T", "--publish-at", "2026-09-15 10:00:00"]
    )
    assert args.command == "schedule"
    assert args.publish_at is not None
