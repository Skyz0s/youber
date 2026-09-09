"""Módulo ``youber.sync``: letras sincronizadas (LRC/SRT/JSON) y subtítulos.

Flujo típico:

1. Extraer la letra: :class:`~youber.sync.lyrics.LyricsExtractor`
   (fichero .lrc/.txt/.srt o transcripción Whisper).
2. Alinear con el audio: :class:`~youber.sync.aligner.LyricsAligner`
   (timestamps precisos; heurística local sin Whisper como base).
3. Serializar: ``youber.sync.timestamps`` (LRC/SRT/JSON/texto).
4. Quemar subtítulos en el vídeo: :class:`~youber.sync.renderer.SubtitleRenderer`.

CLI: ``youber-sync extract|align|burn`` (ver ``youber.sync.cli``).
"""

from youber.sync.aligner import (
    LyricsAligner,
    Segment,
    align_lines_to_segments,
    rough_align,
    transcribe_segments,
)
from youber.sync.lyrics import LyricsExtractor
from youber.sync.renderer import RenderResult, SubtitleRenderer, SubtitleStyle
from youber.sync.timestamps import (
    LyricsDocument,
    SyncError,
    SyncLine,
    parse_document,
    parse_lrc,
    parse_lyrics_file,
    parse_srt,
    serialize,
    to_json,
    to_lrc,
    to_srt,
    to_txt,
)

__all__ = [
    "LyricsAligner",
    "LyricsDocument",
    "LyricsExtractor",
    "RenderResult",
    "Segment",
    "SubtitleRenderer",
    "SubtitleStyle",
    "SyncError",
    "SyncLine",
    "align_lines_to_segments",
    "parse_document",
    "parse_lyrics_file",
    "parse_lrc",
    "parse_srt",
    "rough_align",
    "serialize",
    "to_json",
    "to_lrc",
    "to_srt",
    "to_txt",
    "transcribe_segments",
]
