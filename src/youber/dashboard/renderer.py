"""Renderizado del dashboard de BARF (HTML, Markdown y JSON).

Convierte :class:`~youber.dashboard.models.WidgetData` en salida legible:
un widget suelto o un dashboard completo con varios widgets.
"""

from __future__ import annotations

import json
from typing import Any

from youber.dashboard.models import WidgetData


def _format_value(value: Any) -> str:
    """Formatea un valor simple (número, str, dict o lista) como texto."""
    if isinstance(value, dict):
        return ", ".join(f"{key}: {_format_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "; ".join(_format_value(item) for item in value)
    return str(value)


def _key_value_lines(data: dict[str, Any]) -> list[str]:
    """Convierte un dict de métricas en líneas ``clave: valor``."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"- **{key}:**")
            for sub_key, sub_value in value.items():
                lines.append(f"  - {sub_key}: {_format_value(sub_value)}")
        elif isinstance(value, list):
            lines.append(f"- **{key}:** {_format_value(value)}")
        else:
            lines.append(f"- **{key}:** {value}")
    return lines


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def render_widget_markdown(data: WidgetData) -> str:
    """Renderiza un widget en Markdown."""
    lines = [f"### {data.title}", ""]
    lines.extend(_key_value_lines(data.data))
    return "\n".join(lines) + "\n"


def render_dashboard_markdown(widgets: list[WidgetData]) -> str:
    """Renderiza un dashboard completo en Markdown."""
    lines = ["# Dashboard — Youber", ""]
    for widget in sorted(widgets, key=lambda item: item.widget_id):
        lines.append(render_widget_markdown(widget))
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def _escape_html(text: str) -> str:
    """Escapa texto para HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_widget_html(data: WidgetData) -> str:
    """Renderiza un widget como tarjeta HTML."""
    lines = [
        f'<div class="widget" id="{data.widget_id}">',
        f"  <h3>{_escape_html(data.title)}</h3>",
        "  <ul>",
    ]
    for line in _key_value_lines(data.data):
        lines.append(f"    <li>{_escape_html(line)}</li>")
    lines += ["  </ul>", "</div>"]
    return "\n".join(lines)


def render_dashboard_html(widgets: list[WidgetData]) -> str:
    """Renderiza un dashboard completo en HTML (página autocontenida)."""
    body = "\n".join(
        render_widget_html(widget)
        for widget in sorted(widgets, key=lambda item: item.widget_id)
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<title>Dashboard — Youber</title>\n"
        "<style>"
        "body{font-family:sans-serif;margin:2rem;background:#f7f7f7}"
        ".widget{background:#fff;border:1px solid #ddd;border-radius:8px;"
        "padding:1rem 1.5rem;margin-bottom:1rem}"
        "h3{margin-top:0}li{margin:0.2rem 0}"
        "</style>\n</head>\n<body>\n"
        f"<h1>Dashboard — Youber</h1>\n{body}\n"
        "</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def render_widget_json(data: WidgetData) -> str:
    """Serializa un widget a JSON."""
    return data.model_dump_json(indent=2)


def render_dashboard_json(widgets: list[WidgetData]) -> str:
    """Serializa un dashboard completo a JSON (lista de widgets)."""
    payload = [widget.model_dump(mode="json") for widget in widgets]
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


RENDERERS = {
    "md": render_dashboard_markdown,
    "markdown": render_dashboard_markdown,
    "html": render_dashboard_html,
    "json": render_dashboard_json,
}


def render_dashboard(widgets: list[WidgetData], fmt: str = "md") -> str:
    """Renderiza un dashboard completo en el formato indicado.

    Args:
        widgets: Datos de los widgets.
        fmt: ``md``/``markdown``, ``html`` o ``json``.

    Returns:
        El dashboard renderizado.

    Raises:
        ValueError: si el formato no está soportado.
    """
    renderer = RENDERERS.get(fmt.lower())
    if renderer is None:
        raise ValueError(f"Formato no soportado: {fmt!r} (usa md, html o json)")
    return renderer(widgets)
