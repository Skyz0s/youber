"""Capa MCP del framework BARF: servidor y herramientas para agentes de IA."""

from youber.mcp.models.responses import (
    AccessibilityAuditResponse,
    NavigationResponse,
    OpenPageResponse,
    PageInfoResponse,
)
from youber.mcp.server import build_server, main

__all__ = [
    "AccessibilityAuditResponse",
    "NavigationResponse",
    "OpenPageResponse",
    "PageInfoResponse",
    "build_server",
    "main",
]
