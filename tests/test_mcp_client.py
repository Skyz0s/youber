"""Tests end-to-end del cliente MCP contra el servidor real (stdio).

El servidor se lanza en un subproceso (``python -m youber.mcp.server``) y las
llamadas viajan por el protocolo MCP de verdad.

Nota: la sesión se gestiona dentro del cuerpo de cada test (no como fixture
con ``yield``) porque pytest-asyncio + anyio (que usa mcp 2.x) producen un
``RuntimeError: Attempted to exit cancel scope in a different task`` al
finalizar fixtures async generadores.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from youber.client.session import create_mcp_session
from youber.client.tools import MCPTools

FIXTURES = Path(__file__).parent / "fixtures"
ACCESSIBLE_URL = (FIXTURES / "accessible.html").resolve().as_uri()
INDEX_URL = (FIXTURES / "site" / "index.html").resolve().as_uri()
ABOUT_URL = (FIXTURES / "site" / "about.html").resolve().as_uri()
EXAMPLE_URL = "https://example.com"


@asynccontextmanager
async def _client() -> AsyncIterator[MCPTools]:
    """Cliente MCP conectado al servidor (un servidor por test, headless).

    El servidor se lanza como subproceso; le forzamos ``BROWSER_HEADLESS``
    solo durante el arranque y restauramos el entorno al salir, para no
    contaminar el resto de la suite (p. ej. test_settings).
    """
    previous = os.environ.get("BROWSER_HEADLESS")
    os.environ["BROWSER_HEADLESS"] = "true"
    try:
        async with create_mcp_session() as session:
            yield MCPTools(session)
    finally:
        if previous is None:
            os.environ.pop("BROWSER_HEADLESS", None)
        else:
            os.environ["BROWSER_HEADLESS"] = previous


async def test_open_page():
    async with _client() as tools:
        result = await tools.open_page(EXAMPLE_URL)
        assert result["title"] == "Example Domain"
        assert result["status"] == 200
        assert result["logs"]


async def test_audit_accessibility():
    async with _client() as tools:
        result = await tools.audit_accessibility(ACCESSIBLE_URL)
        assert result["total_violations"] == 0
        assert result["message"]


async def test_trace_journey():
    async with _client() as tools:
        result = await tools.trace_journey([INDEX_URL, ABOUT_URL])
        assert result["completed"] is True
        assert len(result["steps"]) == 2


async def test_simulate_geolocation():
    async with _client() as tools:
        signals = await tools.simulate_geolocation(ACCESSIBLE_URL, "JP")
        assert signals["timezone"] == "Asia/Tokyo"
        assert signals["navigator_language"] == "ja-JP"


async def test_simulate_network():
    async with _client() as tools:
        spec = await tools.simulate_network(EXAMPLE_URL, "4g")
        assert spec["latency"] == 20
        assert spec["offline"] is False


async def test_simulate_device():
    async with _client() as tools:
        spec = await tools.simulate_device(EXAMPLE_URL, "iPhone")
        assert spec["viewport"]["width"] == 390


async def test_get_help():
    async with _client() as tools:
        help_text = await tools.get_help()
        assert "open_page" in help_text
        assert "audit_accessibility" in help_text
