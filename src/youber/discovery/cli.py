"""CLI ``youber-discovery``: buscador inteligente de canales (uso educativo).

Comandos: ``categories``, ``search``, ``similar`` y ``cache``.

Ejemplos:

.. code-block:: bash

    youber-discovery categories
    youber-discovery categories --category tecnología
    youber-discovery search python --category tecnología --limit 10
    youber-discovery search python --api --rank subscribers -o canales.json
    youber-discovery search python --demo -o canales.csv
    youber-discovery similar @canal --query python --demo
    youber-discovery cache stats
    youber-discovery cache clear
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.discovery.cache import DiscoveryCache
from youber.discovery.categories import (
    ChannelCategory,
    all_categories,
    topics_for,
)
from youber.discovery.ranking import RankingMetric, rank_channels, summarize
from youber.discovery.search import ChannelHit, ChannelSearcher, SearchResult
from youber.discovery.similarity import find_similar

console = Console()


def _category(value: str) -> ChannelCategory:
    """Convierte el texto del usuario en un :class:`ChannelCategory`."""
    lowered = value.strip().lower()
    for category in all_categories():
        if lowered in (category.value, category.name.lower()):
            return category
    raise argparse.ArgumentTypeError(
        f"Categoría desconocida: {value!r}. "
        f"Válidas: {', '.join(c.value for c in all_categories())}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-discovery``."""
    parser = argparse.ArgumentParser(
        prog="youber-discovery",
        description=(
            "BARF: buscador inteligente de canales de YouTube "
            "(uso educativo, datos públicos)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- categories --------------------------------------------------------
    categories = sub.add_parser("categories", help="Lista categorías y temas")
    categories.add_argument(
        "--category", type=_category, help="Muestra solo los temas de una categoría"
    )

    # -- search ------------------------------------------------------------
    search = sub.add_parser("search", help="Busca canales por texto/categoría/temas")
    search.add_argument("query", nargs="?", help="Texto de búsqueda (opcional con --category)")
    search.add_argument("--category", type=_category, help="Categoría predefinida")
    search.add_argument("--topics", help="Temas separados por comas")
    search.add_argument("--limit", type=int, default=10, help="Máximo de canales (10)")
    backend = search.add_mutually_exclusive_group()
    backend.add_argument(
        "--api", action="store_true", help="Forzar YouTube Data API v3 (YOUTUBE_API_KEY)"
    )
    backend.add_argument(
        "--html", action="store_true", help="Forzar el parser de la página pública"
    )
    backend.add_argument(
        "--demo", action="store_true", help="Canales sintéticos (sin red, para probar)"
    )
    search.add_argument(
        "--rank",
        type=RankingMetric,
        choices=list(RankingMetric),
        default=RankingMetric.ENGAGEMENT,
        help="Métrica de ordenación (engagement por defecto)",
    )
    search.add_argument("--min-subs", type=int, help="Filtra canales con menos suscriptores")
    search.add_argument("-o", "--output", help="Fichero de salida (JSON, CSV o Markdown)")
    search.add_argument(
        "-f",
        "--format",
        choices=["json", "csv", "md"],
        help="Formato de salida (por defecto se deduce de la extensión)",
    )
    search.add_argument("--no-cache", action="store_true", help="Ignora la caché")

    # -- similar -----------------------------------------------------------
    similar = sub.add_parser(
        "similar", help="Canales similares a uno dado dentro de un pool"
    )
    similar.add_argument("target", help="ID o URL del canal de referencia")
    similar.add_argument("--query", help="Búsqueda del pool de candidatos")
    similar.add_argument("--category", type=_category, help="Categoría del pool")
    similar.add_argument("--limit", type=int, default=5, help="Máximo de similares (5)")
    similar.add_argument("--min-score", type=float, default=0.0, help="Umbral de similitud")
    similar_backend = similar.add_mutually_exclusive_group()
    similar_backend.add_argument("--api", action="store_true")
    similar_backend.add_argument("--html", action="store_true")
    similar_backend.add_argument("--demo", action="store_true")

    # -- cache -------------------------------------------------------------
    cache = sub.add_parser("cache", help="Gestiona la caché de resultados")
    cache.add_argument("action", choices=["stats", "clear"], help="Acción a ejecutar")

    return parser


def _resolve_mode(api: bool, html: bool, demo: bool) -> str:
    if api:
        return "api"
    if html:
        return "html"
    if demo:
        return "demo"
    return "auto"


def main() -> None:
    """Punto de entrada del comando ``youber-discovery``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    if args.command == "categories":
        _cmd_categories(args)
    elif args.command == "search":
        asyncio.run(_cmd_search(args))
    elif args.command == "similar":
        asyncio.run(_cmd_similar(args))
    elif args.command == "cache":
        _cmd_cache(args)


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def _cmd_categories(args: argparse.Namespace) -> None:
    """Muestra las categorías y sus temas."""
    categories = [args.category] if args.category else all_categories()
    table = Table(title="Categorías de canales")
    table.add_column("Categoría", style="cyan")
    table.add_column("Temas", style="white")
    for category in categories:
        table.add_row(category.value, ", ".join(topics_for(category)))
    console.print(table)


async def _cmd_search(args: argparse.Namespace) -> None:
    """Busca canales y muestra/exporta el ranking."""
    topics = [t.strip() for t in args.topics.split(",")] if args.topics else None
    if not args.query and args.category is None and not topics:
        raise SystemExit("Indica un texto de búsqueda, --category o --topics")
    if args.min_subs is not None and args.min_subs < 0:
        raise SystemExit("--min-subs debe ser ≥ 0")

    searcher = ChannelSearcher(api_key=os.getenv("YOUTUBE_API_KEY"))
    cache = None if args.no_cache else DiscoveryCache()

    result = await _search_cached(searcher, cache, args)
    channels = [
        ch for ch in result.channels if (args.min_subs is None or (ch.subscriber_count or 0) >= args.min_subs)
    ]
    ranked = rank_channels(channels, metric=args.rank)

    if args.output:
        _export(ranked, args.output, args.format)
        console.print(f"[green]✓[/green] Exportado {len(ranked)} canales a {args.output}")
    else:
        _print_results(result, ranked)


async def _search_cached(
    searcher: ChannelSearcher,
    cache: DiscoveryCache | None,
    args: argparse.Namespace,
) -> SearchResult:
    """Ejecuta la búsqueda usando la caché si está disponible."""
    topics = [t.strip() for t in args.topics.split(",")] if args.topics else None
    key = f"search:{args.query or ''}:{args.category}:{topics}:{args.limit}"
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            console.print("[dim]Resultado de caché[/dim]")
            return SearchResult.model_validate(cached)
    result = await searcher.search(
        query=args.query,
        category=args.category,
        topics=topics,
        limit=args.limit,
        mode=_resolve_mode(args.api, args.html, args.demo),
    )
    if cache is not None:
        cache.set(key, result.model_dump(mode="json"))
    return result


async def _cmd_similar(args: argparse.Namespace) -> None:
    """Busca un pool y muestra los canales más parecidos al objetivo."""
    searcher = ChannelSearcher(api_key=os.getenv("YOUTUBE_API_KEY"))
    if not args.query and args.category is None and not args.demo:
        raise SystemExit("Indica --query, --category o --demo para construir el pool")

    result = await searcher.search(
        query=args.query,
        category=args.category,
        limit=20,
        mode=_resolve_mode(args.api, args.html, args.demo),
    )
    target = _find_target(args.target, result.channels, result)
    if target is None:
        raise SystemExit(
            f"No se encontró {args.target!r} en el pool. "
            "Pásale la URL/ID de uno de los canales del pool."
        )

    similar = find_similar(target, result.channels, limit=args.limit, min_score=args.min_score)
    table = Table(title=f"Canales similares a «{target.title}»")
    table.add_column("#", style="dim")
    table.add_column("Canal", style="cyan")
    table.add_column("Similitud", style="green")
    table.add_column("Temas compartidos", style="white")
    table.add_column("Suscriptores", style="magenta")
    for item in similar:
        table.add_row(
            str(item.rank),
            item.channel.title,
            f"{item.score:.2f}",
            ", ".join(item.shared_topics) or "—",
            _format_count(item.channel.subscriber_count),
        )
    console.print(table)


def _find_target(
    target: str,
    channels: list[ChannelHit],
    result: SearchResult,
) -> ChannelHit | None:
    """Localiza el canal de referencia en el pool (por ID, URL o handle)."""
    stripped = target.strip().lower()
    for channel in channels:
        candidates = [
            channel.channel_id,
            channel.url,
            channel.handle or "",
            channel.title,
        ]
        if any(stripped in str(candidate).lower() for candidate in candidates):
            return channel
    return None


def _cmd_cache(args: argparse.Namespace) -> None:
    """Muestra estadísticas o vacía la caché."""
    cache = DiscoveryCache()
    if args.action == "stats":
        stats = cache.stats()
        console.print(
            f"Entradas: [cyan]{stats['entradas']}[/cyan] "
            f"· Válidas: [green]{stats['validas']}[/green] "
            f"· Expiradas: [yellow]{stats['expiradas']}[/yellow] "
            f"· Tamaño: [magenta]{stats['bytes']} bytes[/magenta]"
        )
    elif args.action == "clear":
        cache.clear()
        console.print("[green]✓[/green] Caché vaciada")


# ---------------------------------------------------------------------------
# Presentación y exportación
# ---------------------------------------------------------------------------


def _print_results(result: SearchResult, ranked: list[Any]) -> None:
    """Muestra la tabla del ranking en consola."""
    summary = summarize([item.channel for item in ranked])
    table = Table(
        title=(
            f"Canales para «{result.query}» "
            f"({result.backend}, {len(ranked)} resultados)"
        )
    )
    table.add_column("#", style="dim")
    table.add_column("Canal", style="cyan")
    table.add_column("Categoría", style="blue")
    table.add_column("Suscriptores", style="magenta")
    table.add_column("Vídeos", style="white")
    table.add_column("Vistas", style="white")
    table.add_column("Score", style="green")
    for item in ranked:
        channel = item.channel
        table.add_row(
            str(item.rank),
            channel.title,
            channel.category.value if channel.category else "—",
            _format_count(channel.subscriber_count),
            _format_count(channel.video_count),
            _format_count(channel.view_count),
            f"{item.score:.2f}",
        )
    console.print(table)
    console.print(
        "[dim]Media: "
        f"{summary['suscriptores_medio']:.0f} suscriptores · "
        f"{summary['vistas_medio']:.0f} vistas · "
        f"{summary['con_categoria']}/{summary['canales']} con categoría[/dim]"
    )


def _export(ranked: list[Any], output: str, fmt: str | None) -> None:
    """Exporta el ranking a JSON, CSV o Markdown según la extensión."""
    extension = fmt or Path(output).suffix.lstrip(".").lower()
    if extension == "json":
        _export_json(ranked, output)
    elif extension == "csv":
        _export_csv(ranked, output)
    elif extension in ("md", "markdown"):
        _export_markdown(ranked, output)
    else:
        raise SystemExit(
            f"Formato no soportado: {extension!r}. Usa .json, .csv o .md"
        )


def _export_json(ranked: list[Any], output: str) -> None:
    payload = [
        {
            "rank": item.rank,
            "metric": item.metric.value,
            "score": item.score,
            "channel": item.channel.model_dump(mode="json"),
        }
        for item in ranked
    ]
    Path(output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _export_csv(ranked: list[Any], output: str) -> None:
    path = Path(output)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["rank", "canal", "categoria", "suscriptores", "videos", "vistas", "score"]
        )
        for item in ranked:
            channel = item.channel
            writer.writerow(
                [
                    item.rank,
                    channel.title,
                    channel.category.value if channel.category else "",
                    channel.subscriber_count or 0,
                    channel.video_count or 0,
                    channel.view_count or 0,
                    f"{item.score:.4f}",
                ]
            )


def _export_markdown(ranked: list[Any], output: str) -> None:
    lines = [
        "# Canales descubiertos",
        "",
        "| # | Canal | Categoría | Suscriptores | Vídeos | Vistas | Score |",
        "|---|-------|-----------|--------------|--------|--------|-------|",
    ]
    for item in ranked:
        channel = item.channel
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {:.2f} |".format(
                item.rank,
                channel.title,
                channel.category.value if channel.category else "—",
                _format_count(channel.subscriber_count),
                _format_count(channel.video_count),
                _format_count(channel.view_count),
                item.score,
            )
        )
    Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_count(value: int | None) -> str:
    """Formatea un número grande de forma compacta (1234567 → 1,2 M)."""
    if not value:
        return "—"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} M"
    if value >= 1_000:
        return f"{value / 1_000:.1f} K"
    return str(value)
