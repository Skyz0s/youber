"""Utilidades de logging para el núcleo de BARF.

Incluye el decorador :func:`log_action` (INFO para acciones normales, DEBUG
para detalles, ERROR si falla) y el gestor de contexto :func:`capture_logs`
para recolectar los mensajes de log generados durante una ejecución.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from loguru import logger

_LOG_FORMAT = "{time:HH:mm:ss} | {level: <8} | {message}"


def log_action(message: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorador que registra el inicio y el resultado de una acción asíncrona.

    Registra ``INFO`` al iniciar, ``DEBUG`` al completar y ``ERROR`` si la
    acción lanza una excepción (que se re-lanza tal cual).

    Args:
        message: Descripción breve de la acción, p. ej. "Navegando".

    Returns:
        El decorador listo para aplicar sobre una corrutina.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.info(f"{message}...")
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                logger.error(f"{message} falló: {exc}")
                raise
            logger.debug(f"{message} OK")
            return result

        return wrapper

    return decorator


@contextmanager
def capture_logs(sink: list[str], level: str = "INFO") -> Iterator[None]:
    """Captura los mensajes de loguru durante la ejecución de un bloque.

    Args:
        sink: Lista donde se irán acumulando los mensajes formateados.
        level: Nivel mínimo de log a capturar (por defecto ``INFO``).

    Yields:
        Nada; el bloque se ejecuta dentro del gestor de contexto.
    """
    handler_id = logger.add(sink.append, level=level.upper(), format=_LOG_FORMAT)
    try:
        yield
    finally:
        logger.remove(handler_id)
