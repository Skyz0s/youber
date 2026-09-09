"""CLI ``youber-sync``: letras sincronizadas y subtítulos en vídeo.

Comandos:

- ``extract <fichero>``: extrae la letra (texto plano) de .lrc/.txt/.srt/.json.
- ``align --audio <audio> [--lyrics <letra>] [--whisper]``: alinea la letra
  con el audio y genera LRC/SRT/JSON con timestamps.
- ``burn --video <vídeo> --lyrics <lrc|srt|json>``: quema los subtítulos
  sincronizados en el vídeo final (MP4).

Ejemplos:

.. code-block:: bash

    youber-sync extract letra.lrc
    youber-sync align --audio cancion.mp3 --lyrics letra.txt -o letra.lrc
    youber-sync align --track abc123 --lyrics letra.txt --whisper -f json
    youber-sync burn --video final.mp4 --lyrics letra.lrc -o final_sub.mp4
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from youber.sync.aligner import LyricsAligner
from youber.sync.lyrics import LyricsExtractor
from youber.sync.renderer import (
    SUBTITLE_STYLE_PRESETS,
    SubtitleRenderer,
    subtitle_style_preset,
)
from youber.sync.timestamps import SyncError, serialize

_FORMATS = ("lrc", "srt", "json", "txt")


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-sync``."""
    parser = argparse.ArgumentParser(
        prog="youber-sync",
        description="Youber: letras sincronizadas con el audio y subtítulos en vídeo",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- extract -----------------------------------------------------------
    extract = sub.add_parser(
        "extract", help="Extrae la letra (texto plano) de un fichero"
    )
    extract.add_argument("file", help="Fichero .lrc/.txt/.srt/.json")

    # --- align -------------------------------------------------------------
    align = sub.add_parser(
        "align",
        help="Alinea la letra con el audio y genera LRC/SRT/JSON con timestamps",
    )
    entrada = align.add_mutually_exclusive_group(required=True)
    entrada.add_argument("--audio", help="Ruta del audio (MP3/WAV/FLAC/...)")
    entrada.add_argument("--track", help="ID de pista del catálogo youber.music")
    align.add_argument(
        "--library", default="music",
        help="Directorio del catálogo de música (para --track; default: music)",
    )
    align.add_argument(
        "--lyrics",
        help="Fichero de letra .lrc/.txt/.srt (si se omite, transcribe con Whisper)",
    )
    align.add_argument(
        "--whisper", action="store_true",
        help="Transcribe con Whisper para timestamps precisos (requiere instalar "
        "faster-whisper: pip install 'youber[sync]')",
    )
    align.add_argument(
        "--model", default="small",
        help="Modelo Whisper: tiny|base|small|medium|large-v3 (default: small)",
    )
    align.add_argument("--language", default=None, help="Código ISO-639-1 del idioma")
    align.add_argument(
        "-f", "--format", choices=_FORMATS, default="lrc",
        help="Formato de salida (default: lrc)",
    )
    align.add_argument(
        "-o", "--output", default=None,
        help="Fichero de salida (default: imprime por stdout)",
    )
    align.add_argument("--title", default=None, help="Título para metadatos")
    align.add_argument("--artist", default=None, help="Artista para metadatos")

    # --- burn --------------------------------------------------------------
    burn = sub.add_parser(
        "burn", help="Quema subtítulos sincronizados en un vídeo (FFmpeg/libass)"
    )
    burn.add_argument("--video", required=True, help="Vídeo de entrada")
    burn.add_argument(
        "--lyrics", required=True,
        help="Fichero de letra temporizado (.lrc/.srt/.json)",
    )
    burn.add_argument("-o", "--output", default=None, help="MP4 de salida")
    burn.add_argument("--font", default=None, help="Fuente (default: Arial en Windows)")
    burn.add_argument("--font-size", type=int, default=None, help="Tamaño de fuente")
    burn.add_argument(
        "--style",
        choices=sorted(SUBTITLE_STYLE_PRESETS),
        default="clean",
        help="Estilo de subtítulos (default: clean)",
    )

    return parser


def _resolve_audio(args: argparse.Namespace) -> tuple[Path, str | None, str | None]:
    """Resuelve el audio (ruta directa o pista del catálogo) + metadatos."""
    if args.audio:
        return Path(args.audio), None, None
    from youber.music.library import MusicLibrary

    library = MusicLibrary(args.library)
    try:
        track = library.get(args.track)
    finally:
        library.close()
    if track is None:
        raise SyncError(
            f"Pista no encontrada: {args.track!r} en el catálogo {args.library!r}"
        )
    return track.file_path, track.title, track.artist


async def _cmd_extract(args: argparse.Namespace) -> int:
    extractor = LyricsExtractor()
    plain = await extractor.extract_from_file(Path(args.file))
    if plain is None:
        return 1
    print(plain)
    return 0


async def _cmd_align(args: argparse.Namespace) -> int:
    audio, track_title, track_artist = _resolve_audio(args)
    if not audio.is_file():
        raise SyncError(f"Audio no encontrado: {audio}")

    lyrics_path = Path(args.lyrics) if args.lyrics else None
    if lyrics_path is not None and not lyrics_path.is_file():
        raise SyncError(f"Letra no encontrada: {lyrics_path}")

    model_size = args.model if (args.whisper or lyrics_path is None) else None
    document = await LyricsAligner().align(
        audio,
        lyrics_path,
        model_size=model_size,
        language=args.language,
    )

    if args.title:
        document.title = args.title
    elif document.title is None:
        document.title = track_title
    if args.artist:
        document.artist = args.artist
    elif document.artist is None:
        document.artist = track_artist

    output = serialize(document, args.format)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Escrito: {args.output} (source={document.source}, "
              f"{len(document.lines)} líneas)")
    else:
        print(output, end="")
    return 0


async def _cmd_burn(args: argparse.Namespace) -> int:
    style = subtitle_style_preset(args.style)
    if args.font:
        style = style.model_copy(update={"font_name": args.font})
    if args.font_size:
        style = style.model_copy(update={"font_size": args.font_size})
    result = await SubtitleRenderer().render(
        args.video, args.lyrics, output=args.output, style=style
    )
    print(
        f"Subtítulos quemados: {result.output_path} | "
        f"{result.duration:.1f}s | {result.resolution[0]}x{result.resolution[1]}"
    )
    return 0


async def _run(args: argparse.Namespace) -> int:
    if args.command == "extract":
        return await _cmd_extract(args)
    if args.command == "align":
        return await _cmd_align(args)
    if args.command == "burn":
        return await _cmd_burn(args)
    raise SyncError(f"Comando desconocido: {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    """Entry point para setuptools (``youber-sync``)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except SyncError as exc:
        print(f"[youber-sync] error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
