"""Simulación de heatmaps de scroll y de clics (uso educativo).

Genera heatmaps a partir de comportamiento simulado: tiempo de permanencia
por zona de la página (scroll) y agregación de interacciones en cuadrícula
(clics). El objetivo es enseñar a interpretar visualmente la atención del
usuario.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any


async def simulate_scroll_heatmap(
    page: Any,
    dwell_ms: int = 400,
    seed: int = 7,
) -> dict[str, Any]:
    """Simula un scroll natural por la página y mide el tiempo en viewport.

    Recorre la página por bandas de una altura de viewport, con pausas de
    lectura simuladas: la primera banda recibe más atención y el resto un
    pequeño factor aleatorio con semilla fija (resultados reproducibles).

    Args:
        page: Página de Playwright.
        dwell_ms: Pausa base por banda.
        seed: Semilla para la variación de pausas.

    Returns:
        Zonas (banda, rango y, tiempo e intensidad) y métricas de la página.
    """
    rng = random.Random(seed)
    dims = await page.evaluate(
        "() => ({ pageHeight: document.documentElement.scrollHeight, viewportHeight: window.innerHeight })"
    )
    page_height = int(dims["pageHeight"])
    viewport_height = int(dims["viewportHeight"])
    if viewport_height <= 0 or page_height <= 0:
        return {
            "zones": [],
            "total_time_ms": 0,
            "viewport_height": viewport_height,
            "page_height": page_height,
        }

    bands = max(1, math.ceil(page_height / viewport_height))
    time_per_band: dict[int, float] = {}

    for band in range(bands):
        await page.evaluate(f"window.scrollTo(0, {band * viewport_height})")
        # La primera banda (contenido inicial) recibe más tiempo de lectura.
        factor = 2.0 if band == 0 else 0.8 + rng.random() * 0.4
        start = time.perf_counter()
        await page.wait_for_timeout(int(dwell_ms * factor))
        time_per_band[band] = (time.perf_counter() - start) * 1000

    total = sum(time_per_band.values())
    zones = [
        {
            "band": band,
            "y_start": band * viewport_height,
            "y_end": min((band + 1) * viewport_height, page_height),
            "time_ms": round(seconds, 1),
            "intensity": round(seconds / total, 3) if total else 0,
        }
        for band, seconds in sorted(time_per_band.items())
    ]
    return {
        "viewport_height": viewport_height,
        "page_height": page_height,
        "total_time_ms": round(total, 1),
        "zones": zones,
    }


async def simulate_click_heatmap(
    page: Any,
    interactions: list[dict[str, Any]],
    cell_size: int = 100,
) -> dict[str, Any]:
    """Agrega interacciones (clics) en una cuadrícula para simular un heatmap.

    Cada interacción puede ser ``{"x": int, "y": int}`` o
    ``{"selector": str}`` (se resuelve al centro del elemento).

    Args:
        page: Página de Playwright (para resolver selectores).
        interactions: Lista de clics simulados.
        cell_size: Tamaño de celda en píxeles.

    Returns:
        Zonas calientes ordenadas por número de interacciones.
    """
    points: list[dict[str, Any]] = []
    for interaction in interactions:
        if "selector" in interaction:
            box = await page.locator(interaction["selector"]).first.bounding_box()
            if box is None:
                continue
            points.append(
                {
                    "x": box["x"] + box["width"] / 2,
                    "y": box["y"] + box["height"] / 2,
                    "selector": interaction["selector"],
                }
            )
        else:
            points.append({"x": interaction.get("x", 0), "y": interaction.get("y", 0)})

    grid: dict[tuple[int, int], int] = {}
    for point in points:
        key = (int(point["x"] // cell_size), int(point["y"] // cell_size))
        grid[key] = grid.get(key, 0) + 1

    hotspots = sorted(
        (
            {
                "cell_x": key[0],
                "cell_y": key[1],
                "x_center": int((key[0] + 0.5) * cell_size),
                "y_center": int((key[1] + 0.5) * cell_size),
                "clicks": count,
            }
            for key, count in grid.items()
        ),
        key=lambda hotspot: -hotspot["clicks"],
    )
    return {
        "cell_size": cell_size,
        "total_interactions": len(points),
        "grid_cells": len(grid),
        "hotspots": hotspots[:10],
    }
