"""CLI de análisis musical: subcomando ``analyze`` de ``youber-music``.

Añade al comando existente ``youber-music`` la capacidad de analizar las
características de audio del catálogo local (vía Spotify API o estimador
local) y mostrar perfiles y recomendaciones.

Ejemplos:

.. code-block:: bash

    youber-music analyze <id>
    youber-music analyze --all
    youber-music analyze <id> --local
    youber-music recommend <id> -n 5
"""

from __future__ import annotations

import argparse
import asyncio

from rich.console import Console
from rich.table import Table

from youber.music.audio_features.analyzer import AudioAnalyzer
from youber.music.audio_features.enricher import AudioFeatureStore, CatalogEnricher
from youber.music.audio_features.models import AudioProfile
from youber.music.audio_features.recommender import FeatureRecommender
from youber.music.audio_features.spotify import SpotifyClient
from youber.music.library import MusicLibrary

console = Console()


def register(sub: argparse._SubParsersAction) -> None:
    """Registra los subcomandos de análisis musical en ``youber-music``."""
    analyze = sub.add_parser("analyze", help="Analiza las características de audio")
    analyze.add_argument("track_id", nargs="?", help="Id de la pista (o --all)")
    analyze.add_argument("--all", action="store_true", help="Analiza todo el catálogo")
    analyze.add_argument(
        "--local",
        action="store_true",
        help="Fuerza la estimación local (ignora Spotify)",
    )
    analyze.add_argument("--refresh", action="store_true", help="Reanaliza aunque ya exista")

    recommend = sub.add_parser(
        "recommend", help="Recomienda pistas similares por características de audio"
    )
    recommend.add_argument("track_id", help="Id de la pista de referencia")
    recommend.add_argument("-n", "--limit", type=int, default=5, help="Número de sugerencias")


def run(args: argparse.Namespace, library: MusicLibrary) -> None:
    """Despacha los subcomandos de análisis musical."""
    if args.command == "analyze":
        asyncio.run(_cmd_analyze(args, library))
    elif args.command == "recommend":
        asyncio.run(_cmd_recommend(args, library))


async def _cmd_analyze(args: argparse.Namespace, library: MusicLibrary) -> None:
    """Analiza una pista (o todo el catálogo) y muestra su perfil."""
    analyzer = AudioAnalyzer()
    if args.local:
        # Sin credenciales -> available=False -> el analyzer cae al estimador local.
        analyzer.spotify = SpotifyClient(client_id="", client_secret="")
    enricher = CatalogEnricher(library=library, analyzer=analyzer)

    if args.all:
        result = await enricher.enrich_all()
        console.print(
            f"[green]✓[/green] Analizadas {result.enriched}/{result.total} pistas "
            f"({len(result.errors)} errores)"
        )
        _print_profiles(enricher.store.all())
        return

    if not args.track_id:
        raise SystemExit("Indica un id de pista o usa --all")

    track = library.get(args.track_id)
    if track is None:
        console.print(f"[red]Pista no encontrada: {args.track_id}[/]")
        raise SystemExit(1)

    if enricher.store.has(track.id) and not args.refresh:
        profile = enricher.store.get(track.id)
        assert profile is not None
        _print_profile(profile)
        return

    profile = await enricher.enrich(track)
    if profile is None:
        console.print(f"[red]No se pudo analizar: {track.title}[/]")
        raise SystemExit(1)
    _print_profile(profile)


async def _cmd_recommend(args: argparse.Namespace, library: MusicLibrary) -> None:
    """Recomienda pistas similares a una del catálogo."""
    store = AudioFeatureStore()
    target = store.get(args.track_id)
    if target is None:
        console.print(
            f"[red]No hay perfil de audio para {args.track_id}. "
            "Ejecuta antes: youber-music analyze <id>[/]"
        )
        raise SystemExit(1)
    recommender = FeatureRecommender()
    recommendations = recommender.recommend(target, store.all(), limit=args.limit)
    _print_recommendations(recommendations)


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------


def _print_profile(profile: AudioProfile) -> None:
    """Muestra el perfil de audio de una pista."""
    features = profile.features
    source = "API Spotify" if features.confidence >= 1.0 else "Estimación local"
    console.print(f"[bold]{profile.track_title}[/] — {profile.artist}")
    console.print(
        f"  Energía: {features.energy:.2f} ({profile.energy_level}) · "
        f"Bailabilidad: {features.danceability:.2f} ({profile.dance_bucket})"
    )
    console.print(
        f"  Valencia: {features.valence:.2f} ({profile.valence_bucket}) · "
        f"Tempo: {features.tempo:.0f} BPM ({profile.tempo_bucket})"
    )
    console.print(
        f"  Acústica: {features.acousticness:.2f} · Instrumental: "
        f"{features.instrumentalness:.2f} · Duración: {features.duration_ms / 1000:.0f}s"
    )
    console.print(
        f"  Moods: {', '.join(profile.moods) or '-'} · "
        f"Tags: {', '.join(profile.recommendation_tags) or '-'}"
    )
    console.print(
        f"  [dim]Fuente: {source} · Confianza: {features.confidence:.2f}[/]"
    )


def _print_profiles(profiles: list[AudioProfile]) -> None:
    """Muestra una tabla con los perfiles almacenados."""
    if not profiles:
        console.print("[dim]Sin perfiles de audio en el catálogo.[/]")
        return
    table = Table(title=f"{len(profiles)} perfil(es) de audio")
    table.add_column("Id", style="dim")
    table.add_column("Título")
    table.add_column("Energía", justify="right")
    table.add_column("Dance", justify="right")
    table.add_column("Valencia", justify="right")
    table.add_column("Tempo", justify="right")
    table.add_column("Fuente", style="cyan")
    for profile in profiles:
        features = profile.features
        table.add_row(
            profile.track_id,
            profile.track_title,
            f"{features.energy:.2f}",
            f"{features.danceability:.2f}",
            f"{features.valence:.2f}",
            f"{features.tempo:.0f}",
            "api" if features.confidence >= 1.0 else "local",
        )
    console.print(table)


def _print_recommendations(recommendations: list) -> None:
    """Muestra las recomendaciones por similitud."""
    if not recommendations:
        console.print("[dim]No hay recomendaciones para esta pista.[/]")
        return
    table = Table(title=f"{len(recommendations)} recomendación(es)")
    table.add_column("#", style="dim")
    table.add_column("Título")
    table.add_column("Artista")
    table.add_column("Similitud", justify="right")
    table.add_column("Moods compartidos")
    for item in recommendations:
        table.add_row(
            str(item.rank),
            item.track_title,
            item.artist,
            f"{item.score:.2f}",
            ", ".join(item.shared_moods) or "—",
        )
    console.print(table)
