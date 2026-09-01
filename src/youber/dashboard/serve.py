"""Servidor web del dashboard de BARF.

Permite **trabajar directamente en el dashboard** desde el navegador, sin
tocar comandos: ``youber-dashboard serve`` abre una página local que se
auto-refresca, muestra los widgets seleccionados y permite cambiar la
selección con checkboxes (se guarda en ``~/.youber/dashboard.json``).

Solo usa la librería estándar (``http.server``), escucha en 127.0.0.1 y no
expone datos fuera de la máquina.
"""

from __future__ import annotations

import asyncio
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
from youber.music.models import TrackSource
from youber.music.providers import import_cloud

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
        library_dir: str | Path = "music",
    ) -> None:
        config = load_config(config_path)
        self.config_path = Path(config_path)
        self.widgets: list[str] = widgets or config["widgets"]
        self.refresh_seconds: int = refresh_seconds or config["refresh_seconds"]
        self.port: int = port or config["port"]
        self.library_dir = Path(library_dir)
        self._library: Any = None
        self.manager = WidgetManager()

    def collect(self) -> list[WidgetData]:
        """Recolecta los datos de los widgets seleccionados."""
        return self.manager.collect_types(self.widgets)

    async def import_cloud(
        self,
        query: str,
        source: TrackSource | str = TrackSource.APPLE,
        limit: int = 10,
        external_ids: list[str] | None = None,
    ) -> dict[str, int]:
        """Busca en la plataforma e importa al catálogo del dashboard.

        Usa el mismo catálogo local que muestra el widget ``catalog-stats``
        (``<library_dir>/.music.db``), así los cambios se ven al refrescar.
        """
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        return await import_cloud(
            query,
            source,
            limit=limit,
            db=self._library.db,
            external_ids=external_ids,
        )

    async def search_cloud(
        self,
        query: str,
        source: TrackSource | str = TrackSource.APPLE,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Busca en la plataforma y devuelve resultados (sin importar)."""
        from youber.music.providers import search as providers_search

        hits = await providers_search(source, query, limit)
        return {
            "source": TrackSource(source).value,
            "query": query,
            "hits": [hit.model_dump(mode="json") for hit in hits],
        }

    async def import_apple_library(self, path: str) -> dict[str, int]:
        """Importa el XML exportado de la biblioteca de Apple al catálogo."""
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        from youber.music.apple_library import import_apple_library as import_library

        return await import_library(path, db=self._library.db)

    # -- Spotify (OAuth) ----------------------------------------------------

    def _spotify_client(self):
        from youber.music.spotify_library import SpotifyLibraryClient

        return SpotifyLibraryClient(
            redirect_uri=f"http://127.0.0.1:{self.port}/callback"
        )

    def spotify_auth_url(self) -> str:
        """URL de autorización de Spotify para abrir en el navegador."""
        return self._spotify_client().authorization_url()

    async def spotify_exchange(self, code: str) -> dict[str, Any]:
        """Intercambia el código de autorización y guarda la sesión."""
        return await self._spotify_client().exchange_code(code)

    async def spotify_import(self, include_playlists: bool = False) -> dict[str, Any]:
        """Importa la biblioteca de Spotify (Liked Songs + playlists) al catálogo."""
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        from youber.music.spotify_library import import_spotify_library

        return await import_spotify_library(
            client=self._spotify_client(),
            db=self._library.db,
            include_playlists=include_playlists,
        )

    def spotify_status(self) -> dict[str, Any]:
        """Estado de la conexión con Spotify (sin secretos)."""
        client = self._spotify_client()
        return {
            "available": client.available,
            "connected": client.connected,
        }

    # -- YouTube Music (biblioteca personal) -------------------------------

    def ytmusic_status(self) -> dict[str, Any]:
        """Estado de la autenticación de YouTube Music (headers presentes)."""
        from youber.music.youtube_music import DEFAULT_HEADERS_FILE

        return {
            "headers": DEFAULT_HEADERS_FILE.exists(),
            "headers_path": str(DEFAULT_HEADERS_FILE),
        }

    async def ytmusic_import(self, include_playlists: bool = True) -> dict[str, Any]:
        """Importa la biblioteca de YouTube Music (Me gusta + guardadas + playlists)."""
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        from youber.music.youtube_music import (
            YouTubeMusicClient,
            import_ytmusic_library,
        )

        return await import_ytmusic_library(
            client=YouTubeMusicClient(),
            db=self._library.db,
            include_playlists=include_playlists,
        )

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
.status{{margin-left:0.8rem;color:#555;font-size:0.85rem}}
#cloud-results{{margin-top:0.6rem}}
.hit{{display:block;padding:0.25rem 0;cursor:pointer}}
.hit:hover{{background:#f0f4f8}}
.hit .meta{{color:#777;font-size:0.85rem}}
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
<div class="controls" id="cloud-box">
  <form id="cloud-form">
    <strong>🎵 Importar música desde plataforma:</strong>
    <input type="text" id="cloud-q" placeholder="p. ej. lofi beats" style="min-width:220px">
    <select id="cloud-source">
      <option value="apple">Apple (iTunes)</option>
      <option value="spotify">Spotify</option>
    </select>
    <input type="number" id="cloud-limit" value="10" min="1" max="50" style="width:70px">
    <button type="submit">Buscar</button>
    <span id="cloud-status" class="status"></span>
  </form>
  <div id="cloud-results"></div>
  <form id="apple-library-form" style="margin-top:0.8rem;border-top:1px dashed #ccc;padding-top:0.7rem">
    <strong>🍎 Importar TODA tu biblioteca de Apple:</strong>
    <input type="text" id="apple-library-path" placeholder="ruta del XML exportado (p. ej. C:/Users/tu/Music/iTunes/iTunes Music Library.xml)" style="min-width:380px">
    <button type="submit">Importar biblioteca</button>
    <span id="apple-status" class="status"></span>
  </form>
  <form id="ytmusic-form" style="margin-top:0.8rem;border-top:1px dashed #ccc;padding-top:0.7rem">
    <strong>🎧 Importar mi biblioteca de YouTube Music:</strong>
    <label><input type="checkbox" id="ytmusic-playlists" checked> incluir playlists</label>
    <button type="submit">Importar</button>
    <span id="ytmusic-status" class="status"></span>
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
document.getElementById('apple-library-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const path = document.getElementById('apple-library-path').value.trim();
  const status = document.getElementById('apple-status');
  if (!path) {{ status.textContent = 'Escribe la ruta del XML'; return; }}
  status.textContent = 'Importando…';
  const res = await fetch('/api/import-apple-library', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{path}}),
  }});
  const result = await res.json();
  status.textContent = result.error ? '✗ ' + result.error
    : `✅ Biblioteca importada: ${{result.added}} nuevas, ${{result.skipped}} ya existían`;
  loadData();
}});

document.getElementById('ytmusic-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const status = document.getElementById('ytmusic-status');
  status.textContent = 'Importando…';
  const includePlaylists = document.getElementById('ytmusic-playlists').checked;
  const res = await fetch('/api/import-ytmusic', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{include_playlists: includePlaylists}}),
  }});
  const result = await res.json();
  status.textContent = result.error ? '✗ ' + result.error
    : `✅ YouTube Music: ${{result.added}} nuevas, ${{result.skipped}} ya existían`;
  loadData();
}});

(async () => {{
  const res = await fetch('/api/ytmusic-status');
  const status = await res.json();
  const el = document.getElementById('ytmusic-status');
  el.textContent = status.headers
    ? '🔓 autenticado (headers listos)'
    : '🔒 sin autenticar: genera ~/.youber/ytmusic_headers.json (ver docs/MUSIC.md)';
}})();

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

// Importación desde plataforma (Apple/iTunes o Spotify)
function esc(s) {{
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
const cloudStatus = document.getElementById('cloud-status');
document.getElementById('cloud-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const q = document.getElementById('cloud-q').value.trim();
  const source = document.getElementById('cloud-source').value;
  const limit = document.getElementById('cloud-limit').value || 10;
  const box = document.getElementById('cloud-results');
  if (!q) {{ cloudStatus.textContent = 'Escribe una búsqueda'; return; }}
  cloudStatus.textContent = 'Buscando…';
  box.innerHTML = '';
  const params = new URLSearchParams({{q, source, limit}});
  const res = await fetch('/api/search-cloud?' + params.toString());
  const payload = await res.json();
  if (payload.error) {{
    cloudStatus.textContent = '✗ ' + payload.error;
    return;
  }}
  const hits = payload.hits || [];
  if (!hits.length) {{
    cloudStatus.textContent = 'Sin resultados';
    return;
  }}
  cloudStatus.textContent = hits.length + ' resultado(s) — marca y pulsa «Importar»';
  box.innerHTML = hits.map((h, i) => {{
    const meta = [h.artist, h.album, h.duration_s ? Math.round(h.duration_s) + 's' : null]
      .filter(Boolean).join(' · ');
    return '<label class="hit"><input type="checkbox" class="hit-chk" value="' + esc(h.external_id) + '"> '
      + '<strong>' + esc(h.title) + '</strong> <span class="meta">' + esc(meta) + '</span></label>';
  }}).join('') + '<button id="cloud-import">Importar seleccionadas</button>';
  document.getElementById('cloud-import').addEventListener('click', async () => {{
    const ids = [...document.querySelectorAll('.hit-chk:checked')].map(cb => cb.value);
    if (!ids.length) {{ cloudStatus.textContent = 'Marca al menos una pista'; return; }}
    const res2 = await fetch('/api/import-cloud', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{q, source, limit, external_ids: ids}}),
    }});
    const result = await res2.json();
    cloudStatus.textContent = result.error ? '✗ ' + result.error
      : `✅ Importadas: ${{result.added}} nuevas, ${{result.skipped}} ya existían`;
    loadData();
  }});
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
            if self.path.startswith("/api/search-cloud"):
                self._handle_search_cloud()
                return
            if self.path == "/api/ytmusic-status":
                self._send_json(self.app.ytmusic_status())
                return
            body = self.app.render_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_search_cloud(self) -> None:
            """Busca en Apple/Spotify y devuelve resultados JSON (sin importar)."""
            from urllib.parse import parse_qs, urlparse

            try:
                query = parse_qs(urlparse(self.path).query)
                q = (query.get("q") or [""])[0].strip()
                source = (query.get("source") or ["apple"])[0]
                limit = int((query.get("limit") or ["10"])[0])
                if not q:
                    self._send_json({"error": "Parámetro q (búsqueda) requerido"}, status=400)
                    return
                payload = asyncio.run(self.app.search_cloud(q, source, limit))
                self._send_json(payload)
            except Exception as exc:
                logger.warning(f"Error en /api/search-cloud: {exc}")
                self._send_json({"error": str(exc)}, status=400)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/config":
                self._handle_config()
                return
            if self.path == "/api/import-cloud":
                self._handle_import_cloud()
                return
            if self.path == "/api/import-ytmusic":
                self._handle_import_ytmusic()
                return
            if self.path == "/api/import-apple-library":
                self._handle_import_apple_library()
                return
            self._send_json({"error": "no encontrado"}, status=404)

        def _handle_import_ytmusic(self) -> None:
            """Importa la biblioteca de YouTube Music (Me gusta + guardadas + playlists)."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8")) if raw else {}
                include_playlists = bool(body.get("include_playlists", True))
                summary = asyncio.run(
                    self.app.ytmusic_import(include_playlists=include_playlists)
                )
                self._send_json({"ok": True, **summary})
            except Exception as exc:
                logger.warning(f"Error en POST /api/import-ytmusic: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_import_apple_library(self) -> None:
            """Importa un XML de biblioteca de Apple al catálogo."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                path = str(body.get("path", "")).strip()
                if not path:
                    self._send_json({"error": "Parámetro path (ruta del XML) requerido"}, status=400)
                    return
                summary = asyncio.run(self.app.import_apple_library(path))
                self._send_json({"ok": True, **summary})
            except FileNotFoundError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=404)
            except Exception as exc:
                logger.warning(f"Error en POST /api/import-apple-library: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_config(self) -> None:
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

        def _handle_import_cloud(self) -> None:
            """Importa al catálogo las pistas seleccionadas de una plataforma."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                q = str(body.get("q", "")).strip()
                source = str(body.get("source", "apple"))
                limit = int(body.get("limit", 10))
                external_ids = body.get("external_ids")
                if not q:
                    self._send_json({"error": "Parámetro q (búsqueda) requerido"}, status=400)
                    return
                summary = asyncio.run(
                    self.app.import_cloud(
                        q, source, limit=limit, external_ids=external_ids
                    )
                )
                self._send_json({"ok": True, **summary})
            except Exception as exc:
                logger.warning(f"Error en POST /api/import-cloud: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

    return DashboardHandler


def serve(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    widgets: list[str] | None = None,
    refresh_seconds: int | None = None,
    port: int | None = None,
    open_browser: bool = True,
    host: str = "127.0.0.1",
    library_dir: str | Path = "music",
) -> None:
    """Arranca el servidor web del dashboard (bloqueante hasta Ctrl+C).

    Args:
        config_path: Fichero de configuración (widgets, refresco, puerto).
        widgets: Selección de widgets (sobreescribe la config).
        refresh_seconds: Segundos entre actualizaciones automáticas.
        port: Puerto local (por defecto 8787, desde la config).
        open_browser: Abre el navegador automáticamente.
        host: Interfaz donde escuchar (por defecto solo local).
        library_dir: Directorio del catálogo de música (para importar
            desde plataformas y para el widget catalog-stats).
    """
    app = DashboardApp(
        config_path=config_path,
        widgets=widgets,
        refresh_seconds=refresh_seconds,
        port=port,
        library_dir=library_dir,
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
