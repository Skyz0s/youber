"""Servidor web del dashboard de BARF.

Permite **trabajar directamente en el dashboard** desde el navegador, sin
tocar comandos: ``youber-dashboard serve`` abre una página local que se
auto-refresca, muestra los widgets seleccionados y permite cambiar la
selección con checkboxes (se guarda en ``~/.youber/dashboard.json``).

Solo usa la librería estándar (``http.server``), escucha en 127.0.0.1 y no
expone datos fuera de la máquina.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from loguru import logger

from youber.dashboard.models import WidgetData, WidgetType
from youber.dashboard.renderer import render_widget_html
from youber.dashboard.widgets import WidgetManager

DEFAULT_CONFIG_PATH = Path.home() / ".youber" / "dashboard.json"
DEFAULT_WIDGETS = ["catalog-stats", "scheduled-tasks", "upload-status"]
# Libre en esta máquina: 8765 lo usa Lumenoia y 18789 el gateway de OpenClaw.
DEFAULT_PORT = 8787
DEFAULT_REFRESH = 60  # segundos


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Carga la configuración del dashboard (widgets, refresco, puerto).

    Si el fichero no existe, devuelve los valores por defecto (los tres
    widgets de trabajo diario: catálogo, tareas programadas y subidas).
    """
    file = Path(path)
    if not file.exists():
        return {
            "widgets": list(DEFAULT_WIDGETS),
            "refresh_seconds": DEFAULT_REFRESH,
            "port": DEFAULT_PORT,
        }
    raw = json.loads(file.read_text(encoding="utf-8"))
    config = {
        "widgets": list(DEFAULT_WIDGETS),
        "refresh_seconds": DEFAULT_REFRESH,
        "port": DEFAULT_PORT,
    }
    config.update(raw)
    return config


def save_config(config: dict[str, Any], path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    """Guarda la configuración del dashboard en el fichero indicado."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class DashboardApp:
    """Aplicación del dashboard: configuración + recolección de datos."""

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        widgets: list[str] | None = None,
        refresh_seconds: int | None = None,
        port: int | None = None,
    ) -> None:
        config = load_config(config_path)
        self.config_path = Path(config_path)
        self.widgets: list[str] = widgets or config["widgets"]
        self.refresh_seconds: int = refresh_seconds or config["refresh_seconds"]
        self.port: int = port or config["port"]
        self.manager = WidgetManager()

    def collect(self) -> list[WidgetData]:
        """Recolecta los datos de los widgets seleccionados."""
        return self.manager.collect_types(self.widgets)

    def data_payload(self) -> dict[str, Any]:
        """Payload JSON del endpoint ``/api/data`` (para el polling)."""
        from datetime import datetime

        return {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "refresh_seconds": self.refresh_seconds,
            "widgets": [
                widget.model_dump(mode="json") for widget in self.collect()
            ],
        }

    def render_page(self) -> str:
        """Página HTML del dashboard (autocontenida, con JS de polling)."""
        checkboxes = "\n".join(
            f'<label class="chk"><input type="checkbox" name="widget" value="{widget.value}"'
            f'{" checked" if widget.value in self.widgets else ""}> {widget.value}</label>'
            for widget in WidgetType
        )
        cards = "\n".join(
            render_widget_html(data) for data in self.collect()
        )
        refresh = self.refresh_seconds
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Dashboard — Youber</title>
<style>
body{{font-family:sans-serif;margin:2rem;background:#f7f7f7;color:#222}}
h1{{margin-bottom:0.2rem}}
.sub{{color:#666;font-size:0.9rem;margin-bottom:1rem}}
#updated{{color:#777;font-size:0.8rem;margin-top:0.5rem}}
.controls{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:0.8rem 1.2rem;margin-bottom:1.2rem}}
.chk{{margin-right:0.9rem;white-space:nowrap}}
button{{margin-left:0.6rem;padding:0.25rem 1rem;cursor:pointer}}
#grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:1rem}}
.widget{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:1rem 1.5rem}}
.widget h3{{margin-top:0}}li{{margin:0.2rem 0}}
</style>
</head>
<body>
<h1>📊 Dashboard — Youber</h1>
<p class="sub">Auto-refresco cada {refresh}s · configuración guardada en {self.config_path}</p>
<div class="controls">
  <form id="config-form">
    {checkboxes}
    <button type="submit">Guardar selección</button>
  </form>
</div>
<div id="grid">{cards}</div>
<p id="updated"></p>
<script>
const REFRESH_MS = {refresh} * 1000;
async function loadData() {{
  const res = await fetch('/api/data');
  const payload = await res.json();
  const grid = document.getElementById('grid');
  grid.innerHTML = payload.widgets.map(w => {{
    const items = Object.entries(w.data).map(([k, v]) =>
      `<li><strong>${{k}}:</strong> ${{JSON.stringify(v)}}</li>`).join('');
    return `<div class="widget"><h3>${{w.title}}</h3><ul>${{items}}</ul></div>`;
  }}).join('');
  document.getElementById('updated').textContent =
    'Última actualización: ' + payload.updated_at;
}}
document.getElementById('config-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const selected = [...document.querySelectorAll('input[name=widget]:checked')]
    .map(cb => cb.value);
  await fetch('/api/config', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{widgets: selected}}),
  }});
  location.reload();
}});
setInterval(loadData, REFRESH_MS);
loadData();
</script>
</body>
</html>
"""


def make_handler(dashboard_app: DashboardApp) -> type[BaseHTTPRequestHandler]:
    """Crea la clase handler del servidor HTTP con la app inyectada."""

    class DashboardHandler(BaseHTTPRequestHandler):
        """Sirve la página del dashboard y sus endpoints JSON."""

        app = dashboard_app

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug(f"[dashboard] {self.address_string()} {format % args}")

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/data":
                self._send_json(self.app.data_payload())
                return
            body = self.app.render_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/config":
                self._send_json({"error": "no encontrado"}, status=404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                widgets = body.get("widgets", self.app.widgets)
                self.app.widgets = [
                    widget for widget in widgets if widget in WidgetType._value2member_map_
                ]
                save_config(
                    {
                        "widgets": self.app.widgets,
                        "refresh_seconds": self.app.refresh_seconds,
                        "port": self.app.port,
                    },
                    self.app.config_path,
                )
                self._send_json({"ok": True, "widgets": self.app.widgets})
            except Exception as exc:  # pragma: no cover - defensivo
                logger.warning(f"Error en POST /api/config: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

    return DashboardHandler


def serve(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    widgets: list[str] | None = None,
    refresh_seconds: int | None = None,
    port: int | None = None,
    open_browser: bool = True,
    host: str = "127.0.0.1",
) -> None:
    """Arranca el servidor web del dashboard (bloqueante hasta Ctrl+C).

    Args:
        config_path: Fichero de configuración (widgets, refresco, puerto).
        widgets: Selección de widgets (sobreescribe la config).
        refresh_seconds: Segundos entre actualizaciones automáticas.
        port: Puerto local (por defecto 8765, desde la config).
        open_browser: Abre el navegador automáticamente.
        host: Interfaz donde escuchar (por defecto solo local).
    """
    app = DashboardApp(
        config_path=config_path,
        widgets=widgets,
        refresh_seconds=refresh_seconds,
        port=port,
    )
    save_config(
        {
            "widgets": app.widgets,
            "refresh_seconds": app.refresh_seconds,
            "port": app.port,
        },
        app.config_path,
    )
    server = ThreadingHTTPServer((host, app.port), make_handler(app))
    url = f"http://{host}:{server.server_address[1]}"
    logger.info(f"Dashboard en {url} (Ctrl+C para parar)")
    print(f"📊 Dashboard en {url}")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=[url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Servidor del dashboard parado")
    finally:
        server.server_close()
