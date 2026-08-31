"""CLI ``youber-research``: extrae y analiza datos públicos de YouTube.

Uso educativo: solo datos públicos, con rate-limit (modo ``--html``) o vía
la YouTube Data API v3 (modo ``--api``, conforme a ToS).

Ejemplos:

.. code-block:: bash

    youber-research https://www.youtube.com/@python -n 20 -o python_channel.csv
    youber-research https://youtu.be/abc123 -o video_info.json
    youber-research https://www.youtube.com/@python --insights -o reporte.md
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from youber.console import ensure_utf8_console
from youber.research.channel_analyzer import ChannelAnalyzer
from youber.research.data_models import ChannelData, VideoData
from youber.research.exporters import (
    export_channel,
    export_videos,
    generate_channel_markdown,
)
from youber.research.patterns import (
    channel_overview,
    parse_compact_count,
    parse_duration_to_seconds,
)
from youber.research.video_analyzer import VideoAnalyzer, extract_video_id

DEFAULT_MAX_VIDEOS = 10
FORMAT_BY_EXTENSION = {"csv": "csv", "json": "json", "md": "md", "markdown": "md"}


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-research``."""
    parser = argparse.ArgumentParser(
        prog="youber-research",
        description="BARF: extrae y analiza datos públicos de YouTube (uso educativo)",
    )
    parser.add_argument("url", help="URL del canal o vídeo de YouTube")
    parser.add_argument(
        "-n",
        "--max-videos",
        type=int,
        default=DEFAULT_MAX_VIDEOS,
        help=f"Vídeos a extraer en canales (por defecto: {DEFAULT_MAX_VIDEOS})",
    )
    parser.add_argument("-o", "--output", help="Fichero de salida (CSV, JSON o Markdown)")
    parser.add_argument(
        "-f",
        "--format",
        choices=["csv", "json", "md"],
        help="Formato de salida (por defecto se deduce de la extensión)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--api",
        action="store_true",
        help="Forzar la YouTube Data API v3 (requiere YOUTUBE_API_KEY)",
    )
    mode.add_argument(
        "--html",
        action="store_true",
        help="Forzar el parser de la página pública (por defecto)",
    )
    parser.add_argument(
        "--insights",
        action="store_true",
        help="Añadir insights de patrones (hashtags, títulos, duración)",
    )
    return parser


def detect_target(url: str) -> str:
    """Distingue si una URL apunta a un canal o a un vídeo."""
    return "video" if extract_video_id(url) else "channel"


def infer_format(output: str | None, fmt: str | None) -> str | None:
    """Resuelve el formato de salida: explícito o deducido de la extensión."""
    if fmt:
        return fmt.lower()
    if not output:
        return None
    suffix = Path(output).suffix.lower().lstrip(".")
    return FORMAT_BY_EXTENSION.get(suffix)


# ---------------------------------------------------------------------------
# Salida por consola
# ---------------------------------------------------------------------------


def _print_channel(channel: ChannelData) -> None:
    print(f"📺 Canal: {channel.name}")
    print(f"   Handle: @{channel.handle or '-'} | Suscriptores: {channel.subscribers or '-'}")
    print(f"   Vídeos recogidos: {len(channel.videos)}")
    for video in channel.videos[:10]:
        print(f"   • {video.title} — {video.views} ({video.duration or '?'})")


def _print_video(video: VideoData) -> None:
    print(f"▶️ Vídeo: {video.title}")
    print(f"   Vistas: {video.views} | Likes: {video.likes or '-'} | Comentarios: {video.comments or '-'}")
    print(f"   Duración: {video.duration or '-'} | Publicado: {video.publish_date or '-'}")
    print(f"   Canal: {video.channel_name} ({video.channel_url})")
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


def _print_video_insights(video: VideoData) -> None:
    print("\n📊 Insights:")
    if video.hashtags:
        print(f"   Hashtags: {' '.join('#' + tag for tag in video.hashtags)}")
    seconds = parse_duration_to_seconds(video.duration)
    if seconds:
        print(f"   Duración: {seconds} s")
    count = parse_compact_count(video.views)
    if count:
        print(f"   Vistas: {count:,.0f}")


# ---------------------------------------------------------------------------
# Guardado
# ---------------------------------------------------------------------------


def _insights_markdown(overview: dict) -> str:
    lines = ["", "## Insights", ""]
    top = overview["top_hashtags"][:5]
    if top:
        lines.append("**Hashtags más usados:**")
        for entry in top:
            lines.append(f"- `#{entry['hashtag']}` — {entry['count']} vídeo(s)")
        lines.append("")
    patterns = overview["title_patterns"]
    lines.append(
        f"**Patrones de títulos:** {patterns['with_numbers']} con números, "
        f"{patterns['with_uppercase_words']} en MAYÚSCULAS, "
        f"{patterns['with_question']} con pregunta, {patterns['with_vs']} con 'vs'"
    )
    duration = overview["duration_stats"]
    if duration["count"]:
        lines.append(
            f"**Duración media:** {duration['avg_seconds']} s "
            f"(mín {duration['min_seconds']}, máx {duration['max_seconds']})"
        )
    views = overview["views_summary"]
    if views["avg"]:
        lines.append(f"**Vistas:** media {views['avg']:,.0f}, máx {views['max']:,.0f}")
    return "\n".join(lines) + "\n"


def _video_markdown(video: VideoData, insights: bool = False) -> str:
    lines = [
        f"# Vídeo — {video.title}",
        "",
        f"- **URL:** {video.url}",
        f"- **Vistas:** {video.views}",
        f"- **Likes:** {video.likes or '-'}",
        f"- **Comentarios:** {video.comments or '-'}",
        f"- **Duración:** {video.duration or '-'}",
        f"- **Publicado:** {video.publish_date or '-'}",
        f"- **Canal:** {video.channel_name} — {video.channel_url}",
    ]
    if video.hashtags:
        lines += ["", "**Hashtags:** " + " ".join(f"#{tag}" for tag in video.hashtags)]
    if video.description:
        lines += ["", "## Descripción", "", video.description]
    if insights:
        lines += ["", "## Insights", ""]
        if video.hashtags:
            lines.append("**Hashtags:** " + " ".join(f"#{tag}" for tag in video.hashtags))
        seconds = parse_duration_to_seconds(video.duration)
        if seconds:
            lines.append(f"**Duración:** {seconds} s")
        count = parse_compact_count(video.views)
        if count:
            lines.append(f"**Vistas:** {count:,.0f}")
    return "\n".join(lines) + "\n"


def _save_channel(
    channel: ChannelData,
    insights: dict | None,
    args: argparse.Namespace,
) -> None:
    if not args.output:
        return
    fmt = infer_format(args.output, args.format)
    if fmt is None:
        raise SystemExit(
            f"No se pudo deducir el formato de '{args.output}'; usa -f csv|json|md"
        )
    out = Path(args.output)
    if fmt == "md":
        text = generate_channel_markdown(channel)
        if insights:
            text += _insights_markdown(insights)
        out.write_text(text, encoding="utf-8")
    else:
        export_channel(channel, out, fmt=fmt)
    print(f"📄 Guardado: {out}")


def _save_video(video: VideoData, args: argparse.Namespace) -> None:
    if not args.output:
        return
    fmt = infer_format(args.output, args.format)
    if fmt is None:
        raise SystemExit(
            f"No se pudo deducir el formato de '{args.output}'; usa -f csv|json|md"
        )
    out = Path(args.output)
    if fmt == "md":
        out.write_text(_video_markdown(video, insights=args.insights), encoding="utf-8")
    else:
        export_videos([video], out, fmt=fmt)
    print(f"📄 Guardado: {out}")


# ---------------------------------------------------------------------------
# Flujo principal
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> None:
    mode = "api" if args.api else "html"
    api_key = os.getenv("YOUTUBE_API_KEY") if mode == "api" else None
    if mode == "api" and not api_key:
        raise SystemExit("El modo --api requiere YOUTUBE_API_KEY en el entorno")

    if detect_target(args.url) == "video":
        video = await VideoAnalyzer(api_key=api_key).analyze(args.url, mode=mode)
        _print_video(video)
        if args.insights:
            _print_video_insights(video)
        _save_video(video, args)
    else:
        channel = await ChannelAnalyzer(api_key=api_key).analyze(
            args.url, max_videos=args.max_videos, mode=mode
        )
        _print_channel(channel)
        insights = channel_overview(channel) if args.insights else None
        if insights:
            _print_insights(insights)
        _save_channel(channel, insights, args)


def main() -> None:
    """Entry point de ``youber-research``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
