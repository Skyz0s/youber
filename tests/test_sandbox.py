"""Tests del módulo sandbox (geolocalización, red y dispositivos).

Nota: las funciones importadas que empiezan por ``test_`` se importan con
alias para que pytest no las recolecte como tests propios.
"""

from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError

from youber.core.browser import BrowserManager
from youber.sandbox.device import get_device_options, simulate_device
from youber.sandbox.geolocation import (
    get_region_options,
    simulate_location,
)
from youber.sandbox.geolocation import (
    test_localization as probe_localization,
)
from youber.sandbox.network import (
    get_speed_options,
    simulate_network,
)
from youber.sandbox.network import (
    test_performance as measure_performance,
)

ACCESSIBLE_URL = (Path(__file__).parent / "fixtures" / "accessible.html").resolve().as_uri()
EXAMPLE_URL = "https://example.com"


@pytest.fixture
async def page():
    manager = BrowserManager(headless=True)
    await manager.launch()
    context = await manager.new_context()
    p = await manager.new_page(context)
    yield p
    await manager.close()


def test_region_options():
    options = get_region_options()
    assert {"ES", "US", "UK", "JP", "BR"} <= set(options)
    assert options["ES"]["timezone"] == "Europe/Madrid"


async def test_simulate_location(page):
    info = await simulate_location(page, "ES")
    assert info["code"] == "ES"
    await page.goto(ACCESSIBLE_URL)
    assert await page.evaluate("navigator.language") == "es-ES"
    assert (
        await page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
        == "Europe/Madrid"
    )


async def test_simulate_location_unknown_raises(page):
    with pytest.raises(ValueError):
        await simulate_location(page, "XX")


async def test_localization_probe(page):
    signals = await probe_localization(page, ACCESSIBLE_URL, "JP")
    assert signals["timezone"] == "Asia/Tokyo"
    assert signals["navigator_language"] == "ja-JP"
    assert signals["title"] == "Página accesible de prueba"


def test_speed_options():
    options = get_speed_options()
    assert {"4g", "3g", "2g", "slow-3g", "offline"} <= set(options)


async def test_simulate_network_offline_blocks(page):
    await simulate_network(page, "offline")
    with pytest.raises(PlaywrightError):
        await page.goto(EXAMPLE_URL, timeout=8000)


async def test_network_performance(page):
    results = await measure_performance(page, EXAMPLE_URL, ["4g"])
    assert len(results) == 1
    assert results[0]["speed"] == "4g"
    assert results[0]["load_time_ms"] > 0


def test_device_options():
    options = get_device_options()
    assert {"iPhone", "Pixel", "iPad", "Desktop"} <= set(options)


async def test_simulate_device_iphone(page):
    spec = await simulate_device(page, "iPhone")
    assert spec["viewport"]["width"] < 500
    await page.goto(ACCESSIBLE_URL)
    assert "iPhone" in await page.evaluate("navigator.userAgent")
    assert await page.evaluate("'ontouchstart' in window") is True
    assert await page.evaluate("[innerWidth, innerHeight]") == [
        spec["viewport"]["width"],
        spec["viewport"]["height"],
    ]


async def test_simulate_device_unknown_raises(page):
    with pytest.raises(ValueError):
        await simulate_device(page, "Nokia")
