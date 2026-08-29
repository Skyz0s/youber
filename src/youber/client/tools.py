"""Wrappers de alto nivel sobre las herramientas MCP del servidor BARF."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from mcp import ClientSession

CLIENT_HELP = """\
Cliente MCP de BARF — métodos disponibles:
  open_page(url)                    Abre una página y devuelve su info
  audit_accessibility(url)          Audita la accesibilidad con axe-core
  trace_journey(urls)               Traza un journey (open + navigate)
  simulate_geolocation(url, region) Simula geo/idioma/zona horaria
  simulate_network(url, speed)      Simula un perfil de red
  simulate_device(url, device)      Simula un dispositivo
  get_help()                        Muestra esta ayuda"""


def _parse_result(result: Any) -> dict[str, Any]:
    """Extrae el contenido JSON de un ``CallToolResult`` (SDK 2.x)."""
    if getattr(result, "is_error", False):
        raise RuntimeError(f"La herramienta MCP devolvió un error: {result}")
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured if isinstance(structured, dict) else {"data": structured}
    texts = [item.text for item in getattr(result, "content", []) if hasattr(item, "text")]
    payload = "\n".join(texts)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": payload}


class MCPTools:
    """Cliente de alto nivel para las herramientas del servidor BARF.

    Args:
        session: Sesión MCP inicializada (ver :func:`create_mcp_session`).
    """

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def _call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        logger.debug(f"Llamando herramienta MCP '{name}' con {arguments}")
        result = await self._session.call_tool(name, arguments)
        return _parse_result(result)

    async def open_page(self, url: str) -> dict[str, Any]:
        """Abre una página en la URL indicada.

        Returns:
            ``page_id``, ``url``, ``title``, ``status`` y ``logs``.
        """
        return await self._call("open_page", {"url": url})

    async def audit_accessibility(self, url: str) -> dict[str, Any]:
        """Abre la página y ejecuta una auditoría de accesibilidad (axe-core).

        Returns:
            Violaciones, checks superados, incompletos y mensaje.
        """
        opened = await self._call("open_page", {"url": url})
        return await self._call("audit_accessibility", {"page_id": opened["page_id"]})

    async def trace_journey(self, urls: list[str]) -> dict[str, Any]:
        """Traza un journey: abre la primera URL y navega el resto con la misma página.

        Args:
            urls: URLs del recorrido en orden.

        Returns:
            Pasos del journey (URL, título/estado) y si se completó.
        """
        if not urls:
            return {"steps": [], "completed": False}
        first = await self._call("open_page", {"url": urls[0]})
        steps = [
            {
                "url": first["url"],
                "title": first["title"],
                "status": first["status"],
            }
        ]
        page_id = first["page_id"]
        for url in urls[1:]:
            nav = await self._call("navigate_to", {"url": url, "page_id": page_id})
            steps.append(
                {
                    "url": nav["new_url"],
                    "previous_url": nav["previous_url"],
                    "status": nav["status"],
                }
            )
        return {"steps": steps, "completed": len(steps) == len(urls)}

    async def simulate_geolocation(self, url: str, region: str) -> dict[str, Any]:
        """Abre la URL con la región simulada y devuelve las señales de localización."""
        return await self._call("simulate_geolocation", {"url": url, "region": region})

    async def simulate_network(self, url: str, speed: str) -> dict[str, Any]:
        """Abre la URL con un perfil de red simulado y devuelve la especificación."""
        return await self._call("simulate_network", {"url": url, "speed": speed})

    async def simulate_device(self, url: str, device_name: str) -> dict[str, Any]:
        """Abre la URL con un dispositivo simulado y devuelve la especificación."""
        return await self._call("simulate_device", {"url": url, "device_name": device_name})

    async def get_help(self) -> str:
        """Devuelve la ayuda del cliente."""
        return CLIENT_HELP
