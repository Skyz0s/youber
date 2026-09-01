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
    assert "cloud-form" in html
    assert "apple-library-form" in html
    assert "ytmusic-form" in html


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


def test_http_research_canal_ordenado_por_vistas(tmp_path: Path, monkeypatch):
    """GET /api/research devuelve el canal con vídeos ordenados por vistas desc."""
    from youber.research.data_models import ChannelData, VideoData

    videos = [
        VideoData(
            title=f"Vídeo {i}",
            url=f"https://www.youtube.com/watch?v=vid{i}",
            video_id=f"vid{i}",
            views=f"{i} M de visualizaciones",
            duration="10:00",
            publish_date=f"hace {i} días",
            channel_name="Canal Demo",
            channel_url="https://www.youtube.com/@canaldemo",
        )
        for i in range(1, 4)
    ]
    # El analizador devuelve los vídeos desordenados (2 M, 1 M, 3 M);
    # el endpoint debe ordenarlos por vistas desc (3 M, 2 M, 1 M).
    videos = [videos[1], videos[0], videos[2]]
    channel = ChannelData(
        name="Canal Demo",
        url="https://www.youtube.com/@canaldemo",
        handle="canaldemo",
        subscribers="12,3 K suscriptores",
        videos=videos,
    )

    async def fake_analyze(url, max_videos=10, mode="html"):
        assert mode == "html"
        return channel

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    monkeypatch.setattr(
        "youber.research.channel_analyzer.ChannelAnalyzer",
        lambda **kwargs: type(
            "Fake", (), {"analyze": staticmethod(fake_analyze)}
        )(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        with urlopen(f"{base}/api/research?url=@canaldemo&n=3", timeout=5) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["kind"] == "channel"
            assert payload["channel"]["name"] == "Canal Demo"
            titles = [v["title"] for v in payload["videos"]]
            assert titles == ["Vídeo 3", "Vídeo 2", "Vídeo 1"]
            assert payload["views_summary"]["max"] == 3_000_000
    finally:
        server.shutdown()
        server.server_close()


def test_http_research_video(tmp_path: Path, monkeypatch):
    """GET /api/research con URL de vídeo devuelve los datos del vídeo."""
    from youber.research.data_models import VideoData

    video = VideoData(
        title="Vídeo suelto",
        url="https://www.youtube.com/watch?v=abc123def45",
        video_id="abc123def45",
        views="1.234 visualizaciones",
        likes="98",
        comments="12",
        duration="12:34",
        publish_date="2026-08-15",
        channel_name="Canal Demo",
        channel_url="https://www.youtube.com/@canaldemo",
    )

    async def fake_analyze(url, mode="html"):
        assert mode == "html"
        return video

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    monkeypatch.setattr(
        "youber.research.video_analyzer.VideoAnalyzer",
        lambda **kwargs: type(
            "Fake", (), {"analyze": staticmethod(fake_analyze)}
        )(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        with urlopen(
            f"{base}/api/research?url=https://youtu.be/abc123def45", timeout=5
        ) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["kind"] == "video"
            assert payload["video"]["title"] == "Vídeo suelto"
            assert payload["video"]["video_id"] == "abc123def45"
    finally:
        server.shutdown()
        server.server_close()


def test_http_research_sin_url(tmp_path: Path, monkeypatch):
    """GET /api/research sin url devuelve 400."""
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{base}/api/research", timeout=5)
        assert exc_info.value.code == 400
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


def _fake_channel_analyzer(monkeypatch):
    """Mockea ChannelAnalyzer con un canal sintético de 2 vídeos."""
    from youber.research.data_models import ChannelData, VideoData

    videos = [
        VideoData(
            title=f"Vídeo {i}",
            url=f"https://www.youtube.com/watch?v=vid{i}",
            video_id=f"vid{i}",
            views="10 K de visualizaciones",
            duration="10:00",
            publish_date=f"hace {i} días",
            channel_name="Canal Demo",
            channel_url="https://www.youtube.com/@canaldemo",
        )
        for i in range(1, 3)
    ]
    channel = ChannelData(
        name="Canal Demo",
        url="https://www.youtube.com/@canaldemo",
        handle="canaldemo",
        subscribers="12,3 K suscriptores",
        videos=videos,
    )

    async def fake_analyze(url, max_videos=10, mode="html"):
        return channel

    monkeypatch.setattr(
        "youber.research.channel_analyzer.ChannelAnalyzer",
        lambda **kwargs: type("Fake", (), {"analyze": staticmethod(fake_analyze)})(),
    )
    return channel


def test_http_script_proposal(tmp_path: Path, monkeypatch):
    """GET /api/script-proposal devuelve guion + opciones de música local."""
    _fake_channel_analyzer(monkeypatch)
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(
        config_path=tmp_path / "dash.json",
        widgets=DEFAULT_WIDGETS,
        library_dir=tmp_path / "music",  # sin pistas locales
    )
    server, base = _start_server(app)
    try:
        with urlopen(
            f"{base}/api/script-proposal?url=@canaldemo&topic=Mi%20reto&duration=45",
            timeout=5,
        ) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["ok"] is True
            assert payload["channel"] == "Canal Demo"
            script = payload["script"]
            assert script["topic"] == "Mi reto"
            assert script["total_duration"] == 45.0
            assert script["scenes"]
            assert payload["music"]["options"] == []
            assert payload["music"]["suggested_track_id"] is None
            # stock: sin keys en el entorno → ambos desactivados
            assert payload["stock"] == {"pexels": False, "pixabay": False}
    finally:
        server.shutdown()
        server.server_close()


def test_http_script_proposal_sin_url(tmp_path: Path, monkeypatch):
    """GET /api/script-proposal sin url devuelve 400."""
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{base}/api/script-proposal", timeout=5)
        assert exc_info.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_http_videos_lista_reports(tmp_path: Path, monkeypatch):
    """GET /api/videos lista los MP4 del directorio reports/."""
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "demo.mp4").write_bytes(b"fake-mp4-bytes")
    (reports / "nota.md").write_text("# no es vídeo", encoding="utf-8")
    app = DashboardApp(
        config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS
    )
    server, base = _start_server(app)
    try:
        # El método usa "reports" relativo al cwd; redirigimos a tmp via monkeypatch
        monkeypatch.setattr(
            "youber.dashboard.serve.Path",
            lambda *a, **k: __import__("pathlib").Path(*a, **k),
        )
        videos = app.videos(output_dir=str(reports))
        assert len(videos) == 1
        assert videos[0]["name"] == "demo.mp4"
        assert videos[0]["url"] == "/media/demo.mp4"
        assert videos[0]["size"] == len(b"fake-mp4-bytes")
    finally:
        server.shutdown()
        server.server_close()


def test_http_media_sirve_video(tmp_path: Path, monkeypatch):
    """GET /media/<nombre> sirve el MP4 con content-type correcto."""
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    reports = tmp_path / "reports"
    reports.mkdir()
    video_file = reports / "demo.mp4"
    video_file.write_bytes(b"fake-mp4-bytes")
    app = DashboardApp(
        config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS
    )
    server, base = _start_server(app)
    try:
        # _handle_media usa Path("reports") relativo al cwd del servidor:
        # copiamos el vídeo a un reports/ real junto al cwd para el test.
        real_reports = Path("reports")
        real_reports.mkdir(exist_ok=True)
        target = real_reports / "demo.mp4"
        target.write_bytes(b"fake-mp4-bytes")
        try:
            with urlopen(f"{base}/media/demo.mp4", timeout=5) as response:
                assert response.status == 200
                assert response.headers["Content-Type"] == "video/mp4"
                assert response.read() == b"fake-mp4-bytes"
        finally:
            target.unlink(missing_ok=True)
    finally:
        server.shutdown()
        server.server_close()


def test_http_script_render(tmp_path: Path, monkeypatch):
    """POST /api/script/render construye y renderiza el vídeo aprobado."""
    from youber.research.patterns import channel_overview
    from youber.script.generator import generate_script
    from youber.video.models import Clip, Project, TextOverlay

    channel = _fake_channel_analyzer(monkeypatch)
    script = generate_script(channel_overview(channel), topic="Mi reto", duration=30)

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    fake_project = Project(
        title="Mi reto",
        clips=[Clip(file_path=clip)],
        text_overlays=[TextOverlay(text="Hola")],
    )

    async def fake_render(project, output_path, music_path=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"mp4")
        return str(output_path)

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    monkeypatch.setattr(
        "youber.script.builder.build_project",
        lambda *a, **k: fake_project,
    )
    monkeypatch.setattr(
        "youber.video.editor.VideoEditor",
        lambda **kwargs: type(
            "Fake",
            (),
            {
                "render": staticmethod(fake_render),
                "set_music": lambda self, project, track_id, volume=0.25: None,
            },
        )(),
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
            {
                "script": script.model_dump(mode="json"),
                "clips": [str(clip)],
                "music_track_id": None,
            }
        ).encode("utf-8")
        request = Request(
            f"{base}/api/script/render",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            assert response.status == 200
            result = json.loads(response.read().decode("utf-8"))
            assert result["ok"] is True
            assert result["output"].endswith("_final.mp4")
            assert result["clips"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_http_script_render_sin_clips(tmp_path: Path, monkeypatch):
    """POST /api/script/render sin clips devuelve 400."""
    from urllib.error import HTTPError

    from youber.research.patterns import channel_overview
    from youber.script.generator import generate_script

    channel = _fake_channel_analyzer(monkeypatch)
    script = generate_script(channel_overview(channel), topic="Mi reto", duration=30)

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
            {
                "script": script.model_dump(mode="json"),
                "clips": [],
                "music_track_id": None,
            }
        ).encode("utf-8")
        request = Request(
            f"{base}/api/script/render",
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


def test_http_script_render_con_stock(tmp_path: Path, monkeypatch):
    """POST /api/script/render con use_stock descarga clips de stock y renderiza."""
    from youber.research.patterns import channel_overview
    from youber.script.generator import generate_script
    from youber.video.models import Clip, Project, TextOverlay

    channel = _fake_channel_analyzer(monkeypatch)
    script = generate_script(channel_overview(channel), topic="Mi reto", duration=30)

    clip = tmp_path / "stock-pexels-1.mp4"
    clip.write_bytes(b"fake")
    fake_project = Project(
        title="Mi reto",
        clips=[Clip(file_path=clip)],
        text_overlays=[TextOverlay(text="Hola")],
    )

    async def fake_render(project, output_path, music_path=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"mp4")
        return str(output_path)

    async def fake_fetch(scenes, dest_dir, bank="auto", per_scene=1):
        return {"escena1": [clip], "escena2": [clip]}

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    monkeypatch.setattr(
        "youber.script.builder.build_project",
        lambda *a, **k: fake_project,
    )
    monkeypatch.setattr(
        "youber.video.editor.VideoEditor",
        lambda **kwargs: type(
            "Fake",
            (),
            {
                "render": staticmethod(fake_render),
                "set_music": lambda self, project, track_id, volume=0.25: None,
            },
        )(),
    )
    monkeypatch.setattr(
        "youber.video.stock.available", lambda: {"pexels": True, "pixabay": False}
    )
    monkeypatch.setattr(
        "youber.video.stock.fetch_clips_for_scenes", fake_fetch
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
            {
                "script": script.model_dump(mode="json"),
                "clips": [],
                "music_track_id": None,
                "use_stock": True,
            }
        ).encode("utf-8")
        request = Request(
            f"{base}/api/script/render",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            assert response.status == 200
            result = json.loads(response.read().decode("utf-8"))
            assert result["ok"] is True
            assert result["clips"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_http_script_render_con_stock_sin_key(tmp_path: Path, monkeypatch):
    """use_stock sin key configurada devuelve 400 con mensaje claro."""
    from urllib.error import HTTPError

    from youber.research.patterns import channel_overview
    from youber.script.generator import generate_script

    channel = _fake_channel_analyzer(monkeypatch)
    script = generate_script(channel_overview(channel), topic="Mi reto", duration=30)

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    monkeypatch.setattr(
        "youber.video.stock.available", lambda: {"pexels": False, "pixabay": False}
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
            {
                "script": script.model_dump(mode="json"),
                "clips": [],
                "music_track_id": None,
                "use_stock": True,
            }
        ).encode("utf-8")
        request = Request(
            f"{base}/api/script/render",
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


def test_http_ytmusic_status(tmp_path: Path, monkeypatch):
    """GET /api/ytmusic-status refleja si hay headers de YT Music."""
    headers_file = tmp_path / "ytmusic_headers.json"
    monkeypatch.setattr(
        "youber.music.youtube_music.DEFAULT_HEADERS_FILE", headers_file
    )
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        with urlopen(f"{base}/api/ytmusic-status", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["headers"] is False
        headers_file.write_text("{}", encoding="utf-8")
        with urlopen(f"{base}/api/ytmusic-status", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["headers"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_http_import_ytmusic(tmp_path: Path, monkeypatch):
    """POST /api/import-ytmusic importa la biblioteca al catálogo."""

    async def fake_import(client=None, db=None, include_playlists=True):
        assert include_playlists is True
        return {"added": 3, "skipped": 1, "total": 4, "sources": ["liked", "library", "playlists"]}

    monkeypatch.setattr(
        "youber.music.youtube_music.import_ytmusic_library", fake_import
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

        body = json.dumps({"include_playlists": True}).encode("utf-8")
        request = Request(
            f"{base}/api/import-ytmusic",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            result = json.loads(response.read().decode("utf-8"))
            assert result["ok"] is True
            assert result["added"] == 3
    finally:
        server.shutdown()
        server.server_close()


def test_http_import_ytmusic_sin_auth(tmp_path: Path, monkeypatch):
    """Sin headers de YT Music, el endpoint devuelve 400 con mensaje claro."""
    from urllib.error import HTTPError

    async def fake_import(client=None, db=None, include_playlists=True):
        raise RuntimeError("YouTube Music sin autenticar")

    monkeypatch.setattr(
        "youber.music.youtube_music.import_ytmusic_library", fake_import
    )
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = b"{}"
        request = Request(
            f"{base}/api/import-ytmusic",
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


def test_http_import_channel(tmp_path: Path, monkeypatch):
    """POST /api/import-channel importa el catálogo del canal al catálogo."""

    async def fake_channel_import(self, handle, db=None):
        assert handle == "@KnightPrincessReal"
        return {
            "artist": "Knight Princess",
            "added": 3,
            "skipped": 1,
            "total": 4,
            "sources": ["songs", "albums", "singles"],
        }

    monkeypatch.setattr("youber.dashboard.serve.DashboardApp.channel_import", fake_channel_import)
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

        body = json.dumps({"handle": "@KnightPrincessReal"}).encode("utf-8")
        request = Request(
            f"{base}/api/import-channel",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            result = json.loads(response.read().decode("utf-8"))
            assert result["ok"] is True
            assert result["artist"] == "Knight Princess"
            assert result["added"] == 3
    finally:
        server.shutdown()
        server.server_close()


def test_http_import_channel_requiere_handle(tmp_path: Path, monkeypatch):
    """POST /api/import-channel sin handle devuelve 400."""
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(config_path=tmp_path / "dash.json", widgets=DEFAULT_WIDGETS)
    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = json.dumps({"handle": ""}).encode("utf-8")
        request = Request(
            f"{base}/api/import-channel",
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


def test_http_tracks(tmp_path: Path, monkeypatch):
    """GET /api/tracks devuelve la lista de canciones del catálogo."""
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(
        config_path=tmp_path / "dash.json",
        widgets=DEFAULT_WIDGETS,
        library_dir=tmp_path / "music",
    )
    # Poblar el catálogo con una pista.
    from youber.music.library import MusicLibrary
    from youber.music.models import Track

    library = MusicLibrary(tmp_path / "music")
    library.db.add_track(
        Track(
            id="t1",
            file_path=tmp_path / "cancion.mp3",
            title="Mi Canción",
            artist="Artista",
            duration=180.0,
            genre="pop",
            file_hash="abc",
        )
    )
    library.close()

    server, base = _start_server(app)
    try:
        with urlopen(f"{base}/api/tracks", timeout=5) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert len(payload["tracks"]) == 1
            track = payload["tracks"][0]
            assert track["title"] == "Mi Canción"
            assert track["artist"] == "Artista"
            assert track["duration"] == 180.0
            assert track["source"] == "local"
            assert "favorite" in track
        # Filtro por texto.
        with urlopen(f"{base}/api/tracks?q=artista", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert len(payload["tracks"]) == 1
        with urlopen(f"{base}/api/tracks?q=zzz", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["tracks"] == []
    finally:
        server.shutdown()
        server.server_close()


def test_http_toggle_favorite(tmp_path: Path, monkeypatch):
    """POST /api/tracks/favorite marca/desmarca favorita."""
    monkeypatch.setattr(
        "youber.dashboard.serve.WidgetManager",
        lambda: _FakeCollectManager(),
    )
    app = DashboardApp(
        config_path=tmp_path / "dash.json",
        widgets=DEFAULT_WIDGETS,
        library_dir=tmp_path / "music",
    )
    from youber.music.library import MusicLibrary
    from youber.music.models import Track

    library = MusicLibrary(tmp_path / "music")
    library.db.add_track(
        Track(
            id="t1",
            file_path=tmp_path / "cancion.mp3",
            title="Mi Canción",
            artist="Artista",
            duration=180.0,
            file_hash="abc",
        )
    )
    library.close()

    server, base = _start_server(app)
    try:
        from urllib.request import Request

        body = json.dumps({"track_id": "t1"}).encode("utf-8")
        request = Request(
            f"{base}/api/tracks/favorite",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
            assert result == {"id": "t1", "favorite": True}
        # Segundo toggle: vuelve a False.
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
            assert result == {"id": "t1", "favorite": False}
    finally:
        server.shutdown()
        server.server_close()


def test_http_toggle_favorite_no_existe(tmp_path: Path, monkeypatch):
    """Marcar favorita una pista inexistente devuelve 404."""
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

        body = json.dumps({"track_id": "nope"}).encode("utf-8")
        request = Request(
            f"{base}/api/tracks/favorite",
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
