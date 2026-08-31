"""Servicio en segundo plano del scheduler de BARF.

:func:`run_daemon` ejecuta un bucle que revisa periódicamente los trabajos
pendientes del :class:`~youber.scheduler.scheduler.Scheduler` y los ejecuta.
Se detiene de forma limpia con un :class:`asyncio.Event`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from youber.scheduler.scheduler import Scheduler


async def run_daemon(
    scheduler: Scheduler,
    interval: float = 60.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Ejecuta el bucle del scheduler en segundo plano.

    Cada ``interval`` segundos ejecuta los trabajos pendientes
    (``scheduler.run_due()``). El bucle termina cuando se activa
    ``stop_event`` o se recibe ``KeyboardInterrupt``.

    Args:
        scheduler: Scheduler con los trabajos programados.
        interval: Segundos entre comprobaciones.
        stop_event: Evento opcional para detener el bucle limpiamente.
    """
    stop = stop_event or asyncio.Event()
    logger.info(f"Daemon del scheduler arrancado (intervalo {interval}s)")
    while not stop.is_set():
        try:
            results = await scheduler.run_due(datetime.now())
            if results:
                ok = sum(1 for result in results if result.get("status") == "ok")
                logger.info(f"Daemon: {len(results)} trabajo(s) ejecutado(s), {ok} ok")
        except Exception as exc:
            logger.error(f"Daemon: error ejecutando trabajos: {exc}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
    logger.info("Daemon del scheduler detenido")


class Daemon:
    """Wrapper asíncrono del bucle del scheduler (arrancar/detener)."""

    def __init__(self, scheduler: Scheduler, interval: float = 60.0) -> None:
        """Crea el daemon.

        Args:
            scheduler: Scheduler con los trabajos programados.
            interval: Segundos entre comprobaciones.
        """
        self.scheduler = scheduler
        self.interval = interval
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        """Arranca el bucle en segundo plano (tarea asíncrona)."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            run_daemon(self.scheduler, self.interval, self._stop_event)
        )

    async def stop(self) -> None:
        """Detiene el bucle limpiamente y espera a que termine."""
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
