"""Dispatcher del bridge ``youber.api``.

``handle(route, params)`` resuelve una ruta canónica (``"music.list"``,
``"jobs.submit"``, ...) contra el registro de :mod:`youber.api.routes` y
devuelve un dict JSON-safe con el envoltorio ``{"ok": true, "data": ...}``.
Los errores controlados (:class:`ApiError`) se devuelven como
``{"ok": false, "error": ...}``.
"""

from __future__ import annotations

import traceback
from typing import Any

from loguru import logger

from youber.api.models import ApiError
from youber.api.routes import ROUTES

__all__ = ["ROUTES", "handle", "list_routes"]


def list_routes() -> list[str]:
    """Rutas registradas (ordenadas)."""
    return sorted(ROUTES)


async def handle(route: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ejecuta una ruta del bridge y devuelve el envoltorio JSON-safe."""
    handler = ROUTES.get(route)
    if handler is None:
        return {"ok": False, "error": f"Ruta desconocida: {route!r}"}
    try:
        data = await handler(params or {})
        return {"ok": True, "data": data}
    except ApiError as exc:
        logger.warning("ApiError en {route}: {exc}", route=route, exc=exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — el bridge nunca debe reventar
        logger.error("Error interno en {}: {}", route, traceback.format_exc())
        return {"ok": False, "error": f"Error interno: {exc}"}
