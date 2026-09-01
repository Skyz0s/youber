"""Importación de la biblioteca de Apple Music/iTunes (fichero XML).

La app Música/iTunes permite **exportar la biblioteca completa** a un
fichero plist XML (Archivo → Biblioteca → Exportar biblioteca…), que
contiene todas las canciones con sus metadatos (título, artista, álbum,
duración, género y el ``Persistent ID`` de Apple).

Este módulo lee ese XML y lo importa al catálogo de BARF como pistas
``source=apple`` con su ``external_id`` (el Persistent ID, estable entre
exportaciones). **Solo metadatos: nunca se descarga ni copia audio.**

Uso típico (Mac: ``~/Music/Music/Music Library.xml``; Windows/iTunes:
``~/Music/iTunes/iTunes Music Library.xml``):

.. code-block:: python

    from youber.music.apple_library import import_apple_library

    summary = await import_apple_library("Music Library.xml")
    print(summary)  # {'added': ..., 'skipped': ..., 'total': ...}
"""

from __future__ import annotations

import hashlib
import plistlib
from pathlib import Path

from loguru import logger

from youber.music.database import MusicDatabase
from youber.music.models import Track, TrackSource
from youber.music.providers import CloudHit

# Claves del plist de iTunes/Apple Music que nos interesan.
_KEY_NAME = "Name"
_KEY_ARTIST = "Artist"
_KEY_ALBUM = "Album"
_KEY_GENRE = "Genre"
_KEY_TOTAL_TIME = "Total Time"
_KEY_PERSISTENT_ID = "Persistent ID"
_KEY_HAS_VIDEO = "Has Video"
_KEY_PODCAST = "Podcast"
_KEY_TRACK_ID = "Track ID"


def parse_apple_library(path: str | Path) -> list[CloudHit]:
    """Lee el XML de la biblioteca de Apple y devuelve sus canciones.

    Args:
        path: Ruta del fichero plist XML exportado por Música/iTunes.

    Returns:
        Lista de :class:`CloudHit` con los metadatos de cada canción
        (se omiten vídeos, podcasts y entradas sin título).

    Raises:
        FileNotFoundError: si el fichero no existe.
        plistlib.InvalidFileException: si el fichero no es un plist válido.
    """
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"Biblioteca de Apple no encontrada: {path}")

    with file.open("rb") as handle:
        data = plistlib.load(handle)

    tracks = data.get("Tracks", {})
    hits: list[CloudHit] = []
    for item in tracks.values():
        if not isinstance(item, dict):
            continue
        title = str(item.get(_KEY_NAME, "")).strip()
        if not title:
            continue
        if item.get(_KEY_HAS_VIDEO) or item.get(_KEY_PODCAST):
            continue
        persistent_id = str(item.get(_KEY_PERSISTENT_ID, "")).strip()
        if not persistent_id:
            persistent_id = _fallback_id(title, item)
        total_time_ms = item.get(_KEY_TOTAL_TIME)
        hits.append(
            CloudHit(
                source=TrackSource.APPLE,
                external_id=persistent_id,
                title=title,
                artist=_clean(item.get(_KEY_ARTIST)),
                album=_clean(item.get(_KEY_ALBUM)),
                duration_s=(total_time_ms / 1000) if total_time_ms else None,
                genre=_clean(item.get(_KEY_GENRE)),
            )
        )
    logger.debug(f"parse_apple_library({path}): {len(hits)} canciones")
    return hits


def _clean(value: object) -> str | None:
    """Convierte un valor del plist a str limpio (o ``None``)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _fallback_id(title: str, item: dict) -> str:
    """Id estable para pistas sin Persistent ID (hash de sus metadatos)."""
    raw = f"{title}|{item.get(_KEY_ARTIST)}|{item.get(_KEY_ALBUM)}|{item.get(_KEY_TOTAL_TIME)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


async def import_apple_library(
    path: str | Path,
    db: MusicDatabase | None = None,
) -> dict[str, int]:
    """Importa la biblioteca de Apple al catálogo (idempotente).

    Las canciones ya importadas (mismo Persistent ID) se omiten, así que
    reimportar el mismo XML (o uno más reciente) no duplica nada.

    Args:
        path: Ruta del fichero plist XML.
        db: Base de datos del catálogo. Si es ``None``, se crea una
            temporal (solo para probar/validar).

    Returns:
        Resumen: ``added`` (nuevas), ``skipped`` (ya existentes) y ``total``.
    """
    if db is None:
        import tempfile

        temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        temp_path = Path(temp_file.name)
        temp_file.close()
        database = MusicDatabase(temp_path)
        own_db = True
    else:
        database = db
        own_db = False

    try:
        hits = parse_apple_library(path)
        added = skipped = 0
        for hit in hits:
            if database.get_by_external_id(hit.source, hit.external_id):
                skipped += 1
                continue
            track = _hit_to_track(hit)
            track.id = database.new_id()
            database.add_track(track)
            added += 1
        logger.info(
            f"import_apple_library({path}): +{added} nuevas, "
            f"{skipped} ya existentes"
        )
        return {"added": added, "skipped": skipped, "total": len(hits)}
    finally:
        if own_db:
            database.close()
            temp_path.unlink(missing_ok=True)


def _hit_to_track(hit: CloudHit) -> Track:
    """Convierte un :class:`CloudHit` de Apple en una pista del catálogo."""
    return Track(
        id="",
        file_path=Path(f"cloud:apple:{hit.external_id}"),
        title=hit.title,
        artist=hit.artist,
        duration=hit.duration_s or 0.0,
        genre=hit.genre,
        source=TrackSource.APPLE,
        external_id=hit.external_id,
        album=hit.album,
        file_hash=f"cloud:apple:{hit.external_id}",
    )
