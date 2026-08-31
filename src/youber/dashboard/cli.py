"""CLI ``youber-dashboard``: dashboard de métricas del ecosistema Youber.

Comandos: ``list`` (widgets disponibles), ``render`` (un widget concreto) y
``dashboard`` (todos los widgets por defecto).

Ejemplos:

.. code-block:: bash

    youber-dashboard list
    youber-dashboard render catalog-stats
    youber-dashboard dashboard --format html -o dashboard.html
    youber-dashboard dashboard --format json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.dashboard.models import WidgetType
from youber.dashboard.registry import list_widgets
from youber.dashboard.renderer import render_dashboard
from youber.dashboard.widgets import WidgetManager, create_widget, default_widgets

console = Console()


def _widget_type(value: str) -> WidgetType:
    """Convierte el texto del usuario en un :class:`WidgetType`."""
    try:
        return WidgetType(value.strip().lower())
    except ValueError as exc:
        valid = ", ".join(widget.value for widget in WidgetType)
        raise argparse.ArgumentTypeError(f"Widget desconocido: {value!r}. Válidos: {valid}") from exc


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-dashboard``."""
    parser = argparse.ArgumentParser(
        prog="youber-dashboard",
        description="BARF: dashboard de métricas del ecosistema Youber",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Lista los widgets disponibles")

    render = sub.add_parser("render", help="Renderiza un widget concreto")
    render.add_argument("type", type=_widget_type, help="Tipo de widget")
    render.add_argument("-f", "--format", choices=["md", "html", "json"], default="md")
    render.add_argument("-o", "--output", default=None, help="Fichero de salida")

    dashboard = sub.add_parser("dashboard", help="Renderiza el dashboard completo")
    dashboard.add_argument("-f", "--format", choices=["md", "html", "json"], default="md")
    dashboard.add_argument("-o", "--output", default=None, help="Fichero de salida")
    dashboard.add_argument("--music-dir", default="music", help="Directorio del catálogo de música")

    return parser


def _print_widgets() -> None:
    table = Table(title="Widgets disponibles")
    table.add_column("Tipo")
    table.add_column("Título")
    table.add_column("Descripción")
    for widget in list_widgets():
        table.add_row(widget["type"], widget["title"], widget["description"])
    console.print(table)


def _emit(text: str, output: str | None) -> None:
    """Muestra por consola o guarda en un fichero."""
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        console.print(f"📄 Guardado: {path}")
    else:
        console.print(text)


def run(args: argparse.Namespace) -> None:
    """Ejecuta el subcomando indicado."""
    if args.command == "list":
        _print_widgets()
        return

    manager = WidgetManager()
    if args.command == "render":
        widget = create_widget(args.type)
        data = manager.collect(widget)
        if args.format == "json":
            from youber.dashboard.renderer import render_widget_json

            _emit(render_widget_json(data), args.output)
        else:
            from youber.dashboard.renderer import render_widget_html, render_widget_markdown

            renderer = render_widget_markdown if args.format == "md" else render_widget_html
            _emit(renderer(data), args.output)
    elif args.command == "dashboard":
        widgets = [widget for widget in default_widgets() if widget.type not in {
            WidgetType.CHANNEL_TRENDS,
            WidgetType.CHANNEL_COMPARISON,
            WidgetType.TOP_VIDEOS,
            WidgetType.ENGAGEMENT_METRICS,
        }]
        collected = manager.collect_many(widgets)
        _emit(render_dashboard(collected, args.format), args.output)
    else:
        raise SystemExit(f"Comando desconocido: {args.command}")


def main() -> None:
    """Entry point de ``youber-dashboard``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    try:
        run(args)
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
