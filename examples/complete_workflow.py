"""Flujo completo de investigación + edición — ejemplo educativo de BARF.

Demuestra el pipeline de principio a fin:

1. Investiga un canal público de YouTube (datos y vídeos recientes).
2. Extrae datos de los últimos vídeos (título, vistas, duración).
3. Genera insights sobre patrones de éxito (hashtags, títulos, duración).
4. Prepara un vídeo de ejemplo (local o generado con FFmpeg).
5. Añade música de fondo (local o generada con FFmpeg).
6. Exporta el resultado final (JSON/CSV/Markdown + vídeo MP4).

Auto-contenido: si no pasas ``--video`` ni ``--music``, genera ambos con
FFmpeg (testsrc + tono senoidal), sin dependencias externas. El modo
``--demo`` usa un canal sintético y no necesita red.

Uso:
    python examples/complete_workflow.py --demo -o reports
    python examples/complete_workflow.py --channel @python -n 10 -o reports
    python examples/complete_workflow.py --video mi_video.mp4 --music mi_musica.mp3 -o reports

Nota ética: usa solo **tu propia música** (o con licencia) y vídeos propios
o con permiso. Esto es edición educativa, no manipulación de métricas.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from youber.cli.workflow_cli import run_workflow
from youber.console import ensure_utf8_console

console = Console()

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def main() -> None:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(
        description="BARF: flujo completo de investigación de YouTube + edición de audio"
    )
    parser.add_argument(
        "--channel", default="@python", help="Canal a investigar (por defecto: @python)"
    )
    parser.add_argument("-n", "--max-videos", type=int, default=10, help="Vídeos a extraer")
    parser.add_argument(
        "-o", "--output-dir", default=str(REPORTS_DIR), help="Directorio de salida"
    )
    parser.add_argument("--video", default=None, help="Vídeo local (si no, se genera uno)")
    parser.add_argument("--music", default=None, help="Música local (si no, se genera una)")
    parser.add_argument("--duration", type=int, default=30, help="Duración de los medios generados (s)")
    parser.add_argument("--api", action="store_true", help="Usar la YouTube Data API v3 (requiere YOUTUBE_API_KEY)")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Usar un canal sintético (sin red) con medios generados por FFmpeg",
    )
    args = parser.parse_args()

    console.print(
        Panel.fit(
            "[bold]BARF · Flujo completo: investigación de YouTube + edición de audio[/]",
            border_style="magenta",
        )
    )
    try:
        result = asyncio.run(
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

    console.print(
        Panel.fit(
            "[bold green]Flujo completado[/]\n"
            f"Canal: {result['channel']} · {result['videos']} vídeos analizados\n"
            f"Vídeo final: {result['final_video']}\n"
            f"Datos: {result['json']} · {result['csv']} · {result['markdown']}",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
