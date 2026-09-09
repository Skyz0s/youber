"""Bridge ``youber.api`` — funcionalidades de Youber en JSON.

Comando: ``youber-api <ruta> [flags]`` (ver ``youber.api.cli``). Dispatcher
en :mod:`youber.api.server`; rutas registradas en :mod:`youber.api.routes`.
Modo subproceso para el plugin del dashboard::

    python -m youber.api.server --route music.list --params '{"library": "music"}'

Consumido por el plugin de la Control UI (Fase 2) y por scripts.
"""
