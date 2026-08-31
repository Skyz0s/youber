"""Importación de catálogos de música desde CSV (fuente: YouTube Music).

Lee un CSV con canciones (título, artista, álbum, duración...) y las busca
en YouTube Music a través de :class:`YouTubeMusicClient` para enriquecerlas
con su id y metadatos de la nube. **No descarga archivos**: solo metadatos
públicos, para usar la música de forma legal y ética en los vídeos editados.
"""

from __future__ import annotations

import csv
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from youber.music.youtube_music import YouTubeMusicClient

# Alias de columnas aceptados en el CSV (normalizados a minúsculas).
_COLUMN_ALIASES = {
    "title": ("title", "titulo", "título", "cancion", "canción", "song"),
    "artist": ("artist", "artista", "author", "autor"),
    "album": ("album", "álbum", "disco"),
    "duration": ("duration", "duracion", "duración", "length"),
}


class SongImport(BaseModel):
    """Resultado de importar una fila del CSV."""

    title: str
    artist: str = ""
    album: str = ""
    duration: int | None = None
    ytmusic_id: str | None = None
    matched: bool = False
    error: str | None = None


class ImportResult(BaseModel):
    """Resumen de una importación de CSV."""

    total: int = 0
    matched: int = 0
    unmatched: int = 0
    errors: int = 0
    songs: list[SongImport] = Field(default_factory=list)


def _normalize_columns(row: dict[str, str]) -> dict[str, str]:
    """Reasigna las columnas del CSV a nombres canónicos (title/artist/...)."""
    normalized: dict[str, str] = {}
    lookup = {
        alias.lower(): canonical
        for canonical, aliases in _COLUMN_ALIASES.items()
        for alias in aliases
    }
    for key, value in row.items():
        canonical = lookup.get(key.strip().lower())
        if canonical and value:
            normalized[canonical] = value.strip()
    return normalized


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """Lee un CSV (UTF-8 con o sin BOM) y devuelve las filas normalizadas.

    Args:
        path: Ruta del fichero CSV.

    Returns:
        Lista de dicts con las columnas canónicas (``title``, ``artist``,
        ``album``, ``duration``) presentes en cada fila.
    """
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"CSV no encontrado: {path}")

    rows: list[dict[str, str]] = []
    with file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(_normalize_columns(raw))
    return rows


async def import_csv(
    csv_path: str | Path,
    client: YouTubeMusicClient | None = None,
    match: bool = True,
) -> ImportResult:
    """Importa un CSV de canciones y las busca en YouTube Music.

    Para cada fila con ``title`` se llama a ``client.search_song``; si hay
    coincidencia, la canción se marca como ``matched`` con su ``ytmusic_id``
    y metadatos de la nube.

    Args:
        csv_path: Ruta del fichero CSV.
        client: Cliente de YouTube Music (si es ``None``, se crea uno nuevo;
            sin headers autenticados, la búsqueda funciona en modo anónimo).
        match: Si ``False``, solo se lee el CSV sin buscar (para validar).

    Returns:
        Un :class:`ImportResult` con el resumen y las canciones procesadas.
    """
    rows = read_csv(csv_path)
    client = client or YouTubeMusicClient()
    result = ImportResult(total=len(rows))

    for row in rows:
        title = row.get("title", "")
        if not title:
            result.errors += 1
            result.songs.append(SongImport(title="", error="Sin título"))
            continue

        song = SongImport(
            title=title,
            artist=row.get("artist", ""),
            album=row.get("album", ""),
            duration=_parse_duration(row.get("duration")),
        )

        if not match:
            result.songs.append(song)
            continue

        try:
            found = await client.search_song(title, song.artist)
        except Exception as exc:
            logger.warning(f"No se pudo buscar «{title}»: {exc}")
            song.error = str(exc)
            result.errors += 1
            result.songs.append(song)
            continue

        if found:
            song.matched = True
            song.ytmusic_id = found.get("id")
            song.artist = found.get("artist") or song.artist
            song.album = found.get("album") or song.album
            song.duration = found.get("duration") or song.duration
            result.matched += 1
        else:
            result.unmatched += 1
        result.songs.append(song)

    logger.info(
        f"Importación: {result.matched} coincidencias, "
        f"{result.unmatched} sin coincidencia, {result.errors} errores"
    )
    return result


def _parse_duration(value: str | None) -> int | None:
    """Convierte una duración (``"3:45"`` o segundos) a segundos."""
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    parts = value.split(":")
    try:
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds
    except ValueError:
        return None
