"""CLI ``youber-music``: gestiona el catálogo local de música de BARF.

Comandos: ``scan``, ``list``, ``search``, ``suggest``, ``favorite``,
``info`` y ``remove``.

Ejemplos:

.. code-block:: bash

    youber-music --library ~/musica scan
    youber-music --library ~/musica list
    youber-music --library ~/musica search --mood relajante
    youber-music --library ~/musica suggest --mood energética -n 5
    youber-music --library ~/musica favorite <id>
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.console import Console
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.music.audio_features.cli import (
    register as register_audio_features,
)
from youber.music.audio_features.cli import (
    run as run_audio_features,
)
from youber.music.library import MusicLibrary
from youber.music.models import Mood, Track

console = Console()

DEFAULT_LIBRARY = Path("music")


def _mood(value: str | None) -> Mood | None:
    """Convierte el texto del usuario en un :class:`Mood` (o ``None``)."""
    if not value:
        return None
    lowered = value.strip().lower()
    for mood in Mood:
        if mood.value.lower() == lowered or mood.name.lower() == lowered:
            return mood
    raise argparse.ArgumentTypeError(
        f"Mood desconocido: {value!r}. Válidos: {', '.join(m.value for m in Mood)}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-music``."""
    parser = argparse.ArgumentParser(
        prog="youber-music",
        description="BARF: catálogo local de música (uso educativo)",
    )
    parser.add_argument(
        "--library",
        default=str(DEFAULT_LIBRARY),
        help=f"Directorio de música (por defecto: {DEFAULT_LIBRARY})",
    )
    parser.add_argument("--db", default=None, help="Ruta de la base de datos SQLite")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="Escanea el directorio y sincroniza el catálogo")

    sub.add_parser("list", help="Lista todas las pistas del catálogo")

    search = sub.add_parser("search", help="Busca pistas por mood/género/texto")
    search.add_argument("--mood", type=_mood, help="Estado de ánimo (p. ej. relajante)")
    search.add_argument("--genre", help="Género (coincidencia parcial)")
    search.add_argument("--text", help="Texto libre (título/artista/género)")
    search.add_argument("--favorite", action="store_true", help="Solo favoritas")
    search.add_argument("--bpm-min", type=int, help="BPM mínimo")
    search.add_argument("--bpm-max", type=int, help="BPM máximo")

    suggest = sub.add_parser("suggest", help="Sugiere pistas para un estado de ánimo")
    suggest.add_argument("--mood", type=_mood, help="Estado de ánimo deseado")
    suggest.add_argument("--text", help="Tema o texto libre")
    suggest.add_argument("-n", "--limit", type=int, default=5, help="Número de sugerencias")

    favorite = sub.add_parser("favorite", help="Marca/desmarca una pista como favorita")
    favorite.add_argument("id", help="Id de la pista")
    favorite.add_argument("--no", dest="favorite", action="store_false", default=True)

    info = sub.add_parser("info", help="Muestra los detalles de una pista")
    info.add_argument("id", help="Id de la pista")

    remove = sub.add_parser("remove", help="Elimina una pista del catálogo")
    remove.add_argument("id", help="Id de la pista")

    import_cloud = sub.add_parser(
        "import-cloud",
        help="Importa pistas desde una plataforma (apple/spotify) por metadatos públicos",
    )
    import_cloud.add_argument("query", help="Texto de búsqueda (p. ej. 'lofi beats')")
    import_cloud.add_argument(
        "--source",
        choices=["apple", "spotify"],
        default="apple",
        help="Plataforma (apple = iTunes Search API, sin API key; spotify = Web API con credenciales)",
    )
    import_cloud.add_argument("-n", "--limit", type=int, default=10, help="Número máximo de resultados")
    import_cloud.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo busca y muestra resultados, sin guardar",
    )

    import_library = sub.add_parser(
        "import-apple-library",
        help="Importa TODA tu biblioteca de Apple Music/iTunes desde su XML exportado",
    )
    import_library.add_argument(
        "xml",
        help=(
            "Ruta del fichero XML exportado (Archivo → Biblioteca → Exportar "
            "biblioteca…). Mac: ~/Music/Music/Music Library.xml; "
            "Windows/iTunes: ~/Music/iTunes/iTunes Music Library.xml"
        ),
    )
    import_library.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo lee y muestra el resumen, sin guardar",
    )

    import_yt = sub.add_parser(
        "import-ytmusic-library",
        help="Importa tu biblioteca de YouTube Music (Me gusta + guardadas + playlists)",
    )
    import_yt.add_argument(
        "--no-playlists",
        action="store_true",
        help="No importar playlists (solo Me gusta y guardadas)",
    )

    import_channel = sub.add_parser(
        "import-channel",
        help="Importa el catálogo público de un artista/canal de YouTube Music (álbumes + singles)",
    )
    import_channel.add_argument("handle", help="Nombre o handle del artista (p. ej. '@KnightPrincessReal')")
    import_channel.add_argument(
        "--no-albums",
        action="store_true",
        help="No importar canciones de álbumes",
    )
    import_channel.add_argument(
        "--no-singles",
        action="store_true",
        help="No importar canciones de singles",
    )

    sub.add_parser(
        "enrich-genres",
        help="Asigna género a cada pista automáticamente (iTunes Search API, sin API key)",
    )

    register_audio_features(sub)

    return parser


def _print_track(track: Track) -> None:
    moods = ", ".join(mood.value for mood in track.moods) or "-"
    console.print(f"[bold]{track.title}[/] — {track.artist or '?'}")
    console.print(f"  id: {track.id} | {track.duration:.1f}s | {track.genre or '-'}")
    console.print(f"  moods: {moods} | bpm: {track.bpm or '-'} | key: {track.key or '-'}")
    console.print(
        f"  favorita: {'⭐' if track.favorite else 'no'} | usos: {track.usage_count} | "
        f"último uso: {track.last_used or '-'}"
    )


def _print_table(tracks: list[Track]) -> None:
    table = Table(title=f"{len(tracks)} pista(s)")
    table.add_column("Id", style="dim")
    table.add_column("Título")
    table.add_column("Artista")
    table.add_column("Duración", justify="right")
    table.add_column("Moods")
    table.add_column("Fav", justify="center")
    for track in tracks:
        table.add_row(
            track.id,
            track.title,
            track.artist or "-",
            f"{track.duration:.0f}s",
            ", ".join(mood.value for mood in track.moods) or "-",
            "⭐" if track.favorite else "",
        )
    console.print(table)


def run(args: argparse.Namespace) -> None:
    """Ejecuta el subcomando indicado sobre el catálogo."""
    library = MusicLibrary(args.library, db_path=args.db)
    try:
        if args.command in ("analyze", "recommend"):
            run_audio_features(args, library)
            return
        if args.command == "scan":
            summary = asyncio.run(library.scan())
            console.print(
                f"[green]Catálogo sincronizado:[/] +{summary['added']} nuevas, "
                f"~{summary['updated']} actualizadas, ={summary['unchanged']} sin cambios, "
                f"-{summary['removed']} eliminadas, !{summary['errors']} errores"
            )
        elif args.command == "list":
            _print_table(library.all())
        elif args.command == "search":
            tracks = library.search(
                mood=args.mood,
                genre=args.genre,
                text=args.text,
                favorite=args.favorite or None,
                bpm_min=args.bpm_min,
                bpm_max=args.bpm_max,
            )
            _print_table(tracks)
        elif args.command == "suggest":
            tracks = library.suggest(mood=args.mood, text=args.text, limit=args.limit)
            _print_table(tracks)
        elif args.command == "favorite":
            ok = library.mark_favorite(args.id, args.favorite)
            if not ok:
                console.print(f"[red]Pista no encontrada: {args.id}[/]")
                raise SystemExit(1)
            console.print(f"⭐ Pista {args.id} {'marcada como favorita' if args.favorite else 'desmarcada'}")
        elif args.command == "info":
            track = library.get(args.id)
            if track is None:
                console.print(f"[red]Pista no encontrada: {args.id}[/]")
                raise SystemExit(1)
            _print_track(track)
        elif args.command == "remove":
            ok = library.remove(args.id)
            if not ok:
                console.print(f"[red]Pista no encontrada: {args.id}[/]")
                raise SystemExit(1)
            console.print(f"🗑️  Pista {args.id} eliminada")
        elif args.command == "import-cloud":
            asyncio.run(_run_import_cloud(args, library))
        elif args.command == "import-apple-library":
            asyncio.run(_run_import_apple_library(args, library))
        elif args.command == "import-ytmusic-library":
            asyncio.run(_run_import_ytmusic_library(args, library))
        elif args.command == "import-channel":
            asyncio.run(_run_import_channel(args, library))
        elif args.command == "enrich-genres":
            asyncio.run(_run_enrich_genres(library))
    finally:
        library.close()


async def _run_import_cloud(args: argparse.Namespace, library: MusicLibrary) -> None:
    """Ejecuta ``import-cloud``: busca en la plataforma y añade al catálogo."""
    from youber.music.models import TrackSource
    from youber.music.providers import import_cloud, search

    source = TrackSource.APPLE if args.source == "apple" else TrackSource.SPOTIFY
    if args.dry_run:
        hits = await search(source, args.query, args.limit)
        table = Table(title=f"Resultados en {source.value} para «{args.query}»")
        table.add_column("Título")
        table.add_column("Artista")
        table.add_column("Álbum")
        table.add_column("Duración", justify="right")
        for hit in hits:
            table.add_row(
                hit.title,
                hit.artist or "-",
                hit.album or "-",
                f"{hit.duration_s:.0f}s" if hit.duration_s else "-",
            )
        console.print(table)
        console.print(f"ℹ️  Dry run: {len(hits)} resultado(s). Usa sin --dry-run para importar.")
        return

    summary = await import_cloud(args.query, source, args.limit, library.db)
    console.print(
        f"[green]Importación desde {source.value}:[/] +{summary['added']} nuevas, "
        f"{summary['skipped']} ya existentes ({summary['total']} encontradas)"
    )
    if summary["added"]:
        console.print("💡 Revisa el dashboard (catalog-stats) o 'youber-music list' para verlas.")


async def _run_import_apple_library(args: argparse.Namespace, library: MusicLibrary) -> None:
    """Ejecuta ``import-apple-library``: importa el XML de la biblioteca."""
    from pathlib import Path

    from youber.music.apple_library import import_apple_library, parse_apple_library

    xml_path = Path(args.xml)
    if not xml_path.exists():
        console.print(f"[red]Fichero no encontrado: {args.xml}[/]")
        console.print("ℹ️  En Apple Music: Archivo → Biblioteca → Exportar biblioteca…")
        raise SystemExit(1)

    if args.dry_run:
        hits = parse_apple_library(xml_path)
        console.print(f"ℹ️  El XML contiene {len(hits)} canciones.")
        console.print("ℹ️  Usa sin --dry-run para importarlas al catálogo.")
        return

    summary = await import_apple_library(xml_path, library.db)
    console.print(
        f"[green]Biblioteca de Apple importada:[/] +{summary['added']} nuevas, "
        f"{summary['skipped']} ya existentes ({summary['total']} canciones en el XML)"
    )
    if summary["added"]:
        console.print("💡 Mira el dashboard (catalog-stats) o 'youber-music list' para verlas.")


async def _run_import_ytmusic_library(args: argparse.Namespace, library: MusicLibrary) -> None:
    """Ejecuta ``import-ytmusic-library``: importa la biblioteca personal."""
    from youber.music.youtube_music import (
        YouTubeMusicClient,
        import_ytmusic_library,
    )

    client = YouTubeMusicClient()
    if not client.authenticated:
        console.print("[red]YouTube Music sin autenticar.[/]")
        console.print(
            "ℹ️  Genera ~/.youber/ytmusic_headers.json (instrucciones en docs/MUSIC.md): "
            "python -c \"from ytmusicapi import setup; setup('headers.json')\" "
            "y muévelo a ~/.youber/"
        )
        raise SystemExit(1)

    summary = await import_ytmusic_library(
        client=client,
        db=library.db,
        include_playlists=not args.no_playlists,
    )
    console.print(
        f"[green]Biblioteca de YouTube Music importada:[/] +{summary['added']} nuevas, "
        f"{summary['skipped']} ya existentes "
        f"(fuentes: {', '.join(summary['sources'])})"
    )
    if summary["added"]:
        console.print("💡 Mira el dashboard (catalog-stats) o 'youber-music list' para verlas.")


async def _run_import_channel(args: argparse.Namespace, library: MusicLibrary) -> None:
    """Ejecuta ``import-channel``: importa el catálogo público del artista."""
    from youber.music.youtube_music import import_channel

    summary = await import_channel(
        args.handle,
        db=library.db,
        include_albums=not args.no_albums,
        include_singles=not args.no_singles,
    )
    console.print(
        f"[green]Catálogo de {summary['artist']} importado:[/] +{summary['added']} nuevas, "
        f"{summary['skipped']} ya existentes "
        f"(fuentes: {', '.join(summary['sources'])})"
    )
    if summary["added"]:
        console.print("💡 Mira el dashboard (catalog-stats o pestaña Canciones) para verlas.")


async def _run_enrich_genres(library: MusicLibrary) -> None:
    """Ejecuta ``enrich-genres``: asigna género automático desde iTunes."""
    from youber.music.providers import enrich_genres

    with console.status("Buscando géneros en iTunes…") as status:
        summary = await enrich_genres(library.db, progress=lambda title: status.update(f"Buscando géneros en iTunes… {title}"))
    console.print(
        f"[green]Géneros asignados:[/] {summary['updated']} actualizadas, "
        f"{summary['not_found']} sin encontrar, {summary['errors']} errores "
        f"({summary['total']} pendientes)"
    )
    console.print("💡 Ejecuta ahora 'youber-music analyze --all' para recalcular las propiedades de audio.")


def main() -> None:
    """Entry point de ``youber-music``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    run(args)


if __name__ == "__main__":
    main()
