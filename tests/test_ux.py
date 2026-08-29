"""Tests del módulo de estudio UX (patrones, heatmaps, journeys y reportes)."""

from pathlib import Path

import pytest

from youber.core.browser import BrowserManager
from youber.ux.heatmap import simulate_click_heatmap, simulate_scroll_heatmap
from youber.ux.journey import (
    JourneyReport,
    JourneyStep,
    identify_dropoff_points,
    trace_user_journey,
)
from youber.ux.patterns import analyze_click_flow, detect_navigation_pattern
from youber.ux.report import generate_ux_json, generate_ux_report

FIXTURES = Path(__file__).parent / "fixtures" / "site"
INDEX_URL = (FIXTURES / "index.html").resolve().as_uri()
ABOUT_URL = (FIXTURES / "about.html").resolve().as_uri()
CONTACT_URL = (FIXTURES / "contact.html").resolve().as_uri()


@pytest.fixture
async def page():
    manager = BrowserManager(headless=True)
    await manager.launch()
    context = await manager.new_context()
    p = await manager.new_page(context)
    yield p
    await manager.close()


def test_detect_search_pattern():
    history = [
        {"url": "https://site.test/home"},
        {"url": "https://site.test/search?q=playwright"},
        {"url": "https://site.test/watch/123"},
    ]
    result = detect_navigation_pattern(history)
    assert "search" in result["patterns"]
    assert result["dominant"] == "search"
    assert result["total_steps"] == 3


def test_detect_checkout_and_breadcrumb():
    history = [
        {"url": "https://shop.test/"},
        {"url": "https://shop.test/category/ropa"},
        {"url": "https://shop.test/category/ropa/camisas"},
        {"url": "https://shop.test/cart"},
    ]
    result = detect_navigation_pattern(history)
    assert "checkout" in result["patterns"]
    assert "breadcrumb" in result["patterns"]


async def test_analyze_click_flow(page):
    await page.goto(INDEX_URL)
    result = await analyze_click_flow(page, ["a"], sessions=4, clicks_per_session=2)
    assert result["sessions"] == 4
    assert result["top_sequences"]
    assert result["element_stats"]["a"]["found"] > 0


async def test_simulate_scroll_heatmap(page):
    await page.goto(ABOUT_URL)
    result = await simulate_scroll_heatmap(page)
    assert result["zones"]
    assert result["total_time_ms"] > 0
    assert abs(sum(zone["intensity"] for zone in result["zones"]) - 1.0) < 0.01


async def test_simulate_click_heatmap(page):
    await page.goto(INDEX_URL)
    result = await simulate_click_heatmap(
        page,
        [{"selector": "h1"}, {"selector": "a"}, {"x": 10, "y": 10}],
    )
    assert result["total_interactions"] >= 2
    assert result["hotspots"]


async def test_trace_user_journey():
    report = await trace_user_journey(INDEX_URL, [ABOUT_URL, CONTACT_URL], dwell_ms=50)
    assert isinstance(report, JourneyReport)
    assert report.completed
    assert len(report.steps) == 2
    assert report.steps[0].title == "Sobre nosotros"
    assert report.total_time_ms > 0


def test_identify_dropoff_points():
    report = JourneyReport(
        start_url="https://x.test/",
        steps=[
            JourneyStep(url="https://x.test/a", time_ms=500, interactions=2),
            JourneyStep(url="https://x.test/b", time_ms=20, interactions=0),
            JourneyStep(url="https://x.test/c", time_ms=600, interactions=1),
        ],
        total_time_ms=1120,
        completed=True,
    )
    dropoffs = identify_dropoff_points(report)
    assert dropoffs
    assert dropoffs[0]["step_index"] == 1
    assert "sin_interacciones" in dropoffs[0]["reason"]


def test_generate_ux_report():
    report = JourneyReport(
        start_url="https://x.test/",
        steps=[JourneyStep(url="https://x.test/search?q=x", time_ms=500, interactions=2)],
        total_time_ms=500,
        completed=True,
    )
    markdown = generate_ux_report(report)
    assert "# Reporte UX" in markdown
    assert "Patrón dominante" in markdown
    assert "Puntos de abandono" in markdown

    data = generate_ux_json(report)
    assert data["steps"][0]["url"].endswith("q=x")
    assert "recommendations" in data
