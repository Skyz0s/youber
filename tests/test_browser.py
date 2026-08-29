"""Tests del núcleo de navegación (``youber.core.browser``)."""

import pytest

from youber.core.browser import BrowserManager
from youber.core.exceptions import BrowserException, TimeoutException
from youber.core.fixtures import sample_navigation

EXAMPLE_URL = "https://example.com"


async def test_browser_launch():
    """Lanza el navegador, lo comprueba y lo cierra."""
    manager = BrowserManager(headless=True)
    try:
        await manager.launch()
        assert manager.is_launched
    finally:
        await manager.close()
    assert not manager.is_launched


async def test_new_context_with_defaults():
    """El contexto se crea con viewport y configuración por defecto."""
    manager = BrowserManager(headless=True)
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)
        assert page.viewport_size == {"width": 1920, "height": 1080}
    finally:
        await manager.close()


async def test_navigation():
    """Navega a una URL real y verifica la URL final."""
    manager = BrowserManager(headless=True)
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)
        await manager.navigate(page, EXAMPLE_URL)
        assert "example.com" in page.url
    finally:
        await manager.close()


async def test_get_title():
    """Obtiene el título de la página navegada."""
    manager = BrowserManager(headless=True)
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)
        await manager.navigate(page, EXAMPLE_URL)
        title = await manager.get_title(page)
        assert title == "Example Domain"
    finally:
        await manager.close()


async def test_new_context_without_launch_raises():
    """Usar el manager sin lanzar el navegador lanza BrowserException."""
    manager = BrowserManager(headless=True)
    with pytest.raises(BrowserException):
        await manager.new_context()


async def test_sample_navigation_fixture():
    """El fixture devuelve título y logs del proceso."""
    result = await sample_navigation(headless=True)
    assert result.title == "Example Domain"
    assert any("Lanzando navegador" in log for log in result.logs)
    assert any("Título obtenido" in log for log in result.logs)


def test_timeout_exception_is_timeout_error():
    """TimeoutException es capturable como TimeoutError nativo."""
    assert issubclass(TimeoutException, TimeoutError)
