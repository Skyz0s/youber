"""Herramientas MCP de simulación (sandbox): geolocalización, red y dispositivos."""

from __future__ import annotations

from typing import Any

from loguru import logger

from youber.sandbox.device import simulate_device
from youber.sandbox.geolocation import test_localization
from youber.sandbox.network import simulate_network


async def geolocation_probe(session: object, url: str, region: str) -> dict[str, Any]:
    """Abre la URL con la región simulada y extrae señales de localización.

    Returns:
        Señales (lang, navigator_language, timezone, título) + ``page_id``.
    """
    pid, page, _ = await session.open_page(url)  # type: ignore[attr-defined]
    signals = await test_localization(page, url, region)
    signals["page_id"] = pid
    logger.info(f"geolocation_probe: {region} -> {signals['navigator_language']} / {signals['timezone']}")
    return signals


async def network_probe(session: object, url: str, speed: str) -> dict[str, Any]:
    """Abre la URL con un perfil de red simulado y devuelve la especificación.

    Returns:
        Especificación del perfil aplicado + ``page_id``.
    """
    pid, page, _ = await session.open_page(url)  # type: ignore[attr-defined]
    spec = await simulate_network(page, speed)
    spec["page_id"] = pid
    logger.info(f"network_probe: {speed} aplicado a {url}")
    return spec


async def device_probe(session: object, url: str, device_name: str) -> dict[str, Any]:
    """Abre la URL con un dispositivo simulado y devuelve la especificación.

    Returns:
        Especificación del dispositivo aplicado + ``page_id``.
    """
    pid, page, _ = await session.open_page(url)  # type: ignore[attr-defined]
    spec = await simulate_device(page, device_name)
    spec["page_id"] = pid
    logger.info(f"device_probe: {device_name} aplicado a {url}")
    return spec
