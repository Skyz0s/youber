"""Tests del conector de clips de stock (youber.video.stock)."""

from __future__ import annotations

from pathlib import Path

import pytest

from youber.video.stock import (
    available,
    download_clip,
    fetch_clips_for_scenes,
    search_pexels,
    search_pixabay,
)


def test_available_sin_keys(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setattr("youber.video.stock.PEXELS_KEY_FILE", tmp_path / "pexels.txt")
    monkeypatch.setattr("youber.video.stock.PIXABAY_KEY_FILE", tmp_path / "pixabay.txt")
    assert available() == {"pexels": False, "pixabay": False}


def test_available_con_keys(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PEXELS_API_KEY", "abc")
    monkeypatch.setenv("PIXABAY_API_KEY", "xyz")
    monkeypatch.setattr("youber.video.stock.PEXELS_KEY_FILE", tmp_path / "pexels.txt")
    monkeypatch.setattr("youber.video.stock.PIXABAY_KEY_FILE", tmp_path / "pixabay.txt")
    assert available() == {"pexels": True, "pixabay": True}


def test_available_desde_fichero(monkeypatch, tmp_path: Path):
    """La key también se lee de ~/.youber/pexels_key.txt (sin env)."""
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    key_file = tmp_path / "pexels.txt"
    key_file.write_text("clave-secreta\n", encoding="utf-8")
    monkeypatch.setattr("youber.video.stock.PEXELS_KEY_FILE", key_file)
    monkeypatch.setattr("youber.video.stock.PIXABAY_KEY_FILE", tmp_path / "pixabay.txt")
    assert available() == {"pexels": True, "pixabay": False}


def test_save_pexels_key(monkeypatch, tmp_path: Path):
    key_file = tmp_path / "pexels.txt"
    monkeypatch.setattr("youber.video.stock.PEXELS_KEY_FILE", key_file)
    from youber.video.stock import save_pexels_key

    path = save_pexels_key("nueva-key")
    assert path == key_file
    assert key_file.read_text(encoding="utf-8").strip() == "nueva-key"


def test_search_pexels_sin_key(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.setattr("youber.video.stock.PEXELS_KEY_FILE", tmp_path / "no.txt")
    with pytest.raises(ValueError):
        # no puede ejecutarse sin key (es async)
        import asyncio

        asyncio.run(search_pexels("test"))


def test_search_pixabay_sin_key(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setattr("youber.video.stock.PIXABAY_KEY_FILE", tmp_path / "no.txt")
    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(search_pixabay("test"))


def test_search_pexels_con_mock(monkeypatch):
    """Con key y httpx mockeado, devuelve los mejores vídeos HD."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            self._params = params
            return _FakeResponse()

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "videos": [
                    {
                        "id": 1,
                        "duration": 12,
                        "video_files": [
                            {"width": 640, "link": "https://low.mp4"},
                            {"width": 1920, "link": "https://hd.mp4"},
                        ],
                    },
                    {
                        "id": 2,
                        "duration": 8,
                        "video_files": [
                            {"width": 1280, "link": "https://ok.mp4"},
                        ],
                    },
                ]
            }

    monkeypatch.setenv("PEXELS_API_KEY", "abc")
    monkeypatch.setattr("youber.video.stock.httpx.AsyncClient", _FakeClient)

    import asyncio

    results = asyncio.run(search_pexels("noche oscura", min_width=1280))
    assert len(results) == 2
    assert results[0]["url"] == "https://hd.mp4"  # el de mayor resolución primero
    assert results[0]["source"] == "pexels"
    assert results[1]["url"] == "https://ok.mp4"


def test_download_clip(tmp_path: Path, monkeypatch):
    """Descarga el clip y lo guarda (idempotente)."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            return _FakeResp()

    class _FakeResp:
        def raise_for_status(self):
            pass

        @property
        def content(self):
            return b"fake-video-bytes" * 100

    monkeypatch.setattr("youber.video.stock.httpx.AsyncClient", _FakeClient)
    item = {"id": 99, "url": "https://x/clip.mp4", "source": "pexels"}

    import asyncio

    path = asyncio.run(download_clip(item, tmp_path, "hook"))
    assert path is not None
    assert path.exists()
    assert path.name == "hook-pexels-99.mp4"
    # segunda llamada → no re-descarga (idempotente)
    path2 = asyncio.run(download_clip(item, tmp_path, "hook"))
    assert path2 == path


def test_fetch_clips_for_scenes_sin_key(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setattr("youber.video.stock.PEXELS_KEY_FILE", tmp_path / "pexels.txt")
    monkeypatch.setattr("youber.video.stock.PIXABAY_KEY_FILE", tmp_path / "pixabay.txt")
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(
            fetch_clips_for_scenes(
                [{"title": "Hook", "text": "noche oscura"}], Path("/tmp/x")
            )
        )
