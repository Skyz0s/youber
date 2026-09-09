"""Tests del bridge youber.api: dispatcher, rutas offline y CLI.

Estrategia: sin red. Se usan bibliotecas vacías en tmp (SQLite local), el
modo ``demo`` de discovery (sintético) y mocks para research/catálogo.
"""

from __future__ import annotations

import json
from pathlib import Path

from youber.api.server import handle, list_routes

EXPECTED_ROUTES = {
    "status",
    "music.list",
    "music.search",
    "music.lyrics",
    "discovery.search",
    "research.channel",
    "schedule.list",
    "jobs.submit",
    "jobs.status",
    "jobs.history",
    "uploads.status",
}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_registry_contiene_rutas_esperadas():
    assert EXPECTED_ROUTES <= set(list_routes())


async def test_handle_ruta_desconocida():
    envelope = await handle("no.existe")
    assert envelope["ok"] is False
    assert "Ruta desconocida" in envelope["error"]


async def test_handle_error_controlado_ok_false(tmp_path: Path):
    # music.search sin query -> ApiError controlado
    envelope = await handle("music.search", {"library": str(tmp_path)})
    assert envelope["ok"] is False
    assert "query" in envelope["error"]


# ---------------------------------------------------------------------------
# status / music (catálogo vacío en tmp)
# ---------------------------------------------------------------------------


async def test_status_con_catalogo_vacio(tmp_path: Path):
    envelope = await handle("status", {"library": str(tmp_path)})
    assert envelope["ok"] is True
    data = envelope["data"]
    assert data["music"]["tracks"] == 0
    assert set(data["providers"]) >= {"pexels", "minimax", "spotify"}
    assert data["system"]["ffmpeg"] is False or isinstance(data["system"]["ffmpeg"], bool)


async def test_music_list_vacio(tmp_path: Path):
    envelope = await handle("music.list", {"library": str(tmp_path)})
    assert envelope["ok"] is True
    assert envelope["data"]["count"] == 0
    assert envelope["data"]["tracks"] == []


async def test_music_search_vacio(tmp_path: Path):
    envelope = await handle("music.search", {"query": "bohemian", "library": str(tmp_path)})
    assert envelope["ok"] is True
    assert envelope["data"]["count"] == 0


async def test_music_lyrics_pista_no_encontrada(tmp_path: Path):
    envelope = await handle("music.lyrics", {"query": "no-existe", "library": str(tmp_path)})
    assert envelope["ok"] is False
    assert "no encontrada" in envelope["error"]


class _FakeTrack:
    """Sustituto mínimo de Track (file_path + model_dump)."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    def model_dump(self, mode: str = "json") -> dict:
        return {"id": "t1", "title": "Cancion demo", "file_path": str(self.file_path)}


async def test_music_lyrics_con_sidecar(tmp_path: Path, monkeypatch):
    song = tmp_path / "cancion.mp3"
    song.write_bytes(b"fake")
    (tmp_path / "cancion.lrc").write_text(
        "[00:01.00]primera linea\n[00:02.00]segunda linea", encoding="utf-8"
    )

    def fake_find_track(_library, _query):
        return _FakeTrack(song)

    monkeypatch.setattr("youber.api.routes.music.find_track", fake_find_track)
    envelope = await handle("music.lyrics", {"query": "cancion", "library": str(tmp_path)})
    assert envelope["ok"] is True
    lyrics = envelope["data"]["lyrics"]
    assert lyrics is not None
    assert len(lyrics["lines"]) == 2
    assert lyrics["source"] == "lrc"


async def test_music_lyrics_sin_sidecar(tmp_path: Path, monkeypatch):
    song = tmp_path / "cancion.mp3"
    song.write_bytes(b"fake")

    def fake_find_track(_library, _query):
        return _FakeTrack(song)

    monkeypatch.setattr("youber.api.routes.music.find_track", fake_find_track)
    envelope = await handle("music.lyrics", {"query": "cancion", "library": str(tmp_path)})
    assert envelope["ok"] is True
    assert envelope["data"]["lyrics"] is None
    assert "No hay fichero de letra" in envelope["data"]["hint"]


# ---------------------------------------------------------------------------
# discovery (modo demo = sintético, sin red)
# ---------------------------------------------------------------------------


async def test_discovery_search_demo():
    envelope = await handle("discovery.search", {"query": "python", "mode": "demo"})
    assert envelope["ok"] is True
    data = envelope["data"]
    assert data["backend"] == "demo"
    assert len(data["channels"]) > 0


async def test_discovery_categoria_valida():
    envelope = await handle(
        "discovery.search",
        {"query": "python", "category": "tecnología", "mode": "demo", "limit": 3},
    )
    assert envelope["ok"] is True


async def test_discovery_categoria_invalida():
    envelope = await handle(
        "discovery.search", {"query": "python", "category": "no-existe", "mode": "demo"}
    )
    assert envelope["ok"] is False
    assert "Categoría desconocida" in envelope["error"]


async def test_discovery_modo_invalido():
    envelope = await handle("discovery.search", {"query": "python", "mode": "raro"})
    assert envelope["ok"] is False
    assert "Modo desconocido" in envelope["error"]


# ---------------------------------------------------------------------------
# research (analyzer mockeado; sin red)
# ---------------------------------------------------------------------------


class _FakeAnalyzer:
    async def analyze(self, channel_url: str, max_videos: int = 10, mode: str = "auto"):
        return _FakeChannel(channel_url)


class _FakeChannel:
    def __init__(self, url: str) -> None:
        self.url = url

    def model_dump(self, mode: str = "json") -> dict:
        return {"name": "Canal Demo", "url": self.url, "handle": "@demo"}


async def test_research_channel_mockeado(monkeypatch):
    monkeypatch.setattr("youber.api.routes.research.ChannelAnalyzer", _FakeAnalyzer)
    envelope = await handle("research.channel", {"channel": "@python"})
    assert envelope["ok"] is True
    assert envelope["data"]["name"] == "Canal Demo"


async def test_research_channel_sin_parametro():
    envelope = await handle("research.channel", {})
    assert envelope["ok"] is False
    assert "channel" in envelope["error"]


# ---------------------------------------------------------------------------
# schedule / uploads (sin dependencias externas)
# ---------------------------------------------------------------------------


async def test_schedule_list_vacio(monkeypatch):
    class _FakeStorage:
        def load(self):
            return []

    monkeypatch.setattr("youber.api.routes.schedule.JobStorage", lambda: _FakeStorage())
    envelope = await handle("schedule.list", {})
    assert envelope["ok"] is True
    assert envelope["data"]["count"] == 0


async def test_uploads_status_sin_credenciales():
    envelope = await handle("uploads.status", {})
    assert envelope["ok"] is True
    data = envelope["data"]
    assert "youtube" in data
    assert data["youtube"]["ready"] is False


# ---------------------------------------------------------------------------
# CLI (smoke)
# ---------------------------------------------------------------------------


def test_cli_status_json(tmp_path: Path, capsys):
    from youber.api.cli import main

    code = main(["status", "--library", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["ok"] is True


def test_cli_music_list(tmp_path: Path, capsys):
    from youber.api.cli import main

    code = main(["music", "list", "--library", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["data"]["count"] == 0


def test_cli_error_devuelve_codigo_1(capsys):
    from youber.api.cli import main

    # jobs submit produce sin topic/pattern -> ApiError controlado (no argparse)
    code = main(["jobs", "submit", "--type", "produce"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["ok"] is False


def test_cli_parser_tiene_subcomandos():
    from youber.api.cli import build_parser

    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    assert {"status", "music", "discovery", "research", "schedule", "jobs", "uploads"} <= set(choices)
