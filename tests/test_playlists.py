"""Tests del almacén de playlists (youber.music.playlists)."""

from __future__ import annotations

from pathlib import Path

from youber.music.playlists import Playlist, PlaylistStore


def test_crear_y_recuperar(tmp_path: Path) -> None:
    store = PlaylistStore(tmp_path / "playlists.json")
    playlist = store.create("Mi selección", ["a", "b", "c"])
    assert playlist.id
    assert playlist.name == "Mi selección"
    assert playlist.track_ids == ["a", "b", "c"]

    loaded = store.get(playlist.id)
    assert loaded is not None
    assert loaded.name == "Mi selección"
    assert loaded.track_ids == ["a", "b", "c"]


def test_create_deduplica_keeping_order(tmp_path: Path) -> None:
    store = PlaylistStore(tmp_path / "p.json")
    playlist = store.create("Duplicados", ["x", "y", "x", "z"])
    assert playlist.track_ids == ["x", "y", "z"]


def test_all_ordenadas_por_creacion(tmp_path: Path) -> None:
    store = PlaylistStore(tmp_path / "p.json")
    first = store.create("Primera", ["a"])
    second = store.create("Segunda", ["b"])
    assert [p.id for p in store.all()] == [first.id, second.id]
    assert [p.name for p in store.all()] == ["Primera", "Segunda"]


def test_delete(tmp_path: Path) -> None:
    store = PlaylistStore(tmp_path / "p.json")
    playlist = store.create("Temporal", ["a"])
    assert store.delete(playlist.id) is True
    assert store.get(playlist.id) is None
    assert store.delete(playlist.id) is False  # ya no existe


def test_persistencia_entre_instancias(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    PlaylistStore(path).create("Persistente", ["a", "b"])
    reloaded = PlaylistStore(path)
    assert len(reloaded.all()) == 1
    assert reloaded.all()[0].name == "Persistente"


def test_stats(tmp_path: Path) -> None:
    store = PlaylistStore(tmp_path / "p.json")
    assert store.stats() == {"playlists": 0, "bytes": 0}
    store.create("Con datos", ["a"])
    stats = store.stats()
    assert stats["playlists"] == 1
    assert stats["bytes"] > 0


def test_modelo_playlist_pydantic() -> None:
    playlist = Playlist(id="p1", name="N", track_ids=["a"])
    assert playlist.created_at  # default_factory genera timestamp
    assert playlist.description == ""
