"""CLI interactiva del cliente MCP de BARF (comando ``youber-client``)."""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from youber.client.session import create_mcp_session
from youber.client.tools import MCPTools
from youber.console import ensure_utf8_console

HELP_TEXT = """\
Comandos disponibles:
  open <url>                  Abre una página
  audit <url>                 Auditoría de accesibilidad (axe-core)
  journey <url1> <url2>...    Traza un user journey
  geo <region> <url>          Simula geolocalización (ES, US, JP, BR, ...)
  network <speed> <url>       Simula red (4g, 3g, 2g, slow-3g, offline)
  device <nombre> <url>       Simula dispositivo (iPhone, Pixel, iPad, Desktop)
  help                        Muestra esta ayuda
  exit                        Sale de la CLI"""


def _require(args: list[str], minimum: int, usage: str) -> None:
    """Comprueba que hay suficientes argumentos o lanza ValueError."""
    if len(args) < minimum:
        raise ValueError(f"Faltan argumentos. Uso: {usage}")


async def execute_command(tools: MCPTools, line: str) -> str:
    """Ejecuta un comando de la CLI y devuelve la salida en texto plano.

    Separada del bucle REPL para poder testearla directamente: los comandos
    ``help``, ``exit`` y los desconocidos no necesitan servidor.

    Args:
        tools: Cliente MCP de alto nivel.
        line: Línea de comando (p. ej. ``audit https://example.com``).

    Returns:
        Salida formateada del comando.

    Raises:
        ValueError: si faltan argumentos.
    """
    parts = shlex.split(line)
    if not parts:
        return ""
    command = parts[0].lower()
    args = parts[1:]

    if command in ("help", "ayuda", "?"):
        return HELP_TEXT
    if command in ("exit", "quit", "salir"):
        return "Hasta luego 👋"

    if command == "open":
        _require(args, 1, "open <url>")
        result = await tools.open_page(args[0])
        return (
            f"📄 Página abierta: {result['url']}\n"
            f"   Título: {result['title']}\n"
            f"   Estado: {result['status']}"
        )

    if command == "audit":
        _require(args, 1, "audit <url>")
        result = await tools.audit_accessibility(args[0])
        return (
            f"🔎 Auditoría de {args[0]}\n"
            f"   Violaciones: {result['total_violations']}\n"
            f"   {result.get('message') or '⚠️ Hay violaciones: revisa el detalle'}"
        )

    if command == "journey":
        _require(args, 1, "journey <url1> <url2> ...")
        result = await tools.trace_journey(args)
        lines = [f"🧭 Journey: {len(result['steps'])} pasos"]
        for index, step in enumerate(result["steps"], start=1):
            lines.append(f"   {index}. {step['url']} — {step.get('title') or step.get('status')}")
        return "\n".join(lines)

    if command == "geo":
        _require(args, 2, "geo <region> <url>")
        signals = await tools.simulate_geolocation(args[1], args[0])
        return (
            f"📍 Región {args[0].upper()}\n"
            f"   language: {signals['navigator_language']}\n"
            f"   timezone: {signals['timezone']}"
        )

    if command == "network":
        _require(args, 2, "network <speed> <url>")
        spec = await tools.simulate_network(args[1], args[0])
        return (
            f"🌐 Red simulada: {args[0]} "
            f"(latencia {spec['latency']} ms, offline={spec['offline']})"
        )

    if command == "device":
        _require(args, 2, "device <nombre> <url>")
        spec = await tools.simulate_device(args[1], args[0])
        return f"📱 Dispositivo: {args[0]} — viewport {spec['viewport']}"

    return f"❓ Comando desconocido: {command}. Usa 'help' para ver los disponibles."


async def run_interactive(session: Any) -> None:
    """Bucle REPL de la CLI interactiva.

    Args:
        session: Sesión MCP inicializada.
    """
    console = Console()
    tools = MCPTools(session)
    history: list[str] = []
    console.print(Panel("BARF — cliente MCP. Escribe 'help' para los comandos.", title="⚙️ Youber"))
    while True:
        try:
            line = Prompt.ask("[cyan]youber[/cyan]")
        except (EOFError, KeyboardInterrupt):
            console.print("\nHasta luego 👋")
            break
        line = line.strip()
        if not line:
            continue
        history.append(line)
        try:
            output = await execute_command(tools, line)
            console.print(output)
        except Exception as exc:
            console.print(f"[red]Error:[/red] {exc}")


async def _run() -> None:
    async with create_mcp_session() as session:
        await run_interactive(session)


def main() -> None:
    """Entry point ``youber-client``."""
    ensure_utf8_console()
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, EOFError):
        pass
