"""CLI ``youber-dashboard``: dashboard de métricas del ecosistema Youber.

Comandos: ``list`` (widgets disponibles), ``render`` (un widget concreto),
``dashboard`` (todos los widgets por defecto) y ``serve`` (dashboard en
el navegador con auto-refresco).

Ejemplos:

.. code-block:: bash

    youber-dashboard list
    youber-dashboard render catalog-stats
    youber-dashboard dashboard --format html -o dashboard.html
    youber-dashboard dashboard --format json
    youber-dashboard serve            # navegador en http://127.0.0.1:8787
    youber-dashboard serve --port 9000 --refresh 30
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
    dashboard.add_argument(
        "--widgets",
        type=_parse_widgets,
        default=None,
        help=(
            "Widgets a incluir, separados por comas "
            "(p. ej. catalog-stats,scheduled-tasks,upload-status). "
            "Por defecto: todos los disponibles."
        ),
    )
    dashboard.add_argument("--music-dir", default="music", help="Directorio del catálogo de música")

    serve_parser = sub.add_parser("serve", help="Sirve el dashboard en el navegador (auto-refresco)")
    serve_parser.add_argument(
        "--widgets",
        type=_parse_widgets,
        default=None,
        help=(
            "Widgets a mostrar, separados por comas "
            "(p. ej. catalog-stats,scheduled-tasks,upload-status). "
            "Por defecto: los de la configuración guardada."
        ),
    )
    serve_parser.add_argument("--port", type=int, default=None, help="Puerto local (por defecto 8787)")
    serve_parser.add_argument("--refresh", type=int, default=None, help="Segundos entre auto-refrescos")
    serve_parser.add_argument("--no-open", action="store_true", help="No abrir el navegador automáticamente")
    serve_parser.add_argument("--config", default=None, help="Fichero de configuración del dashboard")

    return parser


def _parse_widgets(value: str) -> list[WidgetType]:
    """Convierte una lista separada por comas en tipos de widget válidos."""
    return [_widget_type(item) for item in value.split(",") if item.strip()]


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
        if args.widgets:
            widgets = [
                create_widget(widget_type, position=index)
                for index, widget_type in enumerate(args.widgets)
            ]
        else:
            widgets = [widget for widget in default_widgets() if widget.type not in {
                WidgetType.CHANNEL_TRENDS,
                WidgetType.CHANNEL_COMPARISON,
                WidgetType.TOP_VIDEOS,
                WidgetType.ENGAGEMENT_METRICS,
            }]
        collected = manager.collect_many(widgets)
        _emit(render_dashboard(collected, args.format), args.output)
    elif args.command == "serve":
        from youber.dashboard.serve import DEFAULT_CONFIG_PATH
        from youber.dashboard.serve import serve as serve_dashboard

        selected = [widget.value for widget in args.widgets] if args.widgets else None
        serve_dashboard(
            config_path=args.config or DEFAULT_CONFIG_PATH,
            widgets=selected,
            refresh_seconds=args.refresh,
            port=args.port,
            open_browser=not args.no_open,
        )
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
