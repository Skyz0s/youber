"""Dashboard personalizado con BARF — ejemplo educativo.

Genera un dashboard HTML con una selección concreta de widgets (catálogo
de música, tareas programadas y estado de subidas) y lo guarda en un
fichero. La API del dashboard es síncrona: no hace falta asyncio.

Uso:
    python examples/custom_dashboard.py [--output custom_dashboard.html] [--format html|md|json]

Ejemplos:
    python examples/custom_dashboard.py
    python examples/custom_dashboard.py --format md
    python examples/custom_dashboard.py --output reports/dashboard.json --format json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from youber.console import ensure_utf8_console
from youber.dashboard import WidgetManager
from youber.dashboard.renderer import render_dashboard, render_dashboard_html

# Los widgets que quieres mostrar (los que existen en el sistema)
WIDGET_TYPES = ["catalog-stats", "scheduled-tasks", "upload-status"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard personalizado de BARF")
    parser.add_argument("--output", default="custom_dashboard.html", help="Fichero de salida")
    parser.add_argument("--format", choices=["md", "html", "json"], default="html")
    args = parser.parse_args()

    # Crear el gestor de widgets
    manager = WidgetManager()

    # Crear + recolectar los widgets de una vez (en el orden indicado)
    data = manager.collect_types(WIDGET_TYPES)

    # Generar la salida (HTML / Markdown / JSON)
    rendered = render_dashboard_html(data) if args.format == "html" else render_dashboard(data, args.format)

    # Guardar
    output_path = Path(args.output)
    output_path.write_text(rendered, encoding="utf-8")

    print(f"✅ Dashboard generado: {output_path}")
    print(f"📊 Abre: {output_path.absolute()}")


if __name__ == "__main__":
    ensure_utf8_console()
    main()
