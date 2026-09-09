"""CLI ``youber-api`` — funcionalidades de Youber en JSON para el dashboard.

Uso:

.. code-block:: bash

    youber-api status --json
    youber-api music list --limit 10 --json
    youber-api music search "Bohemian" --json
    youber-api music lyrics "Bohemian Rhapsody" --json
    youber-api discovery search "python" --category tecnología --limit 10 --json
    youber-api research channel "@python" --limit 10 --json
    youber-api schedule list --json
    youber-api jobs submit --type produce --topic "Python" \\
        --pipeline screen-demo --track "Bohemian Rhapsody" --sync --json
    youber-api jobs status <job-id> --json
    youber-api jobs history --limit 20 --json
    youber-api uploads status --json

Siempre imprime JSON en stdout (envoltorio ``{"ok": true, "data": ...}`` o
``{"ok": false, "error": ...}``); ``--json`` solo añade formato legible.
Exit code 0 si ok, 1 si error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from youber.api.server import handle

# Rutas sin subacción: command -> route
_SINGLE = {"status": "status"}


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="JSON formateado (default: JSON compacto)")


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de ``youber-api`` (comandos anidados)."""
    parser = argparse.ArgumentParser(
        prog="youber-api",
        description="Youber API bridge: funcionalidades en JSON para el dashboard",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- status ------------------------------------------------------------
    status = sub.add_parser("status", help="Estado general de Youber")
    _add_json(status)
    status.add_argument("--library", default="music", help="Directorio del catálogo (default: music)")

    # --- music -------------------------------------------------------------
    music = sub.add_parser("music", help="Catálogo de música")
    music_sub = music.add_subparsers(dest="action", required=True)

    music_list = music_sub.add_parser("list", help="Lista las pistas")
    _add_json(music_list)
    music_list.add_argument("--limit", type=int, default=50)
    music_list.add_argument("--library", default="music")

    music_search = music_sub.add_parser("search", help="Busca pistas por texto")
    _add_json(music_search)
    music_search.add_argument("query")
    music_search.add_argument("--limit", type=int, default=50)
    music_search.add_argument("--library", default="music")

    music_lyrics = music_sub.add_parser("lyrics", help="Letra de una pista (ID o título)")
    _add_json(music_lyrics)
    music_lyrics.add_argument("query")
    music_lyrics.add_argument("--library", default="music")

    # --- discovery ---------------------------------------------------------
    discovery = sub.add_parser("discovery", help="Búsqueda de canales de YouTube")
    discovery_sub = discovery.add_subparsers(dest="action", required=True)
    disc_search = discovery_sub.add_parser("search", help="Busca canales")
    _add_json(disc_search)
    disc_search.add_argument("query", nargs="?", default=None)
    disc_search.add_argument("--category", default=None, help="Categoría (ej: tecnología)")
    disc_search.add_argument("--mode", choices=("auto", "api", "html", "demo"), default="auto")
    disc_search.add_argument("--limit", type=int, default=10)

    # --- research ----------------------------------------------------------
    research = sub.add_parser("research", help="Análisis de canales")
    research_sub = research.add_subparsers(dest="action", required=True)
    res_channel = research_sub.add_parser("channel", help="Datos de un canal")
    _add_json(res_channel)
    res_channel.add_argument("channel")
    res_channel.add_argument("--mode", choices=("auto", "html", "api"), default="auto")
    res_channel.add_argument("--limit", type=int, default=10)

    # --- schedule ----------------------------------------------------------
    schedule = sub.add_parser("schedule", help="Tareas programadas")
    schedule_sub = schedule.add_subparsers(dest="action", required=True)
    schedule_list = schedule_sub.add_parser("list", help="Lista las tareas")
    _add_json(schedule_list)

    # --- jobs --------------------------------------------------------------
    jobs = sub.add_parser("jobs", help="Jobs de larga duración")
    jobs_sub = jobs.add_subparsers(dest="action", required=True)

    submit = jobs_sub.add_parser("submit", help="Lanza un job (produce/workflow/upload)")
    _add_json(submit)
    submit.add_argument("--type", required=True, choices=("produce", "workflow", "upload"))
    # produce
    submit.add_argument("--topic")
    submit.add_argument("--pattern")
    submit.add_argument("--pipeline", default=None)
    submit.add_argument("--sync", action="store_true")
    submit.add_argument("--style", default=None)
    submit.add_argument("--lyrics", default=None)
    submit.add_argument("--whisper", action="store_true")
    submit.add_argument("--model", default=None)
    submit.add_argument("--duration", type=float, default=None)
    submit.add_argument("--resolution", default=None)
    submit.add_argument("--fps", type=int, default=None)
    submit.add_argument("--output", default=None)
    # comunes (workflow/upload)
    submit.add_argument("--track", default=None)
    submit.add_argument("--library", default=None)
    submit.add_argument("--channel", default=None)
    submit.add_argument("--demo", action="store_true")
    submit.add_argument("--output-dir", dest="output_dir", default=None)
    submit.add_argument("--upload", action="store_true")
    submit.add_argument("--privacy", default=None)
    submit.add_argument("--video", default=None)
    submit.add_argument("--title", default=None)
    submit.add_argument("--description", default=None)
    submit.add_argument("--tags", nargs="*", default=None)
    submit.add_argument("--category", default=None)

    jobs_status = jobs_sub.add_parser("status", help="Estado de un job")
    _add_json(jobs_status)
    jobs_status.add_argument("id")

    jobs_history = jobs_sub.add_parser("history", help="Historial de jobs")
    _add_json(jobs_history)
    jobs_history.add_argument("--limit", type=int, default=20)

    # --- uploads -----------------------------------------------------------
    uploads = sub.add_parser("uploads", help="Estado de subidas")
    uploads_sub = uploads.add_subparsers(dest="action", required=True)
    uploads_status = uploads_sub.add_parser("status", help="Estado de la subida a YouTube")
    _add_json(uploads_status)

    return parser


def _route_for(args: argparse.Namespace) -> str:
    if args.command in _SINGLE:
        return _SINGLE[args.command]
    return f"{args.command}.{args.action}"


def _params_for(args: argparse.Namespace) -> dict[str, Any]:
    """Parámetros JSON-safe: quita metadatos de argparse y valores vacíos."""
    skip = {"command", "action", "json"}
    params: dict[str, Any] = {}
    for key, value in vars(args).items():
        if key in skip or value is None or value is False:
            continue
        params[key] = value
    return params


async def _run(args: argparse.Namespace) -> int:
    route = _route_for(args)
    params = _params_for(args)
    envelope = await handle(route, params)
    kwargs = {"indent": 2} if getattr(args, "json", False) else {"separators": (",", ":")}
    print(json.dumps(envelope, ensure_ascii=False, **kwargs))
    return 0 if envelope.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point de ``youber-api``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
