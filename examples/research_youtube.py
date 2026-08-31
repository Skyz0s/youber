"""Investigación de YouTube con BARF — ejemplo educativo.

Analiza un canal o vídeo de YouTube (datos **públicos**) y guarda el
resultado en JSON, CSV o Markdown, con insights opcionales de patrones.

Uso:
    python examples/research_youtube.py <URL> [-n 10] [-o salida] [--insights] [--api]

Ejemplos:
    python examples/research_youtube.py https://www.youtube.com/@python -n 20 -o reports/python.csv
    python examples/research_youtube.py https://youtu.be/dQw4w9WgXcQ -o reports/video.json
    python examples/research_youtube.py https://www.youtube.com/@python --insights -o reports/python.md
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from youber.cli.research_cli import detect_target, infer_format
from youber.console import ensure_utf8_console
from youber.research.channel_analyzer import ChannelAnalyzer
from youber.research.exporters import export_channel, export_videos
from youber.research.patterns import channel_overview, parse_compact_count
from youber.research.video_analyzer import VideoAnalyzer

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def _print_channel(channel) -> None:
    print(f"📺 Canal: {channel.name}")
    print(f"   Handle: @{channel.handle or '-'} | Suscriptores: {channel.subscribers or '-'}")
    print(f"   Vídeos recogidos: {len(channel.videos)}")
    for video in channel.videos[:10]:
        print(f"   • {video.title} — {video.views} ({video.duration or '?'})")


def _print_video(video) -> None:
    print(f"▶️ Vídeo: {video.title}")
    print(
        f"   Vistas: {video.views} | Likes: {video.likes or '-'} | "
        f"Comentarios: {video.comments or '-'}"
    )
    print(f"   Duración: {video.duration or '-'} | Publicado: {video.publish_date or '-'}")
    if video.hashtags:
        print(f"   Hashtags: {' '.join('#' + tag for tag in video.hashtags)}")


def _print_insights(overview: dict) -> None:
    print("\n📊 Insights:")
    top = overview["top_hashtags"][:5]
    if top:
        print("   Hashtags más usados:")
        for entry in top:
            print(f"     #{entry['hashtag']} — {entry['count']} vídeo(s)")
    patterns = overview["title_patterns"]
    print(
        "   Títulos: "
        f"{patterns['with_numbers']} con números, {patterns['with_uppercase_words']} en MAYÚSCULAS, "
        f"{patterns['with_question']} con pregunta"
    )
    duration = overview["duration_stats"]
    if duration["count"]:
        print(
            f"   Duración media: {duration['avg_seconds']} s "
            f"(min {duration['min_seconds']}, máx {duration['max_seconds']})"
        )
    views = overview["views_summary"]
    if views["avg"]:
        print(f"   Vistas medias: {views['avg']:,.0f} | máx: {views['max']:,.0f}")


def _print_video_insights(video) -> None:
    print("\n📊 Insights:")
    if video.hashtags:
        print(f"   Hashtags: {' '.join('#' + tag for tag in video.hashtags)}")
    count = parse_compact_count(video.views)
    if count:
        print(f"   Vistas: {count:,.0f}")


async def run(url: str, max_videos: int, output: str | None, mode: str, insights: bool) -> None:
    """Analiza el canal/vídeo, imprime el resumen y guarda la salida si procede."""
    if detect_target(url) == "video":
        video = await VideoAnalyzer().analyze(url, mode=mode)
        _print_video(video)
        if insights:
            _print_video_insights(video)
        if output:
            fmt = infer_format(output, None) or "json"
            export_videos([video], output, fmt=fmt)
            print(f"📄 Guardado: {output}")
    else:
        channel = await ChannelAnalyzer().analyze(url, max_videos=max_videos, mode=mode)
        _print_channel(channel)
        if insights:
            overview = channel_overview(channel)
            _print_insights(overview)
        if output:
            fmt = infer_format(output, None) or "json"
            export_channel(channel, output, fmt=fmt)
            print(f"📄 Guardado: {output}")


def main() -> None:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(
        description="Investigación de YouTube (ejemplo BARF): datos públicos de canales y vídeos"
    )
    parser.add_argument("url", help="URL del canal o vídeo de YouTube")
    parser.add_argument("-n", "--max-videos", type=int, default=10, help="Vídeos a extraer")
    parser.add_argument("-o", "--output", default=None, help="Fichero de salida (json/csv/md)")
    parser.add_argument(
        "--api",
        action="store_true",
        help="Usar la YouTube Data API v3 (requiere YOUTUBE_API_KEY)",
    )
    parser.add_argument("--insights", action="store_true", help="Mostrar insights de patrones")
    args = parser.parse_args()

    mode = "api" if args.api else "html"
    if args.output:
        reports_dir = REPORTS_DIR if Path(args.output).parent == Path(".") else Path(args.output).parent
        reports_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(run(args.url, args.max_videos, args.output, mode, args.insights))


if __name__ == "__main__":
    main()
