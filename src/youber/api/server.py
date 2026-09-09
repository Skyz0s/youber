"""Dispatcher del bridge ``youber.api``.

``handle(route, params)`` resuelve una ruta canónica (``"music.list"``,
``"jobs.submit"``, ...) contra el registro de :mod:`youber.api.routes` y
devuelve un dict JSON-safe con el envoltorio ``{"ok": true, "data": ...}``.
Los errores controlados (:class:`ApiError`) se devuelven como
``{"ok": false, "error": ...}``.
"""

from __future__ import annotations

import asyncio
import json
import sys
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


def _main(argv: list[str] | None = None) -> int:
    """Modo subproceso usado por el plugin (proxy HTTP → bridge).

    Uso: ``python -m youber.api.server --route <ruta> --params '<json>'``
    Imprime el envoltorio JSON en stdout; exit 0 si ok, 1 si error.
    """
    import argparse

    # stdout en UTF-8: en Windows el codec por defecto (cp1252) rompe con
    # emojis/unicode de los logs (UnicodeEncodeError) al imprimir el JSON.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="python -m youber.api.server")
    parser.add_argument("--route", required=True, help="Ruta canónica (music.list, ...)")
    parser.add_argument("--params", default="{}", help="Parámetros en JSON")
    args = parser.parse_args(argv)
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError:
        print('{"ok": false, "error": "params JSON inválido"}')
        return 1
    if not isinstance(params, dict):
        print('{"ok": false, "error": "params debe ser un objeto JSON"}')
        return 1
    envelope = asyncio.run(handle(args.route, params))
    print(json.dumps(envelope, ensure_ascii=False))
    return 0 if envelope.get("ok") else 1


if __name__ == "__main__":
    sys.exit(_main())
