"""Paso 3 de la demo: cliente MCP end-to-end contra el servidor real (stdio).

Conecta con :func:`create_mcp_session`, llama a las herramientas del servidor
y muestra las respuestas. El navegador del servidor es headless por defecto
(``BROWSER_HEADLESS=true``); ponlo a ``false`` para verlo abrirse en pantalla.

Uso: python examples/demo_mcp.py [URL]
"""

from __future__ import annotations

import argparse
import asyncio
import os

from youber.client.session import create_mcp_session
from youber.client.tools import MCPTools
from youber.console import ensure_utf8_console

DEFAULT_URL = "https://example.com"


async def main(url: str) -> None:
    """Ejecuta la demo del cliente MCP contra el servidor real."""
    headless = os.environ.get("BROWSER_HEADLESS", "true").lower() in {"1", "true", "yes"}
    print("  Conectando al servidor MCP (stdio)...")
    async with create_mcp_session(env={"BROWSER_HEADLESS": "true" if headless else "false"}) as session:
        tools = MCPTools(session)

        info = await tools.open_page(url)
        print(f"  open_page            -> título: {info['title']} | status: {info['status']}")

        audit = await tools.audit_accessibility(url)
        print(f"  audit_accessibility  -> violaciones: {audit['total_violations']}")
        print(f"  {audit.get('message') or '⚠️ Revisa el detalle de las violaciones'}")


def main_entry() -> None:
    """Entry point con argparse."""
    ensure_utf8_console()
    parser = argparse.ArgumentParser(description="Demo del cliente MCP de BARF")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help=f"URL (por defecto: {DEFAULT_URL})")
    args = parser.parse_args()
    asyncio.run(main(args.url))


if __name__ == "__main__":
    main_entry()
