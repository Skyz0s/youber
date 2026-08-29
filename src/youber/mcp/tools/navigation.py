"""Herramientas MCP de navegación: ``open_page``, ``navigate_to`` y ``get_page_info``.

Todas las funciones reciben una *sesión* (objeto con el navegador compartido y
el registro de páginas) para mantener persistencia entre llamadas del agente.
"""

from __future__ import annotations

from loguru import logger

from youber.core.logging import capture_logs
from youber.mcp.models.responses import NavigationResponse, OpenPageResponse, PageInfoResponse


async def open_page(session: object, url: str, page_id: str | None = None) -> OpenPageResponse:
    """Abre una página en la URL indicada.

    Crea una nueva página en la sesión (o reutiliza ``page_id`` si existe) y
    navega a la URL. Devuelve la información de la página y los logs del
    proceso, útil para que el agente pueda inspeccionar qué ocurrió.

    Args:
        session: Sesión de navegador compartida (persistencia entre llamadas).
        url: URL de destino.
        page_id: Identificador de página a reutilizar; si no se indica o no
            existe, se crea una nueva.

    Returns:
        Respuesta con página, título, estado HTTP y logs.

    Raises:
        TimeoutException: Si la navegación supera el timeout.
        NavigationException: Si la navegación falla.
    """
    logs: list[str] = []
    with capture_logs(logs):
        pid, page, status = await session.open_page(url, page_id)  # type: ignore[attr-defined]
        title = await session.manager.get_title(page)  # type: ignore[attr-defined]
        logger.info(f"open_page: '{url}' -> título '{title}' (status={status})")
    return OpenPageResponse(page_id=pid, url=page.url, title=title, status=status, logs=logs)


async def navigate_to(session: object, url: str, page_id: str) -> NavigationResponse:
    """Navega desde una página existente a una nueva URL.

    Args:
        session: Sesión de navegador compartida.
        url: Nueva URL de destino.
        page_id: Identificador de la página existente que debe navegar.

    Returns:
        Respuesta con la URL previa, la nueva URL y el estado HTTP.

    Raises:
        BrowserException: Si ``page_id`` no existe en la sesión.
        TimeoutException / NavigationException: Si la navegación falla.
    """
    page = session.get_page(page_id)  # type: ignore[attr-defined]
    previous_url = page.url
    status = await session.manager.navigate(page, url)  # type: ignore[attr-defined]
    logger.info(f"navigate_to: '{previous_url}' -> '{page.url}' (status={status})")
    return NavigationResponse(previous_url=previous_url, new_url=page.url, status=status)


async def get_page_info(session: object, page_id: str) -> PageInfoResponse:
    """Obtiene información de la página indicada.

    Args:
        session: Sesión de navegador compartida.
        page_id: Identificador de la página.

    Returns:
        URL, título y viewport de la página.

    Raises:
        BrowserException: Si ``page_id`` no existe en la sesión.
    """
    page = session.get_page(page_id)  # type: ignore[attr-defined]
    title = await session.manager.get_title(page)  # type: ignore[attr-defined]
    logger.info(f"get_page_info: página '{page_id}' -> '{page.url}'")
    return PageInfoResponse(url=page.url, title=title, viewport=page.viewport_size)
