"""Herramienta MCP de accesibilidad: ``audit_accessibility`` (axe-core).

Delega en el módulo :mod:`youber.accessibility` (``AxeRunner``), la
implementación única de auditorías con axe-core en el framework.
"""

from __future__ import annotations

from loguru import logger

from youber.accessibility.axe_runner import AxeRunner
from youber.mcp.models.responses import AccessibilityAuditResponse

SUCCESS_MESSAGE = "✅ Sin violaciones de accesibilidad detectadas."

_runner = AxeRunner()


async def audit_accessibility(session: object, page_id: str) -> AccessibilityAuditResponse:
    """Ejecuta una auditoría de accesibilidad con axe-core sobre la página.

    Args:
        session: Sesión de navegador compartida.
        page_id: Identificador de la página a auditar.

    Returns:
        Violaciones, checks superados, checks incompletos y total de
        violaciones. Si no hay violaciones, incluye un mensaje de éxito.

    Raises:
        BrowserException: Si ``page_id`` no existe en la sesión.
    """
    page = session.get_page(page_id)  # type: ignore[attr-defined]
    logger.info(f"Auditando accesibilidad de la página '{page_id}' ({page.url})...")

    results = await _runner.run_axe(page)
    total = results.total_violations
    message = None if total else SUCCESS_MESSAGE
    logger.info(
        f"Auditoría completada: {total} violaciones, "
        f"{len(results.passes)} checks superados, {len(results.incomplete)} incompletos"
    )
    return AccessibilityAuditResponse(
        violations=results.violations,
        passes=results.passes,
        incomplete=results.incomplete,
        total_violations=total,
        message=message,
    )
