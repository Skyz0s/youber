"""CLI del flujo completo de BARF: investigación de YouTube + edición de audio.

Ejecuta el pipeline de principio a fin, mostrando cada paso con ``rich``:

1. Investiga un canal público de YouTube (datos y vídeos recientes).
2. Extrae datos de los últimos vídeos (título, vistas, duración).
3. Genera insights de patrones de éxito (hashtags, títulos, duración).
4. Prepara un vídeo de ejemplo (local o generado con FFmpeg).
5. Añade música de fondo (local o generada con FFmpeg).
6. Exporta el resultado final (JSON/CSV/Markdown + vídeo MP4).

Uso:

.. code-block:: bash

    youber-workflow --channel @python -n 10 -o reports
    youber-workflow --demo -o reports            # sin red (canal sintético)
    youber-workflow --video mi_video.mp4 --music mi_musica.mp3 -o reports

Nota ética: usa solo **tu propia música** o contenido con licencia, y solo
vídeos propios o con permiso. El modo ``--demo`` genera vídeo y música
sintéticos con FFmpeg (sin dependencias externas ni derechos de autor).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from youber.audio._ffmpeg import run_command
from youber.audio.editor import add_background_music
from youber.console import ensure_utf8_console
from youber.research.channel_analyzer import ChannelAnalyzer
from youber.research.data_models import ChannelData, VideoData
from youber.research.exporters import (
    export_channel,
    export_videos,
    generate_channel_markdown,
)
from youber.research.patterns import channel_overview

console = Console()

DEFAULT_CHANNEL = "@python"
DEFAULT_DURATION = 30


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-workflow``."""
    parser = argparse.ArgumentParser(
        prog="youber-workflow",
        description="BARF: flujo completo de investigación de YouTube + edición de audio",
    )
    parser.add_argument(
        "--channel",
        default=DEFAULT_CHANNEL,
        help=f"Canal a investigar (por defecto: {DEFAULT_CHANNEL})",
    )
    parser.add_argument(
        "-n", "--max-videos", type=int, default=10, help="Vídeos a extraer"
    )
    parser.add_argument(
        "-o", "--output-dir", default="reports", help="Directorio de salida"
    )
    parser.add_argument("--video", default=None, help="Vídeo local (si no, se genera uno)")
    parser.add_argument("--music", default=None, help="Música local (si no, se genera una)")
    parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION,
        help=f"Duración del vídeo/música generados (por defecto: {DEFAULT_DURATION}s)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--api", action="store_true", help="Usar la YouTube Data API v3 (requiere YOUTUBE_API_KEY)"
    )
    mode.add_argument(
        "--html", action="store_true", help="Usar el parser de la página pública (por defecto)"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Canal sintético (sin red) + vídeo/música generados con FFmpeg",
    )
    return parser


# ---------------------------------------------------------------------------
# Canal sintético (modo demo, sin red)
# ---------------------------------------------------------------------------


def demo_channel() -> ChannelData:
    """Construye un canal sintético para demostrar el flujo sin red."""
    base_url = "https://www.youtube.com/@canaldemo"
    videos = [
        VideoData(
            title="Python 3.13: TOP 10 novedades que debes conocer",
            url=f"{base_url}/watch?id=1",
            video_id="demo1",
            views="1,2 M",
            likes="45 K",
            comments="1.023",
            duration="12:34",
            publish_date="2026-08-20",
            thumbnail_url=None,
            description="Repaso de las novedades de Python 3.13. #python #programacion",
            hashtags=["python", "programacion"],
            channel_name="Canal Demo (sintético)",
            channel_url=base_url,
        ),
        VideoData(
            title="¿Cómo funciona asyncio por dentro?",
            url=f"{base_url}/watch?id=2",
            video_id="demo2",
            views="890 K",
            likes="32 K",
            comments="540",
            duration="18:20",
            publish_date="2026-08-10",
            description="Guía visual de asyncio. #python #async #tutorial",
            hashtags=["python", "async", "tutorial"],
            channel_name="Canal Demo (sintético)",
            channel_url=base_url,
        ),
        VideoData(
            title="GUÍA COMPLETA de FastAPI para principiantes",
            url=f"{base_url}/watch?id=3",
            video_id="demo3",
            views="2,3 M",
            likes="98 K",
            comments="2.451",
            duration="45:10",
            publish_date="2026-07-28",
            description="Todo lo que necesitas para empezar con FastAPI. #fastapi #python",
            hashtags=["fastapi", "python"],
            channel_name="Canal Demo (sintético)",
            channel_url=base_url,
        ),
        VideoData(
            title="Streamlit vs Gradio: ¿cuál elegir?",
            url=f"{base_url}/watch?id=4",
            video_id="demo4",
            views="410 K",
            likes="15 K",
            comments="312",
            duration="9:45",
            publish_date="2026-07-15",
            description="Comparativa práctica. #python #streamlit #gradio",
            hashtags=["python", "streamlit", "gradio"],
            channel_name="Canal Demo (sintético)",
            channel_url=base_url,
        ),
    ]
    return ChannelData(
        name="Canal Demo (sintético)",
        url=base_url,
        handle="canaldemo",
        subscribers="12,3 K",
        total_views="1,5 M",
        videos=videos,
    )


# ---------------------------------------------------------------------------
# Generación de medios de prueba con FFmpeg (sin dependencias externas)
# ---------------------------------------------------------------------------


async def generate_test_video(path: str, duration: int = DEFAULT_DURATION) -> str:
    """Genera un vídeo de prueba (testsrc + tono) con FFmpeg.

    Incluye una pista de audio sintética para que la mezcla de música de
    fondo (``amix`` sobre ``[0:a]``) funcione sin ficheros externos.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        path,
    ]
    await run_command(cmd)
    return path


async def generate_test_music(path: str, duration: int = DEFAULT_DURATION) -> str:
    """Genera una pista de música de prueba (tono senoidal) con FFmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=523:duration={duration}",
        "-c:a",
        "libmp3lame",
        path,
    ]
    await run_command(cmd)
    return path


# ---------------------------------------------------------------------------
# Flujo completo
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    """Convierte un texto en un nombre de fichero seguro (ASCII)."""
    return (
        "".join(c if c.isalnum() and ord(c) < 128 else "-" for c in text)
        .strip("-")
        .lower()
        or "canal"
    )


def _print_videos_table(channel: ChannelData, max_videos: int) -> None:
    table = Table(title=f"Últimos {min(len(channel.videos), max_videos)} vídeos")
    table.add_column("Título", style="cyan")
    table.add_column("Vistas", justify="right")
    table.add_column("Duración", justify="right")
    for video in channel.videos[:max_videos]:
        table.add_row(video.title, video.views, video.duration or "-")
    console.print(table)


def _print_insights(insights: dict[str, Any]) -> None:
    top = insights["top_hashtags"][:5]
    if top:
        hashtags = ", ".join(f"#{entry['hashtag']} ({entry['count']})" for entry in top)
        console.print(f"🏷️  Hashtags más usados: [bold]{hashtags}[/]")
    patterns = insights["title_patterns"]
    console.print(
        "📈 Patrones de títulos: "
        f"[bold]{patterns['with_numbers']}[/] con números, "
        f"[bold]{patterns['with_uppercase_words']}[/] en MAYÚSCULAS, "
        f"[bold]{patterns['with_question']}[/] con pregunta, "
        f"[bold]{patterns['with_vs']}[/] con 'vs'"
    )
    duration = insights["duration_stats"]
    if duration["count"]:
        console.print(
            f"⏱️  Duración media: [bold]{duration['avg_seconds']}[/] s "
            f"(mín {duration['min_seconds']}, máx {duration['max_seconds']})"
        )
    views = insights["views_summary"]
    if views["avg"]:
        console.print(f"👁️  Vistas medias: [bold]{views['avg']:,.0f}[/] | máx: {views['max']:,.0f}")


async def run_workflow(
    channel_ref: str = DEFAULT_CHANNEL,
    max_videos: int = 10,
    output_dir: str = "reports",
    video_path: str | None = None,
    music_path: str | None = None,
    duration: int = DEFAULT_DURATION,
    mode: str = "html",
    demo: bool = False,
) -> dict[str, Any]:
    """Ejecuta el flujo completo de investigación + edición.

    Args:
        channel_ref: URL/handle del canal (ignorado si ``demo=True``).
        max_videos: Número máximo de vídeos a extraer.
        output_dir: Directorio donde guardar los resultados.
        video_path: Vídeo local; si es ``None`` se genera uno con FFmpeg.
        music_path: Música local; si es ``None`` se genera una con FFmpeg.
        duration: Duración (s) de los medios generados.
        mode: ``"html"`` o ``"api"`` para la investigación.
        demo: Usar canal sintético (sin red).

    Returns:
        Diccionario con las rutas de todos los artefactos generados.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Paso 1: investigación del canal
    console.print(Panel.fit("[bold cyan]Paso 1/6 · Investigación del canal[/]", border_style="cyan"))
    if demo:
        channel = demo_channel()
        console.print(f"📺 Canal sintético: [bold]{channel.name}[/] (sin red)")
    else:
        analyzer = ChannelAnalyzer()
        channel = await analyzer.analyze(channel_ref, max_videos=max_videos, mode=mode)
        console.print(f"📺 Canal: [bold]{channel.name}[/] · {channel.subscribers or '?'} suscriptores")

    # Paso 2: vídeos recientes
    console.print(Panel.fit("[bold cyan]Paso 2/6 · Vídeos recientes[/]", border_style="cyan"))
    _print_videos_table(channel, max_videos)

    # Paso 3: insights de patrones
    console.print(Panel.fit("[bold cyan]Paso 3/6 · Insights de patrones[/]", border_style="cyan"))
    insights = channel_overview(channel)
    _print_insights(insights)

    # Paso 4: vídeo de ejemplo
    console.print(Panel.fit("[bold cyan]Paso 4/6 · Vídeo de ejemplo[/]", border_style="cyan"))
    if video_path:
        video = Path(video_path)
        console.print(f"🎬 Vídeo local: [bold]{video}[/]")
    else:
        video = out / "test_video.mp4"
        console.print(f"🎬 Generando vídeo de prueba (FFmpeg): [bold]{video}[/]")
        await generate_test_video(str(video), duration)
    console.print(f"   Vídeo: [green]{video}[/]")

    # Paso 5: música de fondo
    console.print(Panel.fit("[bold cyan]Paso 5/6 · Música de fondo[/]", border_style="cyan"))
    if music_path:
        music = Path(music_path)
        console.print(f"🎵 Música local: [bold]{music}[/]")
    else:
        music = out / "test_music.mp3"
        console.print(f"🎵 Generando música de prueba (FFmpeg): [bold]{music}[/]")
        await generate_test_music(str(music), duration)
    console.print(f"   Música: [green]{music}[/]")

    # Paso 6: edición y exportación
    console.print(Panel.fit("[bold cyan]Paso 6/6 · Edición y exportación[/]", border_style="cyan"))
    final_video = out / f"{_slug(channel.name)}_final.mp4"
    console.print(f"🎛️  Añadiendo música de fondo → [bold]{final_video}[/]")
    await add_background_music(
        str(video),
        str(music),
        str(final_video),
        volume=0.3,
        fade_in=2,
        fade_out=2,
    )

    stem = _slug(channel.name)
    json_path = export_channel(channel, out / f"{stem}.json", fmt="json")
    csv_path = export_videos(channel.videos, out / f"{stem}_videos.csv", fmt="csv")
    md_path = out / f"{stem}.md"
    md_path.write_text(generate_channel_markdown(channel), encoding="utf-8")

    console.print(f"✅ Vídeo final: [bold green]{final_video}[/]")
    console.print(f"📄 Exportados: {json_path.name}, {csv_path.name}, {md_path.name}")
    return {
        "channel": channel.name,
        "videos": len(channel.videos),
        "video": str(video),
        "music": str(music),
        "final_video": str(final_video),
        "json": str(json_path),
        "csv": str(csv_path),
        "markdown": str(md_path),
    }


def main() -> None:
    """Entry point de ``youber-workflow``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    try:
        asyncio.run(
            run_workflow(
                channel_ref=args.channel,
                max_videos=args.max_videos,
                output_dir=args.output_dir,
                video_path=args.video,
                music_path=args.music,
                duration=args.duration,
                mode="api" if args.api else "html",
                demo=args.demo,
            )
        )
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
