"""Tests de la importación de la biblioteca de Apple (plist XML)."""

import asyncio
import plistlib
from pathlib import Path

import pytest

from youber.music.apple_library import (
    import_apple_library,
    parse_apple_library,
)
from youber.music.database import MusicDatabase
from youber.music.models import TrackSource


def make_library_xml(path: Path, tracks: list[dict] | None = None) -> Path:
    """Escribe un plist XML de biblioteca de Apple de prueba."""
    default_tracks = [
        {
            "Track ID": 100,
            "Name": "Canción Uno",
            "Artist": "Artista A",
            "Album": "Álbum Uno",
            "Genre": "Pop",
            "Total Time": 200000,
            "Persistent ID": "AAA111",
        },
        {
            "Track ID": 101,
            "Name": "Canción Dos",
            "Artist": "Artista B",
            "Album": "Álbum Dos",
            "Genre": "Rock",
            "Total Time": 180000,
            "Persistent ID": "BBB222",
        },
        {
            "Track ID": 102,
            "Name": "Vídeo musical",
            "Artist": "Artista A",
            "Has Video": True,
        },
        {
            "Track ID": 103,
            "Name": "Podcast",
            "Podcast": True,
        },
        {
            "Track ID": 104,
            "Artist": "Sin título",
        },
    ]
    payload = {
        "Application Version": "12.11.3.17",
        "Tracks": {str(i + 1): track for i, track in enumerate(tracks or default_tracks)},
    }
    file = path / "Music Library.xml"
    with file.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)
    return file


def test_parse_apple_library(tmp_path: Path):
    xml = make_library_xml(tmp_path)
    hits = parse_apple_library(xml)
    # Solo las 2 canciones reales: sin vídeos, podcasts ni entradas sin título.
    assert len(hits) == 2
    first = hits[0]
    assert first.source == TrackSource.APPLE
    assert first.external_id == "AAA111"
    assert first.title == "Canción Uno"
    assert first.artist == "Artista A"
    assert first.album == "Álbum Uno"
    assert first.genre == "Pop"
    assert first.duration_s == 200.0


def test_parse_apple_library_fallback_id(tmp_path: Path):
    xml = make_library_xml(
        tmp_path,
        tracks=[{"Track ID": 1, "Name": "Sin ID persistente", "Artist": "X"}],
    )
    hits = parse_apple_library(xml)
    assert len(hits) == 1
    assert len(hits[0].external_id) == 16  # hash sha1 truncado


def test_parse_apple_library_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_apple_library(tmp_path / "no.xml")


def test_import_apple_library_idempotente(tmp_path: Path):
    xml = make_library_xml(tmp_path)
    db = MusicDatabase(tmp_path / "catalogo.db")

    first = asyncio.run(import_apple_library(xml, db))
    assert first["added"] == 2
    assert first["skipped"] == 0
    assert db.count() == 2

    # Reimportar el mismo XML no duplica.
    second = asyncio.run(import_apple_library(xml, db))
    assert second["added"] == 0
    assert second["skipped"] == 2
    assert db.count() == 2

    track = db.get_by_external_id(TrackSource.APPLE, "AAA111")
    assert track is not None
    assert track.title == "Canción Uno"


def test_import_apple_library_db_propia(tmp_path: Path):
    xml = make_library_xml(tmp_path)
    summary = asyncio.run(import_apple_library(xml))
    assert summary["added"] == 2
