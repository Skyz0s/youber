"""Tests del módulo de accesibilidad (axe_runner, reporters, wcag, recomendaciones)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from youber.accessibility.axe_runner import AxeResults, AxeRunner
from youber.accessibility.recommendations import get_fix_suggestion, get_learning_resource
from youber.accessibility.reporters import (
    generate_json_report,
    generate_markdown_report,
    generate_summary,
)
from youber.accessibility.wcag import get_wcag_guideline, wcag_map, wcag_quickref_url
from youber.core.browser import BrowserManager

ACCESSIBLE_URL = (Path(__file__).parent / "fixtures" / "accessible.html").resolve().as_uri()


@pytest.fixture
async def page():
    manager = BrowserManager(headless=True)
    await manager.launch()
    context = await manager.new_context()
    p = await manager.new_page(context)
    await manager.navigate(p, ACCESSIBLE_URL)
    yield p
    await manager.close()


async def test_run_axe_no_violations(page):
    runner = AxeRunner()
    results = await runner.run_axe(page)
    assert isinstance(results, AxeResults)
    assert results.total_violations == 0
    assert results.passes, "debe haber checks superados"
    assert results.url == ACCESSIBLE_URL
    assert results.timestamp.tzinfo is not None


async def test_run_axe_rules_filter(page):
    runner = AxeRunner()
    results = await runner.run_axe(page, {"rules": ["color-contrast"]})
    for violation in results.violations:
        assert violation["id"] == "color-contrast"


async def test_run_axe_impact_filter(page):
    runner = AxeRunner()
    results = await runner.run_axe(page, {"impactLevels": ["critical"]})
    assert all(v.get("impact") == "critical" for v in results.violations)


def test_impact_filter_private():
    items = [{"impact": "serious"}, {"impact": "critical"}, {"impact": "moderate"}]
    filtered = AxeRunner._filter_impact(items, ["critical", "serious"])
    assert [i["impact"] for i in filtered] == ["serious", "critical"]


async def test_axe_cache(page):
    runner = AxeRunner()
    r1 = await runner.run_axe(page)
    r2 = await runner.run_axe(page)
    assert r2 is r1, "la caché debe devolver el mismo objeto"
    runner.clear_cache()
    r3 = await runner.run_axe(page)
    assert r3 is not r1


def test_wcag_map():
    assert wcag_map["color-contrast"].sc == "1.4.3"
    assert get_wcag_guideline("color-contrast") == "WCAG 2.1 - 1.4.3 - Contrast (Minimum)"
    assert "revisar" in get_wcag_guideline("regla-inventada")
    assert wcag_quickref_url("target-size") == "https://www.w3.org/WAI/WCAG22/quickref/#2.5.8"


def test_recommendations():
    suggestion = get_fix_suggestion("color-contrast", "#boton")
    assert "#boton" in suggestion
    fallback = get_fix_suggestion("regla-inventada", "x")
    assert "regla-inventada" in fallback
    assert get_learning_resource("color-contrast").startswith("http")
    assert get_learning_resource("regla-inventada").startswith("http")


def _fake_results() -> AxeResults:
    return AxeResults(
        url="https://x.test",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        violations=[
            {
                "id": "color-contrast",
                "impact": "serious",
                "description": "Elementos con bajo contraste",
                "help": "El contraste es insuficiente",
                "nodes": [{"target": ["#boton"]}],
            }
        ],
        passes=[{"id": "html-has-lang"}],
        incomplete=[],
        inapplicable=[],
    )


def test_markdown_report():
    md = generate_markdown_report(_fake_results())
    assert "# Reporte de accesibilidad" in md
    assert "`color-contrast`" in md
    assert "1.4.3" in md
    assert "#boton" in md


def test_json_report():
    data = generate_json_report(_fake_results())
    assert data["totals"]["violations"] == 1
    assert data["violations"][0]["wcag"] == "WCAG 2.1 - 1.4.3 - Contrast (Minimum)"
    assert data["totals"]["by_impact"]["serious"] == 1


def test_summary():
    summary = generate_summary(_fake_results())
    assert "Violaciones: 1" in summary
    assert "Serious: 1" in summary
