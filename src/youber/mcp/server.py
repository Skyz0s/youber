"""Servidor MCP del framework BARF (MCP Python SDK 2.x, ``MCPServer``).

Expone las herramientas del núcleo como herramientas MCP (Model Context
Protocol) para que agentes de IA puedan usarlas. El servidor mantiene una
sesión de navegador compartida: las páginas abiertas persisten entre llamadas
gracias a su ``page_id``.

Uso:

- Stdio (por defecto): ``python -m youber.mcp.server``
- SSE: ``python -m youber.mcp.server --transport sse --port 8000``
- Streamable HTTP: ``python -m youber.mcp.server --transport streamable-http``

Nota de migración: la Fase 5 migró de ``FastMCP`` (mcp<2) a ``MCPServer``
(mcp>=2). Las herramientas devuelven dicts JSON-serializables (``model_dump``)
para máxima compatibilidad con el protocolo 2.x.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from loguru import logger
from mcp.server.mcpserver import MCPServer

from youber.core.browser import BrowserManager
from youber.core.exceptions import BrowserException
from youber.mcp.tools import accessibility, navigation, sandbox

if TYPE_CHECKING:
    from playwright.async_api import Page

SERVER_NAME = "barf"
SERVER_INSTRUCTIONS = (
    "BARF (Browser Automation Research Framework): herramientas educativas de "
    "automatización de navegador para pruebas de accesibilidad, investigación "
    "de UX y testing. Herramientas disponibles: open_page, navigate_to, "
    "get_page_info, audit_accessibility. Uso exclusivamente educativo; no se "
    "manipulan métricas ni se evaden sistemas de seguridad."
)


class BrowserSession:
    """Sesión de navegador compartida entre llamadas MCP.

    Mantiene un :class:`BrowserManager` y un registro de páginas abiertas
    (``page_id`` -> página). El navegador se lanza de forma perezosa en la
    primera operación y se cierra al terminar el proceso.

    Args:
        headless: Ejecutar el navegador sin interfaz gráfica. Si es ``None``,
            se usa la configuración del framework (``BROWSER_HEADLESS``).
    """

    def __init__(self, headless: bool | None = None) -> None:
        self._headless = headless
        self._manager: BrowserManager | None = None
        self._pages: dict[str, Page] = {}

    @property
    def manager(self) -> BrowserManager:
        """El gestor de navegador de la sesión (debe estar iniciado)."""
        if self._manager is None:
            raise BrowserException("El navegador de la sesión no está iniciado")
        return self._manager

    async def ensure_manager(self) -> BrowserManager:
        """Devuelve el gestor de navegador, lanzándolo si hace falta."""
        if self._manager is None:
            self._manager = BrowserManager(headless=self._headless)
            await self._manager.launch()
            logger.info("Navegador de sesión lanzado")
        return self._manager

    async def open_page(
        self,
        url: str,
        page_id: str | None = None,
    ) -> tuple[str, Page, int | None]:
        """Abre una página (nueva o reutilizada) y navega a ``url``.

        Returns:
            Tupla ``(page_id, page, status_http)``.
        """
        manager = await self.ensure_manager()
        if page_id is None or page_id not in self._pages:
            context = await manager.new_context()
            page = await manager.new_page(context)
            pid = page_id or uuid4().hex[:8]
            self._pages[pid] = page
            logger.debug(f"Nueva página registrada en la sesión: {pid}")
        else:
            pid = page_id
            page = self._pages[pid]
            logger.debug(f"Reutilizando página existente: {pid}")
        status = await manager.navigate(page, url)
        return pid, page, status

    def get_page(self, page_id: str) -> Page:
        """Devuelve la página registrada o lanza :class:`BrowserException`."""
        try:
            return self._pages[page_id]
        except KeyError:
            raise BrowserException(f"Página no encontrada en la sesión: {page_id}") from None

    async def close(self) -> None:
        """Cierra el navegador y limpia el registro de páginas."""
        if self._manager is not None:
            await self._manager.close()
            self._manager = None
        self._pages.clear()
        logger.debug("Sesión cerrada")


# --- Singleton de sesión (compartido por todas las herramientas) -----------

_session: BrowserSession | None = None


def _get_session() -> BrowserSession:
    global _session
    if _session is None:
        _session = BrowserSession()
    return _session


def _close_session() -> None:
    global _session
    if _session is not None:
        # Al salir del proceso los streams de log pueden estar cerrados;
        # quitamos los sinks para evitar errores de escritura.
        logger.remove()
        try:
            asyncio.run(_session.close())
        except Exception:  # pragma: no cover - limpieza best-effort
            pass


atexit.register(_close_session)


# --- Construcción del servidor ----------------------------------------------

def build_server() -> MCPServer:
    """Construye el servidor MCP (SDK 2.x) con todas las herramientas.

    Returns:
        Servidor MCP listo para ``run()``.
    """
    mcp = MCPServer(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    session = _get_session()

    @mcp.tool()
    async def open_page(url: str, page_id: str | None = None) -> dict[str, Any]:
        """Abre una página en la URL indicada y devuelve su título, estado y logs."""
        return (await navigation.open_page(session, url, page_id)).model_dump()

    @mcp.tool()
    async def navigate_to(url: str, page_id: str) -> dict[str, Any]:
        """Navega desde una página existente (page_id) a una nueva URL."""
        return (await navigation.navigate_to(session, url, page_id)).model_dump()

    @mcp.tool()
    async def get_page_info(page_id: str) -> dict[str, Any]:
        """Obtiene la URL, el título y el viewport de una página existente."""
        return (await navigation.get_page_info(session, page_id)).model_dump()

    @mcp.tool()
    async def audit_accessibility(page_id: str) -> dict[str, Any]:
        """Ejecuta una auditoría de accesibilidad (axe-core) sobre una página."""
        return (await accessibility.audit_accessibility(session, page_id)).model_dump()

    @mcp.tool()
    async def simulate_geolocation(url: str, region: str) -> dict[str, Any]:
        """Abre una URL con la región simulada (geo, idioma, zona horaria) y devuelve las señales."""
        return await sandbox.geolocation_probe(session, url, region)

    @mcp.tool()
    async def simulate_network(url: str, speed: str) -> dict[str, Any]:
        """Abre una URL con un perfil de red simulado y devuelve la especificación."""
        return await sandbox.network_probe(session, url, speed)

    @mcp.tool()
    async def simulate_device(url: str, device_name: str) -> dict[str, Any]:
        """Abre una URL con un dispositivo simulado y devuelve la especificación."""
        return await sandbox.device_probe(session, url, device_name)

    return mcp


def main() -> None:
    """Punto de entrada: arranca el servidor MCP (stdio, SSE o streamable-http)."""
    parser = argparse.ArgumentParser(description="Servidor MCP de BARF")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transporte del protocolo MCP (por defecto: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host para transporte de red")
    parser.add_argument("--port", type=int, default=8000, help="Puerto para transporte de red")
    args = parser.parse_args()

    logger.info(f"Arrancando servidor MCP '{SERVER_NAME}' (SDK 2.x, {args.transport})...")
    mcp = build_server()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
