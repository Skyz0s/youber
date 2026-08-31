"""Catálogo de música de BARF.

Gestión de una biblioteca musical local: escaneo de ficheros de audio,
metadatos en SQLite, etiquetas de estado de ánimo (mood), búsqueda y
sugerencias para usar como música de fondo en tus vídeos.

Límites éticos (igual que el resto del framework):

- Solo música propia o con licencia; sin piratear.
- El catálogo es una herramienta de organización, no de distribución.
- Uso educativo y de investigación.
"""

from youber.music.cli import build_parser
from youber.music.cli import main as cli_main
from youber.music.database import MusicDatabase
from youber.music.importers import ImportResult, SongImport, import_csv, read_csv
from youber.music.library import MusicLibrary
from youber.music.matcher import score_track, search_tracks, suggest_tracks
from youber.music.models import Mood, Track
from youber.music.scanner import scan_directory, scan_library
from youber.music.youtube_music import YouTubeMusicClient

__all__ = [
    "ImportResult",
    "Mood",
    "MusicDatabase",
    "MusicLibrary",
    "SongImport",
    "Track",
    "YouTubeMusicClient",
    "build_parser",
    "cli_main",
    "import_csv",
    "read_csv",
    "scan_directory",
    "scan_library",
    "score_track",
    "search_tracks",
    "suggest_tracks",
]
