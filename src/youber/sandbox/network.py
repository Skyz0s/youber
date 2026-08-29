"""Simulación de condiciones de red (latencia, ancho de banda, offline).

Usa CDP (``Network.emulateNetworkConditions``) para emular perfiles de
conexión similares a los de Chrome DevTools. Permite medir tiempos de carga
de una URL en distintas condiciones y estudiar el rendimiento percibido.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

# Perfiles de referencia (valores similares a Chrome DevTools).
NETWORK_SPEEDS: dict[str, dict[str, Any]] = {
    "4g": {
        "offline": False,
        "latency": 20,
        "downloadThroughput": int(4 * 1024 * 1024 / 8),
        "uploadThroughput": int(3 * 1024 * 1024 / 8),
    },
    "3g": {
        "offline": False,
        "latency": 100,
        "downloadThroughput": int(1.6 * 1024 * 1024 / 8),
        "uploadThroughput": int(768 * 1024 / 8),
    },
    "2g": {
        "offline": False,
        "latency": 300,
        "downloadThroughput": int(250 * 1024 / 8),
        "uploadThroughput": int(50 * 1024 / 8),
    },
    "slow-3g": {
        "offline": False,
        "latency": 400,
        "downloadThroughput": int(400 * 1024 / 8),
        "uploadThroughput": int(400 * 1024 / 8),
    },
    "offline": {
        "offline": True,
        "latency": 0,
        "downloadThroughput": 0,
        "uploadThroughput": 0,
    },
}

# Perfil de restauración: red sin limitaciones.
_NORMAL_NETWORK: dict[str, Any] = {
    "offline": False,
    "latency": 0,
    "downloadThroughput": -1,
    "uploadThroughput": -1,
}


def get_speed_options() -> dict[str, dict[str, Any]]:
    """Devuelve los perfiles de red disponibles.

    Returns:
        Diccionario ``{nombre: especificación CDP}``.
    """
    return {name: dict(spec) for name, spec in NETWORK_SPEEDS.items()}


async def _apply_network(page: Any, spec: dict[str, Any]) -> None:
    cdp = await page.context.new_cdp_session(page)
    await cdp.send("Network.enable")
    await cdp.send("Network.emulateNetworkConditions", spec)


async def simulate_network(page: Any, speed: str) -> dict[str, Any]:
    """Simula una condición de red concreta en la página.

    Args:
        page: Página de Playwright.
        speed: Perfil de red: ``4g``, ``3g``, ``2g``, ``slow-3g`` u ``offline``.

    Returns:
        Especificación del perfil aplicado.

    Raises:
        ValueError: si el perfil no existe.
    """
    spec = NETWORK_SPEEDS.get(speed.lower())
    if spec is None:
        raise ValueError(f"Perfil de red desconocido: {speed}. Usa get_speed_options()")
    await _apply_network(page, spec)
    logger.info(f"Red simulada: {speed.lower()} (latencia {spec['latency']} ms)")
    return dict(spec)


async def test_performance(page: Any, url: str, speeds: list[str]) -> list[dict[str, Any]]:
    """Mide tiempos de carga de una URL en distintas condiciones de red.

    Para cada perfil navega a la URL y mide el tiempo total y las métricas de
    Navigation Timing API. Al terminar restablece la red sin limitaciones.

    Args:
        page: Página de Playwright.
        url: URL a medir.
        speeds: Lista de perfiles de red a probar.

    Returns:
        Lista de resultados por perfil (tiempo de carga y métricas del
        navegador, o ``error`` si la carga falló).
    """
    results: list[dict[str, Any]] = []
    for speed in speeds:
        await simulate_network(page, speed)
        start = time.perf_counter()
        try:
            await page.goto(url, wait_until="load")
            elapsed_ms = (time.perf_counter() - start) * 1000
            nav = await page.evaluate(
                """() => {
                    const n = performance.getEntriesByType('navigation')[0];
                    return n ? {
                        duration_ms: n.duration,
                        dom_content_loaded_ms: n.domContentLoadedEventEnd,
                        load_event_ms: n.loadEventEnd,
                    } : null;
                }"""
            )
            results.append(
                {"speed": speed, "load_time_ms": round(elapsed_ms, 1), **nav}
            )
            logger.info(f"{speed}: carga en {elapsed_ms:.0f} ms")
        except Exception as exc:  # p. ej. offline -> navegación imposible
            results.append({"speed": speed, "error": str(exc)})
            logger.warning(f"{speed}: error de carga ({exc})")
    await _apply_network(page, _NORMAL_NETWORK)
    return results
