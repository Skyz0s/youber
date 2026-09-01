"""CLI ``youber-script``: genera un guion desde los insights de un canal
y construye/edita tu propio vídeo con esa estructura + música local.

Ejemplos:

.. code-block:: bash

    youber-script --channel https://www.youtube.com/@MrBeast -n 10 \\
        --topic "Mi reto de 30 días" --clips intro.mp4 main.mp4 --library music
    youber-script --demo --topic "Demo" --clips a.mp4 b.mp4   # sin red
    youber-script --json guion.json                           # solo guion
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.music.library import MusicLibrary
from youber.research.channel_analyzer import ChannelAnalyzer
from youber.research.patterns import channel_overview
from youber.script.builder import build_project, default_font_file
from youber.script.generator import generate_script
from youber.script.models import Script
from youber.video.editor import VideoEditor

console = Console()


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de ``youber-script``."""
    parser = argparse.ArgumentParser(
        prog="youber-script",
        description="BARF: genera un guion desde la estructura de un canal de "
        "YouTube y edita tu propio vídeo con esa estructura + tu música",
    )
    parser.add_argument(
        "--channel",
        help="URL/handle del canal a analizar (p. ej. https://www.youtube.com/@MrBeast)",
    )
    parser.add_argument("-n", "--max-videos", type=int, default=10, help="Vídeos a extraer")
    parser.add_argument("--topic", default="Mi vídeo", help="Tema de tu vídeo")
    parser.add_argument(
        "--duration", type=float, default=None, help="Duración total en segundos"
    )
    parser.add_argument(
        "--clips", nargs="+", default=[], help="Tus ficheros de vídeo (se reparten por escena)"
    )
    parser.add_argument(
        "--library", default="music", help="Directorio del catálogo de música local"
    )
    parser.add_argument(
        "--json", dest="json_out", default=None, help="Guardar el guion como JSON"
    )
    parser.add_argument(
        "--render", default=None, help="Renderizar el vídeo final a esta ruta (.mp4)"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Canal sintético (sin red)"
    )
    return parser


def _print_script(script: Script) -> None:
    """Muestra el guion en consola."""
    console.print(
        Panel.fit(
            f"[bold cyan]🎬 Guion: {script.topic}[/]\n"
            f"   Canal de referencia: [bold]{script.source_channel or '-'}[/] · "
            f"Duración total: [bold]{script.total_duration:g} s[/] · "
            f"Música sugerida: [bold]{script.music_mood or '-'}[/]",
            border_style="cyan",
        )
    )
    table = Table(title="Escenas")
    table.add_column("Escena", style="cyan")
    table.add_column("Duración (s)", justify="right")
    table.add_column("Texto superpuesto")
    table.add_column("Transición")
    for scene in script.scenes:
        table.add_row(
            scene.type.value,
            f"{scene.duration:g}",
            scene.text,
            scene.transition.value,
        )
    console.print(table)
    if script.hashtags:
        console.print(
            "🏷️  Hashtags sugeridos: [bold]" + " ".join(f"#{h}" for h in script.hashtags) + "[/]"
        )


async def _run(args: argparse.Namespace) -> None:
    """Flujo principal."""
    analysis = None
    content_keywords: list[str] | None = None
    if args.demo:
        from youber.cli.workflow_cli import demo_channel

        channel = demo_channel()
        console.print(f"📺 Canal sintético: [bold]{channel.name}[/] (sin red)")
        insights = channel_overview(channel)
    else:
        if not args.channel:
            raise SystemExit("Indica --channel <url> o usa --demo")
        console.print(f"📡 Analizando: [bold]{args.channel}[/]")
        # Si la URL es un vídeo concreto, su contenido manda; si no, es canal.
        from youber.research.video_analyzer import VideoAnalyzer, extract_video_id

        video_id = extract_video_id(args.channel)
        if video_id:
            from youber.research.data_models import ChannelData
            from youber.script.transcripts import (
                analyze_video as analyze_video_transcript,
            )
            from youber.script.transcripts import (
                extract_keywords,
            )

            video = await VideoAnalyzer().analyze(args.channel, mode="auto")
            channel = ChannelData(
                name=video.channel_name,
                url=video.channel_url or args.channel,
                handle=None,
                subscribers=None,
                videos=[video],
            )
            insights = channel_overview(channel)
            if not args.topic or args.topic == "Mi vídeo":
                args.topic = video.title or args.topic
            console.print("🎙️  Extrayendo transcripción pública del vídeo origen...")
            analysis = analyze_video_transcript(video.video_id)
            content_keywords = extract_keywords(
                " ".join(filter(None, [video.title, video.description]))
            )
            if analysis and analysis.keywords:
                content_keywords = list(
                    dict.fromkeys(content_keywords + analysis.keywords)
                )[:8]
        else:
            channel = await ChannelAnalyzer().analyze(
                args.channel, max_videos=args.max_videos, mode="html"
            )
            insights = channel_overview(channel)
            duration_stats = insights.get("duration_stats", {})
            console.print(
                f"   Media: {duration_stats.get('avg_seconds')} s · "
                f"{len(channel.videos)} vídeos · "
                f"patrones: {insights.get('title_patterns', {}).get('with_numbers', 0)} con números"
            )
            # Transcripciones públicas del canal patrón (instrucciones reales).
            from youber.script.transcripts import analyze_channel

            console.print("🎙️  Extrayendo transcripciones públicas (estilo del canal)...")
            analysis = analyze_channel(channel.videos, max_videos=3)
            if analysis and analysis.video_count:
                hook = (analysis.hooks[0] if analysis.hooks else "-")[:60]
                console.print(f"   ✓ {analysis.video_count} transcripción(es) · hook: «{hook}»")
            else:
                console.print("   ℹ️  Sin transcripciones disponibles (plantillas genéricas)")
            if analysis and analysis.video_count and analysis.keywords:
                content_keywords = analysis.keywords

    script = generate_script(
        insights,
        topic=args.topic,
        duration=args.duration,
        transcripts=analysis if analysis and analysis.video_count else None,
        content_keywords=content_keywords,
    )
    _print_script(script)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(script.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"📄 Guion guardado: [green]{out}[/]")

    if args.render:
        if not args.clips:
            raise SystemExit("Para renderizar necesitas --clips <tus ficheros de vídeo>")
        library = MusicLibrary(args.library)
        editor = VideoEditor(library=library)
        project = build_project(
            script, clips=args.clips, library=library, editor=editor, title=args.topic
        )
        font = default_font_file()
        console.print(
            f"🎛️  Proyecto: {len(project.clips)} clips, "
            f"{len(project.text_overlays)} textos"
            + (f", música {project.music_track_id}" if project.music_track_id else ", sin música local")
            + (f", fuente {Path(font).name}" if font else "")
        )
        out_path = Path(args.render)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        console.print(f"🎬 Renderizando → [bold]{out_path}[/] (puede tardar)...")
        await editor.render(project, out_path)
        console.print(f"✅ Vídeo final: [bold green]{out_path}[/]")


def main() -> None:
    """Entry point de ``youber-script``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    try:
        asyncio.run(_run(args))
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
