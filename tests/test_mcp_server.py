"""Tests de la capa MCP de BARF (herramientas + registro del servidor)."""

from pathlib import Path

import pytest

from youber.core.exceptions import BrowserException
from youber.mcp.models.responses import (
    AccessibilityAuditResponse,
    OpenPageResponse,
    PageInfoResponse,
)
from youber.mcp.server import BrowserSession, build_server
from youber.mcp.tools import accessibility, navigation

ACCESSIBLE_URL = (Path(__file__).parent / "fixtures" / "accessible.html").resolve().as_uri()
EXAMPLE_URL = "https://example.com"


@pytest.fixture
async def session():
    """Sesión de navegador aislada por test (headless: CI no tiene display X)."""
    s = BrowserSession(headless=True)
    yield s
    await s.close()


async def test_open_page(session):
    """open_page abre una URL real y devuelve título, estado y logs."""
    result = await navigation.open_page(session, EXAMPLE_URL)
    assert isinstance(result, OpenPageResponse)
    assert result.page_id
    assert result.title == "Example Domain"
    assert result.status == 200
    assert result.logs, "open_page debe devolver los logs del proceso"


async def test_get_page_info(session):
    """get_page_info devuelve URL, título y viewport."""
    opened = await navigation.open_page(session, ACCESSIBLE_URL)
    info = await navigation.get_page_info(session, opened.page_id)
    assert isinstance(info, PageInfoResponse)
    assert info.url == ACCESSIBLE_URL
    assert info.title == "Página accesible de prueba"
    assert info.viewport == {"width": 1920, "height": 1080}


async def test_navigate_to(session):
    """navigate_to navega desde una página existente a otra URL."""
    opened = await navigation.open_page(session, ACCESSIBLE_URL)
    nav = await navigation.navigate_to(session, EXAMPLE_URL, opened.page_id)
    assert nav.previous_url == ACCESSIBLE_URL
    assert "example.com" in nav.new_url
    assert nav.status == 200


async def test_navigate_to_missing_page(session):
    """navigate_to con page_id inexistente lanza BrowserException."""
    with pytest.raises(BrowserException):
        await navigation.navigate_to(session, EXAMPLE_URL, "no-existe")


async def test_audit_accessibility(session):
    """La auditoría sobre una página accesible devuelve 0 violaciones."""
    opened = await navigation.open_page(session, ACCESSIBLE_URL)
    audit = await accessibility.audit_accessibility(session, opened.page_id)
    assert isinstance(audit, AccessibilityAuditResponse)
    assert audit.total_violations == 0
    assert audit.message is not None
    assert len(audit.passes) > 0, "debe haber checks de accesibilidad superados"


async def test_server_registers_all_tools():
    """El servidor MCP registra las 4 herramientas esperadas."""
    server = build_server()
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert {"open_page", "navigate_to", "get_page_info", "audit_accessibility"} <= names
