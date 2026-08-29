"""Análisis de user journeys (uso educativo).

Traza un recorrido completo del usuario por un sitio (secuencia de páginas,
tiempos e interacciones simuladas) e identifica puntos de abandono con
heurísticas sencillas.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from youber.core.browser import BrowserManager


class JourneyStep(BaseModel):
    """Un paso del journey del usuario.

    Attributes:
        url: URL visitada.
        title: Título de la página.
        time_ms: Tiempo invertido en el paso (navegación + permanencia).
        interactions: Número de interacciones simuladas en el paso.
        status: Código de estado HTTP (si aplica).
        error: Mensaje de error si la carga falló.
    """

    url: str
    title: str | None = None
    time_ms: int = 0
    interactions: int = 0
    status: int | None = None
    error: str | None = None


class JourneyReport(BaseModel):
    """Reporte de un user journey completo.

    Attributes:
        start_url: URL de inicio.
        steps: Pasos del journey en orden.
        total_time_ms: Tiempo total del journey.
        completed: Si todos los pasos se ejecutaron.
    """

    start_url: str
    steps: list[JourneyStep] = Field(default_factory=list)
    total_time_ms: int = 0
    completed: bool = False

    @property
    def duration_s(self) -> float:
        """Duración total en segundos."""
        return round(self.total_time_ms / 1000, 2)


async def trace_user_journey(
    start_url: str,
    path: list[Any],
    dwell_ms: int = 250,
    headless: bool = True,
) -> JourneyReport:
    """Traza un user journey: navega cada paso y mide tiempo e interacciones.

    Args:
        start_url: URL inicial (se visita primero y no cuenta como paso).
        path: Lista de pasos: cadenas (URL) o dicts
            ``{"url": str, "interactions": int}``.
        dwell_ms: Permanencia simulada por paso (además del tiempo de carga).
        headless: Ejecutar el navegador sin interfaz.

    Returns:
        Reporte con los pasos, tiempos y estado de cada uno.
    """
    manager = BrowserManager(headless=headless)
    steps: list[JourneyStep] = []
    total = 0
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)
        await manager.navigate(page, start_url)

        for entry in path:
            url = entry["url"] if isinstance(entry, dict) else entry
            interactions = entry.get("interactions", 0) if isinstance(entry, dict) else 0
            start = time.perf_counter()
            try:
                status = await manager.navigate(page, url)
                await page.wait_for_timeout(dwell_ms)
                title = await manager.get_title(page)
                elapsed = int((time.perf_counter() - start) * 1000)
                steps.append(
                    JourneyStep(
                        url=url,
                        title=title,
                        time_ms=elapsed,
                        interactions=interactions,
                        status=status,
                    )
                )
            except Exception as exc:
                elapsed = int((time.perf_counter() - start) * 1000)
                steps.append(
                    JourneyStep(url=url, time_ms=elapsed, interactions=interactions, error=str(exc))
                )
            total += elapsed

        logger.info(f"Journey trazado: {len(steps)} pasos en {total} ms")
        return JourneyReport(
            start_url=start_url,
            steps=steps,
            total_time_ms=total,
            completed=len(steps) == len(path),
        )
    finally:
        await manager.close()


def identify_dropoff_points(journey: JourneyReport) -> list[dict[str, Any]]:
    """Identifica puntos de abandono potenciales en un journey.

    Heurísticas: pasos con error de carga, pasos con tiempo muy inferior a la
    mediana del journey o pasos sin interacciones.

    Args:
        journey: Reporte del journey.

    Returns:
        Lista de puntos de abandono con el motivo.
    """
    if not journey.steps:
        return []
    times = [step.time_ms for step in journey.steps if step.error is None and step.time_ms > 0]
    median = statistics.median(times) if times else 0
    dropoffs: list[dict[str, Any]] = []
    for index, step in enumerate(journey.steps):
        reasons: list[str] = []
        if step.error:
            reasons.append("error_de_carga")
        elif median and step.time_ms < median * 0.3:
            reasons.append("tiempo_muy_bajo")
        if step.interactions == 0:
            reasons.append("sin_interacciones")
        if reasons:
            dropoffs.append(
                {
                    "step_index": index,
                    "url": step.url,
                    "reason": ", ".join(reasons),
                    "time_ms": step.time_ms,
                    "interactions": step.interactions,
                }
            )
    return dropoffs
