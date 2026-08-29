"""Fixtures de ejemplo del framework BARF.

Contiene flujos completos listos para usar o estudiar. El primero,
:func:`sample_navigation`, ejecuta una navegación de ejemplo de principio a
fin y devuelve el título de la página junto con los logs del proceso.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from youber.core.browser import BrowserManager
from youber.core.logging import capture_logs


@dataclass
class SampleNavigationResult:
    """Resultado de una navegación de ejemplo.

    Attributes:
        title: Título de la página visitada.
        logs: Mensajes de log generados durante el proceso.
    """

    title: str
    logs: list[str] = field(default_factory=list)


async def sample_navigation(
    headless: bool = True,
    url: str = "https://example.com",
) -> SampleNavigationResult:
    """Ejecuta una navegación de ejemplo completa.

    Lanza el navegador, crea un contexto aislado, navega a la URL indicada,
    obtiene el título y cierra el navegador. Devuelve el título y los logs
    del proceso, lo que permite estudiar la secuencia completa de acciones.

    Args:
        headless: Ejecutar el navegador sin interfaz gráfica.
        url: URL de destino de la navegación de ejemplo.

    Returns:
        Resultado con el título de la página y los logs del proceso.
    """
    logs: list[str] = []
    with capture_logs(logs):
        manager = BrowserManager(headless=headless)
        try:
            await manager.launch()
            context = await manager.new_context()
            page = await manager.new_page(context)
            await manager.navigate(page, url)
            title = await manager.get_title(page)
            logger.info(f"Título obtenido: {title}")
        finally:
            await manager.close()
    return SampleNavigationResult(title=title, logs=logs)
