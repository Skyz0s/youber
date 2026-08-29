"""Gestión de sesiones de cliente MCP (MCP Python SDK 2.x).

Proporciona un gestor de contexto que conecta un cliente MCP al servidor de
BARF por stdio, SSE o streamable-http, con reintentos de inicialización y
logging de todas las operaciones.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_SERVER_ARGS = ["-m", "youber.mcp.server"]

_SUPPORTED_TRANSPORTS = ("stdio", "sse", "streamable-http")


async def _initialize_with_retry(session: ClientSession, retries: int) -> None:
    """Inicializa la sesión con reintentos y espera progresiva."""
    for attempt in range(1, retries + 1):
        try:
            await session.initialize()
            logger.info("Sesión MCP inicializada")
            return
        except Exception as exc:
            logger.warning(f"Intento {attempt}/{retries} de inicializar la sesión falló: {exc}")
            if attempt == retries:
                raise
            await asyncio.sleep(0.5 * attempt)


@asynccontextmanager
async def create_mcp_session(
    transport: str = "stdio",
    command: str | None = None,
    server_args: list[str] | None = None,
    url: str | None = None,
    retries: int = 3,
) -> AsyncIterator[ClientSession]:
    """Crea una sesión de cliente MCP conectada al servidor de BARF.

    Args:
        transport: ``stdio`` (por defecto), ``sse`` o ``streamable-http``.
        command: Comando para lanzar el servidor (por defecto, el intérprete
            de Python actual).
        server_args: Argumentos del servidor (por defecto
            ``["-m", "youber.mcp.server"]``).
        url: URL del servidor para los transportes ``sse``/``streamable-http``.
        retries: Reintentos de inicialización antes de fallar.

    Yields:
        Sesión MCP inicializada, lista para ``list_tools``/``call_tool``.

    Raises:
        ValueError: si el transporte no está soportado o falta la URL.
    """
    if transport not in _SUPPORTED_TRANSPORTS:
        raise ValueError(
            f"Transporte desconocido: {transport}. Usa: {', '.join(_SUPPORTED_TRANSPORTS)}"
        )

    if transport == "stdio":
        params = StdioServerParameters(
            command=command or sys.executable,
            args=server_args or DEFAULT_SERVER_ARGS,
        )
        logger.debug(f"Conectando por stdio: {params.command} {' '.join(params.args)}")
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await _initialize_with_retry(session, retries)
                yield session
        return

    if url is None:
        raise ValueError(f"El transporte '{transport}' requiere el parámetro 'url'")

    if transport == "sse":
        from mcp.client.sse import sse_client  # import tardío: SDK 2.x

        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await _initialize_with_retry(session, retries)
                yield session
        return

    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await _initialize_with_retry(session, retries)
            yield session
