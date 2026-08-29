"""Modelos Pydantic para las respuestas de las herramientas MCP de BARF.

Definen el contrato de salida de cada herramienta: los agentes de IA reciben
siempre objetos JSON con esta forma, validados y documentados.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OpenPageResponse(BaseModel):
    """Respuesta de :func:`open_page <youber.mcp.tools.navigation.open_page>`.

    Attributes:
        page_id: Identificador de la página creada o reutilizada.
        url: URL final de la página.
        title: Título de la página.
        status: Código de estado HTTP (``None`` para esquemas sin respuesta,
            como ``file://`` o ``data:``).
        logs: Mensajes de log generados durante la operación.
    """

    page_id: str = Field(description="Identificador de la página en la sesión")
    url: str = Field(description="URL final de la página")
    title: str = Field(description="Título de la página")
    status: int | None = Field(description="Código de estado HTTP, si aplica")
    logs: list[str] = Field(default_factory=list, description="Logs del proceso")


class NavigationResponse(BaseModel):
    """Respuesta de :func:`navigate_to <youber.mcp.tools.navigation.navigate_to>`.

    Attributes:
        previous_url: URL en la que estaba la página antes de navegar.
        new_url: URL final tras la navegación.
        status: Código de estado HTTP de la nueva página (``None`` si no aplica).
    """

    previous_url: str = Field(description="URL previa de la página")
    new_url: str = Field(description="URL tras la navegación")
    status: int | None = Field(description="Código de estado HTTP, si aplica")


class PageInfoResponse(BaseModel):
    """Respuesta de :func:`get_page_info <youber.mcp.tools.navigation.get_page_info>`.

    Attributes:
        url: URL actual de la página.
        title: Título de la página.
        viewport: Tamaño del viewport (``{"width": ..., "height": ...}``).
    """

    url: str = Field(description="URL actual de la página")
    title: str = Field(description="Título de la página")
    viewport: dict[str, int] | None = Field(description="Viewport de la página")


class AccessibilityAuditResponse(BaseModel):
    """Respuesta de
    :func:`audit_accessibility <youber.mcp.tools.accessibility.audit_accessibility>`.

    Attributes:
        violations: Reglas de accesibilidad incumplidas (axe-core).
        passes: Reglas superadas.
        incomplete: Reglas que requieren revisión manual.
        total_violations: Número de violaciones detectadas.
        message: Mensaje informativo (éxito si no hay violaciones).
    """

    violations: list[dict[str, Any]] = Field(default_factory=list)
    passes: list[dict[str, Any]] = Field(default_factory=list)
    incomplete: list[dict[str, Any]] = Field(default_factory=list)
    total_violations: int = Field(description="Número total de violaciones")
    message: str | None = Field(
        default=None,
        description="Mensaje informativo del resultado de la auditoría",
    )
