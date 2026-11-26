"""Tests del módulo de TikTok (Content Posting API).

Todo con clientes HTTP fake: no se toca la red ni hacen falta credenciales.
"""

import asyncio
import json
import time
from pathlib import Path

import pytest

from youber.upload.tiktok import (
    MIN_CHUNK_SIZE,
    PrivacyLevel,
    TikTokAPIError,
    TikTokAuth,
    TikTokError,
    TikTokPostInfo,
    TikTokUploader,
    _data_or_error,
    detect_mime,
    plan_chunks,
)
from youber.upload.tiktok_cli import _privacy, build_parser, extract_code

# ---------------------------------------------------------------------------
# HTTP fake
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text or json.dumps(self._json)
        self.content = self.text.encode()

    @property
    def is_error(self):
        return self.status_code >= 400

    def json(self):
        return self._json


class FakeAsyncClient:
    """Cliente async fake: responde por método con una función o cola."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _record(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)

    async def post(self, url, **kwargs):
        return await self._record("post", url, kwargs)

    async def put(self, url, **kwargs):
        return await self._record("put", url, kwargs)

    async def get(self, url, **kwargs):
        return await self._record("get", url, kwargs)


def make_client(monkeypatch, handler):
    client = FakeAsyncClient(handler)

    def factory(**kwargs):
        return client

    monkeypatch.setattr("youber.upload.tiktok.httpx.AsyncClient", factory)
    return client


def ok(data):
    return FakeResponse(200, {"data": data, "error": {"code": "ok", "message": "", "log_id": ""}})


def auth_with_tokens(tmp_path: Path, **overrides) -> TikTokAuth:
    auth = TikTokAuth(client_key="key", client_secret="secret", credentials_dir=tmp_path)
    tokens = {
        "access_token": "act.token",
        "refresh_token": "rft.token",
        "open_id": "open-1",
        "scope": "video.upload",
        "expires_at": time.time() + 3600,
        "refresh_expires_at": time.time() + 86400,
    }
    tokens.update(overrides)
    (tmp_path / "tiktok_token.json").write_text(json.dumps(tokens), encoding="utf-8")
    return auth


# ---------------------------------------------------------------------------
# plan_chunks
# ---------------------------------------------------------------------------


def test_plan_chunks_small_file_single_chunk():
    size = 4 * 1024 * 1024
    chunk, total, ranges = plan_chunks(size)
    assert chunk == size
    assert total == 1
    assert ranges == [(0, size - 1)]


def test_plan_chunks_remainder_goes_to_last_chunk():
    size = 50_000_123
    chunk, total, ranges = plan_chunks(size, 10_000_000)
    assert chunk == 10_000_000
    assert total == 5
    assert len(ranges) == 5
    assert ranges[0] == (0, 9_999_999)
    assert ranges[-1] == (40_000_000, size - 1)
    assert ranges[-1][1] - ranges[-1][0] + 1 == 10_000_123


def test_plan_chunks_clamps_to_minimum():
    size = 20 * 1024 * 1024
    chunk, total, ranges = plan_chunks(size, 1024)
    assert chunk == MIN_CHUNK_SIZE
    assert total == 4  # 20 MB / 5 MB
    assert ranges[-1][1] == size - 1


def test_plan_chunks_ranges_are_contiguous_and_complete():
    size = 37 * 1024 * 1024 + 123
    _, total, ranges = plan_chunks(size, 5 * 1024 * 1024)
    assert total == len(ranges)
    assert ranges[0][0] == 0
    assert ranges[-1][1] == size - 1
    for (_, prev_last), (next_first, _) in zip(ranges, ranges[1:], strict=False):
        assert next_first == prev_last + 1


def test_plan_chunks_rejects_empty():
    with pytest.raises(ValueError):
        plan_chunks(0)


def test_detect_mime():
    assert detect_mime("a.MP4") == "video/mp4"
    assert detect_mime("a.mov") == "video/quicktime"
    assert detect_mime("a.unknown") == "video/mp4"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_authorization_url_contains_required_params(tmp_path):
    auth = TikTokAuth(client_key="ck", client_secret="cs", credentials_dir=tmp_path)
    url = auth.get_authorization_url("https://example.com/cb", state="xyz")
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/?")
    assert "client_key=ck" in url
    assert "response_type=code" in url
    assert "state=xyz" in url
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcb" in url
    assert "video.publish" in url


def test_authorization_url_requires_redirect(tmp_path):
    auth = TikTokAuth(client_key="ck", client_secret="cs", credentials_dir=tmp_path)
    with pytest.raises(TikTokError):
        auth.get_authorization_url()


def test_auth_without_credentials_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("TIKTOK_CLIENT_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_CLIENT_SECRET", raising=False)
    auth = TikTokAuth(credentials_dir=tmp_path)
    with pytest.raises(TikTokError):
        auth.get_authorization_url("https://example.com/cb")


def test_exchange_code_saves_tokens(tmp_path, monkeypatch):
    auth = TikTokAuth(client_key="ck", client_secret="cs", credentials_dir=tmp_path)

    def handler(method, url, kwargs):
        assert "oauth/token" in url
        assert kwargs["data"]["grant_type"] == "authorization_code"
        assert kwargs["data"]["code"] == "the-code"
        return FakeResponse(
            200,
            {
                "access_token": "act.new",
                "expires_in": 86400,
                "open_id": "open-9",
                "refresh_token": "rft.new",
                "refresh_expires_in": 31536000,
                "scope": "video.upload,video.publish",
                "token_type": "Bearer",
            },
        )

    make_client(monkeypatch, handler)
    tokens = asyncio.run(auth.exchange_code("the-code", "https://example.com/cb"))
    assert tokens["access_token"] == "act.new"
    saved = json.loads((tmp_path / "tiktok_token.json").read_text(encoding="utf-8"))
    assert saved["open_id"] == "open-9"
    assert saved["expires_at"] > time.time()


def test_exchange_code_error_payload(tmp_path, monkeypatch):
    auth = TikTokAuth(client_key="ck", client_secret="cs", credentials_dir=tmp_path)
    make_client(
        monkeypatch,
        lambda *a: FakeResponse(400, {"error": "invalid_grant", "error_description": "bad code"}),
    )
    with pytest.raises(TikTokAPIError) as err:
        asyncio.run(auth.exchange_code("nope", "https://example.com/cb"))
    assert err.value.code == "invalid_grant"


def test_get_access_token_returns_valid_token(tmp_path, monkeypatch):
    auth = auth_with_tokens(tmp_path)
    make_client(monkeypatch, lambda *a: pytest.fail("no debería llamar a la red"))
    assert asyncio.run(auth.get_access_token()) == "act.token"


def test_get_access_token_refreshes_when_expired(tmp_path, monkeypatch):
    auth = auth_with_tokens(tmp_path, access_token="old", expires_at=time.time() - 10)

    def handler(method, url, kwargs):
        assert kwargs["data"]["grant_type"] == "refresh_token"
        return FakeResponse(200, {"access_token": "fresh", "expires_in": 86400})

    make_client(monkeypatch, handler)
    assert asyncio.run(auth.get_access_token()) == "fresh"
    saved = json.loads((tmp_path / "tiktok_token.json").read_text(encoding="utf-8"))
    assert saved["access_token"] == "fresh"
    assert saved["refresh_token"] == "rft.token"  # se conserva el anterior


def test_get_access_token_expired_without_refresh(tmp_path):
    auth = auth_with_tokens(tmp_path, expires_at=time.time() - 10, refresh_token=None)
    with pytest.raises(ValueError, match="refresh_token"):
        asyncio.run(auth.get_access_token())


# ---------------------------------------------------------------------------
# Uploader
# ---------------------------------------------------------------------------


def test_query_creator_info(tmp_path, monkeypatch):
    auth = auth_with_tokens(tmp_path)
    payload = {"creator_username": "kp", "privacy_level_options": ["SELF_ONLY"]}
    client = make_client(monkeypatch, lambda *a: ok(payload))
    info = asyncio.run(TikTokUploader(auth).query_creator_info())
    assert info["creator_username"] == "kp"
    assert client.calls[0][0] == "post"
    assert client.calls[0][2]["headers"]["Authorization"] == "Bearer act.token"


def test_init_inbox_upload_body(tmp_path, monkeypatch, tmp_path_factory):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\0" * (6 * 1024 * 1024))
    auth = auth_with_tokens(tmp_path)
    client = make_client(
        monkeypatch,
        lambda *a: ok({"publish_id": "p1", "upload_url": "https://upload/p1"}),
    )
    result = asyncio.run(TikTokUploader(auth).init_inbox_upload(video, 5 * 1024 * 1024))
    assert result["publish_id"] == "p1"
    url = client.calls[0][1]
    body = client.calls[0][2]["json"]
    assert url.endswith("/post/publish/inbox/video/init/")
    assert body["source_info"]["source"] == "FILE_UPLOAD"
    assert body["source_info"]["video_size"] == video.stat().st_size
    assert "post_info" not in body


def test_init_direct_post_includes_post_info(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\0" * (6 * 1024 * 1024))
    auth = auth_with_tokens(tmp_path)
    client = make_client(
        monkeypatch,
        lambda *a: ok({"publish_id": "p2", "upload_url": "https://upload/p2"}),
    )
    post = TikTokPostInfo(title="hola", privacy_level=PrivacyLevel.PUBLIC, disable_comment=True)
    asyncio.run(TikTokUploader(auth).init_direct_post(video, post, 5 * 1024 * 1024))
    body = client.calls[0][2]["json"]
    assert client.calls[0][1].endswith("/post/publish/video/init/")
    assert body["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert body["post_info"]["disable_comment"] is True


def test_init_requires_existing_file(tmp_path, monkeypatch):
    auth = auth_with_tokens(tmp_path)
    make_client(monkeypatch, lambda *a: ok({}))
    with pytest.raises(FileNotFoundError):
        asyncio.run(TikTokUploader(auth).init_inbox_upload(tmp_path / "nope.mp4"))


def test_upload_file_sends_chunks_with_content_range(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 12)
    auth = auth_with_tokens(tmp_path)
    monkeypatch.setattr(
        "youber.upload.tiktok.plan_chunks",
        lambda size, chunk_size=None: (4, 3, [(0, 3), (4, 7), (8, 11)]),
    )
    statuses = iter([206, 206, 201])
    client = make_client(monkeypatch, lambda *a: FakeResponse(next(statuses)))

    sent = asyncio.run(TikTokUploader(auth).upload_file("https://upload/x", video))
    assert sent == 12
    assert len(client.calls) == 3
    ranges = [call[2]["headers"]["Content-Range"] for call in client.calls]
    assert ranges == ["bytes 0-3/12", "bytes 4-7/12", "bytes 8-11/12"]
    assert all(call[2]["headers"]["Content-Type"] == "video/mp4" for call in client.calls)


def test_upload_file_raises_on_rejected_chunk(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 12)
    auth = auth_with_tokens(tmp_path)
    monkeypatch.setattr(
        "youber.upload.tiktok.plan_chunks",
        lambda size, chunk_size=None: (4, 1, [(0, 11)]),
    )
    make_client(monkeypatch, lambda *a: FakeResponse(403, {}, text="expired"))
    with pytest.raises(TikTokError, match="403"):
        asyncio.run(TikTokUploader(auth).upload_file("https://upload/x", video))


def test_wait_for_publish_returns_final_state(tmp_path, monkeypatch):
    auth = auth_with_tokens(tmp_path)
    states = iter([{"status": "PROCESSING_UPLOAD"}, {"status": "PUBLISH_COMPLETE"}])

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("youber.upload.tiktok._sleep", no_sleep)
    make_client(monkeypatch, lambda *a: ok(next(states)))
    result = asyncio.run(TikTokUploader(auth).wait_for_publish("p1"))
    assert result["status"] == "PUBLISH_COMPLETE"


def test_wait_for_publish_failed_state(tmp_path, monkeypatch):
    auth = auth_with_tokens(tmp_path)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("youber.upload.tiktok._sleep", no_sleep)
    make_client(monkeypatch, lambda *a: ok({"status": "FAILED", "fail_reason": "too_long"}))
    with pytest.raises(TikTokError, match="too_long"):
        asyncio.run(TikTokUploader(auth).wait_for_publish("p1"))


def test_publish_inbox_flow(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 12)
    auth = auth_with_tokens(tmp_path)
    monkeypatch.setattr(
        "youber.upload.tiktok.plan_chunks",
        lambda size, chunk_size=None: (4, 1, [(0, 11)]),
    )
    responses = iter(
        [
            ok({"publish_id": "p1", "upload_url": "https://upload/p1"}),
            FakeResponse(201),
        ]
    )
    make_client(monkeypatch, lambda *a: next(responses))
    result = asyncio.run(TikTokUploader(auth).publish(video, wait=False))
    assert result["publish_id"] == "p1"
    assert result["uploaded_bytes"] == 12
    assert result["status"] == "PROCESSING_UPLOAD"


def test_publish_direct_requires_post_info(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 12)
    auth = auth_with_tokens(tmp_path)
    make_client(monkeypatch, lambda *a: ok({}))
    with pytest.raises(TikTokError, match="post_info"):
        asyncio.run(TikTokUploader(auth).publish(video, None, direct=True))


def test_api_error_is_extracted():
    response = FakeResponse(
        200,
        {"data": {}, "error": {"code": "scope_not_authorized", "message": "nope", "log_id": "L1"}},
    )
    with pytest.raises(TikTokAPIError) as err:
        _data_or_error(response)
    assert err.value.code == "scope_not_authorized"
    assert "L1" in str(err.value)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_privacy_aliases():
    assert _privacy("public") is PrivacyLevel.PUBLIC
    assert _privacy("friends") is PrivacyLevel.FRIENDS
    assert _privacy("private") is PrivacyLevel.SELF_ONLY


def test_cli_parser_upload_defaults():
    parser = build_parser()
    args = parser.parse_args(["upload", "video.mp4"])
    assert args.mode == "inbox"
    assert args.privacy is PrivacyLevel.SELF_ONLY
    assert args.video == "video.mp4"


def test_cli_extract_code_from_url_and_raw():
    url = "https://example.com/cb?code=abc123&state=xyz"
    assert extract_code(url) == "abc123"
    assert extract_code("abc123") == "abc123"


def test_cli_extract_code_error_url():
    with pytest.raises(ValueError, match="error"):
        extract_code("https://example.com/cb?error=access_denied")
