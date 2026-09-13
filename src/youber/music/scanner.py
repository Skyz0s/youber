"""Escaneo del catálogo de música local.

Localiza ficheros de audio (MP3, WAV, M4A, FLAC), extrae metadatos con
``ffprobe`` (duración, título, artista) y calcula el hash del fichero para
detectar cambios.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from loguru import logger

from youber.audio._ffmpeg import probe_duration, run_command
from youber.music.lyrics_analyzer import LyricsAnalyzer
from youber.music.models import Track, TrackSource

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac"}


def scan_directory(directory: str | Path, extensions: set[str] | None = None) -> list[Path]:
    """Devuelve los ficheros de audio de un directorio (recursivo).

    Args:
        directory: Directorio a escanear.
        extensions: Extensiones a incluir (por defecto: audio soportado).

    Returns:
        Lista ordenada de rutas de audio.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"No es un directorio válido: {directory}")
    wanted = extensions or AUDIO_EXTENSIONS
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in wanted
    )
    logger.debug(f"scan_directory: {len(files)} fichero(s) en {root}")
    return files


def file_hash(path: str | Path, chunk_size: int = 64 * 1024) -> str:
    """Calcula el SHA-256 de un fichero (para detectar cambios)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


async def _probe_tags(path: Path) -> dict[str, str]:
    """Extrae metadatos (título, artista, género) con ffprobe (mejor esfuerzo)."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format_tags=title,artist,genre",
        "-of",
        "default=noprint_wrappers=1",
        str(path),
    ]
    result = await run_command(cmd)
    tags: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            if value:
                tags[key.lower()] = value
    return tags


async def probe_track(
    path: str | Path,
    lyrics_dir: str | Path | None = None,
    lyrics_analyzer: LyricsAnalyzer | None = None,
) -> Track:
    """Analiza un fichero de audio y construye su :class:`Track`.

    Usa ``ffprobe`` para la duración y los metadatos; el título cae al
    nombre del fichero si no hay etiqueta.
    Si se proporciona un directorio de letras, intenta analizar las letras
    correspondientes para enriquecer la pista con información temática.

    Args:
        path: Ruta del fichero de audio.
        lyrics_dir: Directorio donde buscar archivos de letras (opcional).
        lyrics_analyzer: Instancia de analizador de letras (opcional).

    Returns:
        La pista con sus metadatos básicos y opcionalmente análisis de letras.
    """
    file_path = Path(path)
    duration = await probe_duration(file_path)
    tags = await _probe_tags(file_path)

    track = Track(
        id="",
        file_path=file_path,
        title=tags.get("title") or file_path.stem,
        artist=tags.get("artist"),
        duration=duration,
        genre=tags.get("genre"),
        file_hash=file_hash(file_path),
    )

    # Analizar letras si se proporcionó directorio y analizador
    if lyrics_dir is not None and lyrics_analyzer is not None:
        try:
            lyrics_analysis = lyrics_analyzer.analyze_track_lyrics(track, Path(lyrics_dir))
            if lyrics_analysis is not None:
                track.lyrical_themes = lyrics_analysis.themes
                track.lyrical_sentiment = lyrics_analysis.sentiment
        except Exception as exc:
            # No fallar el escaneo si el análisis de letras falla
            logger.warning(f"No se pudieron analizar las letras para {path}: {exc}")

    return track


async def scan_library(
    directory: str | Path,
    db,
    extensions: set[str] | None = None,
    lyrics_dir: str | Path | None = None,
) -> dict[str, int]:
    """Escanea un directorio y sincroniza el catálogo con la base de datos.

    Añade pistas nuevas, actualiza las que cambiaron (hash distinto,
    conservando favorito y uso) y deja intactas las que siguen igual.
    Si se proporciona un directorio de letras, intenta analizar las letras
    correspondientes para enriquecer las pistas con información temática.

    Args:
        directory: Directorio a escanear.
        db: Instancia de :class:`~youber.music.database.MusicDatabase`.
        extensions: Extensiones a incluir (opcional).
        lyrics_dir: Directorio donde buscar archivos de letras (opcional).

    Returns:
        Resumen con contadores: ``added``, ``updated``, ``unchanged``,
        ``removed`` y ``errors``.
    """
    summary = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0, "errors": 0}
    files = scan_directory(directory, extensions)
    seen: set[str] = set()

    # Crear analizador de letras una sola vez si se proporcionó directorio
    lyrics_analyzer = LyricsAnalyzer() if lyrics_dir is not None else None

    for path in files:
        try:
            track = await probe_track(path, lyrics_dir, lyrics_analyzer)
        except Exception as exc:
            logger.warning(f"No se pudo analizar {path}: {exc}")
            summary["errors"] += 1
            continue

        seen.add(str(path))
        existing = db.get_by_path(path)
        if existing is None:
            track.id = db.new_id()
            db.add_track(track)
            summary["added"] += 1
        elif existing.file_hash != track.file_hash:
            track.id = existing.id
            track.favorite = existing.favorite
            track.usage_count = existing.usage_count
            track.last_used = existing.last_used
            track.added_at = existing.added_at
            db.update_track(track)
            summary["updated"] += 1
        else:
            summary["unchanged"] += 1

    # Pistas locales que ya no están en disco: se retiran del catálogo.
    # Las pistas importadas de plataformas (source != local) no se tocan:
    # su ruta sintética no existe en disco por diseño.
    for track in db.list_tracks():
        if track.source != TrackSource.LOCAL:
            continue
        if str(track.file_path) not in seen:
            db.delete_track(track.id)
            summary["removed"] += 1

    logger.info(
        f"scan_library: +{summary['added']} ~{summary['updated']} "
        f"={summary['unchanged']} -{summary['removed']} !{summary['errors']}"
    )
    return summary
