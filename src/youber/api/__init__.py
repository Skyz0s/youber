"""Bridge ``youber.api`` — funcionalidades de Youber en JSON.

Comando: ``youber-api <ruta> [flags]`` (ver ``youber.api.cli``). Dispatcher
en :mod:`youber.api.server`; rutas registradas en :mod:`youber.api.routes`.
Consumido por el plugin del dashboard (Fase 2) y por scripts.
"""

from youber.api.server import handle, list_routes

__all__ = ["handle", "list_routes"]
