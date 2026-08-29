"""Simulación de dispositivos (viewport, user agent, táctil, DPR).

Define descriptores de dispositivo equivalentes a los que incluye Playwright
y los aplica sobre una página existente mediante CDP (``Emulation`` y
``Network``), de forma equivalente a crear un contexto con el descriptor
completo. Sirve para estudiar cómo cambia el diseño y el comportamiento según
el dispositivo.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

DEVICES: dict[str, dict[str, Any]] = {
    "iPhone": {
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "viewport": {"width": 390, "height": 664},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
    "Pixel": {
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/108.0.0.0 Mobile Safari/537.36"
        ),
        "viewport": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True,
    },
    "iPad": {
        "user_agent": (
            "Mozilla/5.0 (iPad; CPU OS 13_2_3 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.4 "
            "Mobile/15E148 Safari/604.1"
        ),
        "viewport": {"width": 810, "height": 1080},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
    "Desktop": {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1280, "height": 720},
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
    },
}


def get_device_options() -> dict[str, dict[str, Any]]:
    """Devuelve los dispositivos disponibles con sus especificaciones.

    Returns:
        Diccionario ``{alias: especificación del dispositivo}``.
    """
    return {name: dict(spec) for name, spec in DEVICES.items()}


async def simulate_device(page: Any, device_name: str) -> dict[str, Any]:
    """Simula un dispositivo en la página (viewport, UA, táctil, DPR).

    Args:
        page: Página de Playwright.
        device_name: ``iPhone``, ``Pixel``, ``iPad`` o ``Desktop``.

    Returns:
        Especificación del dispositivo aplicado.

    Raises:
        ValueError: si el dispositivo no existe.
    """
    spec = DEVICES.get(device_name)
    if spec is None:
        raise ValueError(
            f"Dispositivo desconocido: {device_name}. Usa get_device_options()"
        )
    viewport = spec["viewport"]

    await page.set_viewport_size(viewport)

    cdp = await page.context.new_cdp_session(page)
    await cdp.send(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": viewport["width"],
            "height": viewport["height"],
            "deviceScaleFactor": spec.get("device_scale_factor", 1),
            "mobile": spec.get("is_mobile", False),
        },
    )
    await cdp.send(
        "Network.setUserAgentOverride",
        {"userAgent": spec["user_agent"]},
    )
    await cdp.send(
        "Emulation.setTouchEmulationEnabled",
        {"enabled": spec.get("has_touch", False)},
    )

    logger.info(f"Dispositivo simulado: {device_name} — viewport {viewport}")
    return dict(spec)
