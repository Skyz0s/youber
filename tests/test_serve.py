"""Tests del servidor web del dashboard (serve.py)."""

import json
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest

from youber.dashboard.models import WidgetData, WidgetType
from youber.dashboard.serve import (
    DEFAULT_REFRESH,
    DEFAULT_WIDGETS,
    DashboardApp,
    load_config,
    make_handler,
    save_config,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_load_config_defaults(tmp_path: Path):
    config = load_config(tmp_path / "no.json")
    assert config["widgets"] == DEFAULT_WIDGETS
    assert config["refresh_seconds"] == DEFAULT_REFRESH
    assert config["port"] == 8787


def test_save_and_load_config(tmp_path: Path):
    file = tmp_path / "dashboard.json"
    save_config({"widgets": ["music-usage"], "refresh_seconds": 30, "port": 9000}, file)
    config = load_config(file)
    assert config["widgets"] == ["music-usage"]
    assert config["refresh_seconds"] == 30
    assert config["port"] == 9000


def test_load_config_merges_partial(tmp_path: Path):
    file = tmp_path / "dashboard.json"
    file.write_text(json.dumps({"widgets": ["top-videos"]}), encoding="utf-8")
    config = load_config(file)
    assert config["widgets"] == ["top-videos"]
    assert config["refresh_seconds"] == DEFAULT_REFRESH  # resto por defecto


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def test_dashboard_app_collect(tmp_path: Path, monkeypatch):
    class FakeManager:
        def collect_types(self, widget_types):
            return [
                WidgetData(
                    widget_id=f"w{i}",
                    type=WidgetType(value),
                    title=value,
                    data={"total": i},
                    position=i,
                )
                for i, value in enumerate(widget_types)
            ]

    monkeypatch.setattr("youber.dashboard.serve.WidgetManager", FakeManager)
    app = DashboardApp(
        config_path=tmp_path / "dash.json",
        widgets=["catalog-stats", "scheduled-tasks", "upload-status"],
    )
    data = app.collect()
    assert len(data) == 3
    assert [item.position for item in data] == [0, 1, 2]


def test_dashboard_app_render_page(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    html = app.render_page()
    assert "<!DOCTYPE html>" in html
    assert "catalog-stats" in html
    assert "scheduled-tasks" in html
    assert "upload-status" in html
    assert "REFRESH_MS" in html
    assert "/api/config" in html


def test_dashboard_app_data_payload(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    payload = app.data_payload()
    assert "updated_at" in payload
    assert payload["refresh_seconds"] == DEFAULT_REFRESH
    assert len(payload["widgets"]) == 3


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class _FakeCollectManager:
    """Manager fake: devuelve widgets sin tocar fuentes reales."""

    def collect_types(self, widget_types):
        return [
            WidgetData(
                widget_id=f"w{i}",
                type=WidgetType(value),
                title=value.replace("-", " ").title(),
                data={"total": i},
                position=i,
            )
            for i, value in enumerate(widget_types)
        ]


def _start_server(app: DashboardApp):
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_http_get_page(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        with urlopen(f"{base}/", timeout=5) as response:
            assert response.status == 200
            html = response.read().decode("utf-8")
            assert "Dashboard — Youber" in html
            assert "catalog-stats" in html
    finally:
        server.shutdown()
        server.server_close()


def test_http_get_api_data(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        with urlopen(f"{base}/api/data", timeout=5) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert len(payload["widgets"]) == 3
    finally:
        server.shutdown()
        server.server_close()


def test_http_import_apple_library(tmp_path: Path, monkeypatch):
    """POST /api/import-apple-library importa el XML al catálogo."""
    import plistlib

    xml_file = tmp_path / "Music Library.xml"
    with xml_file.open("wb") as handle:
        plistlib.dump(
            {
                "Tracks": {
                    "1": {
                        "Track ID": 1,
                        "Name": "Canción Uno",
                        "Artist": "Artista A",
                        "Album": "Álbum Uno",
                        "Total Time": 200000,
                        "Persistent ID": "AAA111",
                    }
                }
            },
            handle,
        )
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(
        config_path=tmp_path / "dash.json",
        widgets=DEFAULT_WIDGETS,
        library_dir=tmp_path / "music",
    )
    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = json.dumps({"path": str(xml_file)}).encode("utf-8")
        request = Request(
            f"{base}/api/import-apple-library",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            result = json.loads(response.read().decode("utf-8"))
            assert result["ok"] is True
            assert result["added"] == 1

        from youber.music.library import MusicLibrary

        library = MusicLibrary(tmp_path / "music")
        tracks = library.all()
        assert len(tracks) == 1
        assert tracks[0].external_id == "AAA111"
        library.close()
    finally:
        server.shutdown()
        server.server_close()


def test_http_import_apple_library_no_encontrado(tmp_path: Path, monkeypatch):
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(
        config_path=tmp_path / "dash.json",
        widgets=DEFAULT_WIDGETS,
        library_dir=tmp_path / "music",
    )
    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = json.dumps({"path": str(tmp_path / "no.xml")}).encode("utf-8")
        request = Request(
            f"{base}/api/import-apple-library",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=5)
        assert exc_info.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_http_import_apple_library_requiere_path(tmp_path: Path, monkeypatch):
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = json.dumps({"path": ""}).encode("utf-8")
        request = Request(
            f"{base}/api/import-apple-library",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=5)
        assert exc_info.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    config_file = tmp_path / "dash.json"
    app = DashboardApp(config_path=config_file, widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = json.dumps({"widgets": ["music-usage"]}).encode("utf-8")
        request = Request(
            f"{base}/api/config",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            result = json.loads(response.read().decode("utf-8"))
            assert result["ok"] is True
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["widgets"] == ["music-usage"]
    finally:
        server.shutdown()
        server.server_close()


def test_http_search_cloud(tmp_path: Path, monkeypatch):
    """GET /api/search-cloud devuelve resultados sin importar nada."""

    async def fake_search(source, query, limit, spotify_client=None):
        from youber.music.models import TrackSource
        from youber.music.providers import CloudHit

        assert query == "lofi"
        return [
            CloudHit(
                source=TrackSource.APPLE,
                external_id="1001",
                title="Canción Uno",
                artist="Artista A",
                album="Álbum Uno",
                duration_s=200.0,
            )
        ]

    monkeypatch.setattr("youber.music.providers.search", fake_search)
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        with urlopen(f"{base}/api/search-cloud?q=lofi&source=apple&limit=10", timeout=5) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["source"] == "apple"
            assert len(payload["hits"]) == 1
            assert payload["hits"][0]["external_id"] == "1001"
    finally:
        server.shutdown()
        server.server_close()


def test_http_search_cloud_requiere_query(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        from urllib.error import HTTPError

        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{base}/api/search-cloud", timeout=5)
        assert exc_info.value.code == 400
        payload = json.loads(exc_info.value.read().decode("utf-8"))
        assert "error" in payload
    finally:
        server.shutdown()
        server.server_close()


def test_http_import_cloud(tmp_path: Path, monkeypatch):
    """POST /api/import-cloud importa al catálogo del dashboard."""

    async def fake_search(source, query, limit, spotify_client=None):
        from youber.music.models import TrackSource
        from youber.music.providers import CloudHit

        return [
            CloudHit(
                source=TrackSource.APPLE,
                external_id="1001",
                title="Canción Uno",
                artist="Artista A",
                duration_s=200.0,
            )
        ]

    monkeypatch.setattr("youber.music.providers.search", fake_search)
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(
        config_path=tmp_path / "dash.json",
        widgets=DEFAULT_WIDGETS,
        library_dir=tmp_path / "music",
    )
    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = json.dumps({"q": "lofi", "source": "apple", "limit": 10}).encode("utf-8")
        request = Request(
            f"{base}/api/import-cloud",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            result = json.loads(response.read().decode("utf-8"))
            assert result["ok"] is True
            assert result["added"] == 1

        # El catálogo del dashboard tiene la pista importada.
        from youber.music.library import MusicLibrary

        library = MusicLibrary(tmp_path / "music")
        tracks = library.all()
        assert len(tracks) == 1
        assert tracks[0].external_id == "1001"
        assert tracks[0].source.value == "apple"
        library.close()
    finally:
        server.shutdown()
        server.server_close()


def test_http_import_cloud_solo_seleccionadas(tmp_path: Path, monkeypatch):
    """POST con external_ids importa solo las pistas marcadas."""

    async def fake_search(source, query, limit, spotify_client=None):
        from youber.music.models import TrackSource
        from youber.music.providers import CloudHit

        return [
            CloudHit(
                source=TrackSource.APPLE,
                external_id="1001",
                title="Canción Uno",
                artist="A",
            ),
            CloudHit(
                source=TrackSource.APPLE,
                external_id="1002",
                title="Canción Dos",
                artist="B",
            ),
        ]

    monkeypatch.setattr("youber.music.providers.search", fake_search)
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(
        config_path=tmp_path / "dash.json",
        widgets=DEFAULT_WIDGETS,
        library_dir=tmp_path / "music",
    )
    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = json.dumps(
            {"q": "lofi", "source": "apple", "limit": 10, "external_ids": ["1002"]}
        ).encode("utf-8")
        request = Request(
            f"{base}/api/import-cloud",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            result = json.loads(response.read().decode("utf-8"))
            assert result["added"] == 1

        from youber.music.library import MusicLibrary

        library = MusicLibrary(tmp_path / "music")
        assert library.count() == 1
        assert library.all()[0].external_id == "1002"
        library.close()
    finally:
        server.shutdown()
        server.server_close()
