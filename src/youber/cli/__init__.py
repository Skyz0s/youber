"""Interfaz de línea de comandos de BARF.

Entry points definidos en ``pyproject.toml``:

- ``youber-audit`` → auditoría de accesibilidad rápida
- ``youber-sandbox`` → demo de simulaciones (región, dispositivo, red)
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from loguru import logger

from youber.accessibility.axe_runner import AxeRunner
from youber.accessibility.reporters import generate_markdown_report, generate_summary
from youber.console import ensure_utf8_console
from youber.core.browser import BrowserManager
from youber.sandbox.device import get_device_options, simulate_device
from youber.sandbox.geolocation import get_region_options, simulate_location
from youber.sandbox.network import get_speed_options, simulate_network

REPORTS_DIR = Path("reports")


def audit() -> None:
    """CLI ``youber-audit``: auditoría de accesibilidad rápida de una URL."""
    ensure_utf8_console()
    parser = argparse.ArgumentParser(
        description="BARF: auditoría de accesibilidad rápida (uso educativo)"
    )
    parser.add_argument("url", help="URL a auditar")
    parser.add_argument(
        "--rules", nargs="*", default=None, help="Reglas axe-core a ejecutar"
    )
    parser.add_argument(
        "--impact",
        nargs="*",
        choices=["critical", "serious", "moderate", "minor"],
        default=None,
        help="Filtrar violaciones por nivel de impacto",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Fichero Markdown de salida (por defecto reports/audit-<host>-<ts>.md)",
    )
    parser.add_argument("--headed", action="store_true", help="Mostrar el navegador")
    args = parser.parse_args()

    asyncio.run(_run_audit(args))


async def _run_audit(args: argparse.Namespace) -> None:
    manager = BrowserManager(headless=not args.headed)
    runner = AxeRunner()
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)
        await manager.navigate(page, args.url)

        options: dict = {}
        if args.rules:
            options["rules"] = args.rules
        if args.impact:
            options["impactLevels"] = args.impact

        results = await runner.run_axe(page, options)
        print(generate_summary(results))

        out = Path(
            args.output
            or REPORTS_DIR / f"audit-{_slug(args.url)}-{results.timestamp:%Y%m%d-%H%M%S}.md"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(generate_markdown_report(results), encoding="utf-8")
        logger.info(f"Reporte guardado en {out}")
    finally:
        await manager.close()


def sandbox() -> None:
    """CLI ``youber-sandbox``: demo de simulaciones (región, dispositivo, red)."""
    ensure_utf8_console()
    parser = argparse.ArgumentParser(
        description="BARF: sandbox de simulaciones (uso educativo)"
    )
    parser.add_argument("--url", default="https://example.com", help="URL de destino")
    parser.add_argument(
        "--region",
        choices=list(get_region_options().keys()),
        help="Región a simular (ES, US, UK, JP, BR...)",
    )
    parser.add_argument(
        "--device",
        choices=list(get_device_options().keys()),
        help="Dispositivo a simular (iPhone, Pixel, iPad, Desktop)",
    )
    parser.add_argument(
        "--speed",
        choices=list(get_speed_options().keys()),
        help="Perfil de red (4g, 3g, 2g, slow-3g, offline)",
    )
    parser.add_argument("--headed", action="store_true", help="Mostrar el navegador")
    args = parser.parse_args()

    asyncio.run(_run_sandbox(args))


async def _run_sandbox(args: argparse.Namespace) -> None:
    manager = BrowserManager(headless=not args.headed)
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)

        if args.region:
            region = await simulate_location(page, args.region)
            print(f"📍 Región: {region['country']} ({region['code']})")
        if args.device:
            spec = await simulate_device(page, args.device)
            print(f"📱 Dispositivo: {args.device} — viewport {spec['viewport']}")
        if args.speed:
            spec = await simulate_network(page, args.speed)
            print(
                f"🌐 Red: {args.speed} — latencia {spec['latency']} ms, "
                f"offline={spec['offline']}"
            )

        try:
            await manager.navigate(page, args.url)
        except Exception as exc:  # p. ej. offline: la navegación falla
            print(f"⚠️ Navegación fallida ({exc})")

        signals = await page.evaluate(
            """() => ({
                lang: document.documentElement.lang || null,
                navigator_language: navigator.language,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                viewport: [innerWidth, innerHeight],
                touch: 'ontouchstart' in window,
                title: document.title,
            })"""
        )
        print("\nSeñales detectadas por la web:")
        for key, value in signals.items():
            print(f"  {key}: {value}")
    finally:
        await manager.close()


def _slug(url: str) -> str:
    """Convierte una URL en un nombre de fichero seguro."""
    return (
        url.replace("https://", "")
        .replace("http://", "")
        .replace("/", "_")
        .replace(".", "-")
    )
