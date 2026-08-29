"""Auditoría con opciones personalizadas — ejemplo educativo de BARF.

Demuestra cómo ejecutar solo reglas concretas, filtrar por nivel de impacto
y obtener recomendaciones automáticas con recursos de aprendizaje.

Uso: python examples/custom_audit.py --url URL [--rules color-contrast label] [--impact serious]
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from youber.accessibility.axe_runner import AxeRunner
from youber.accessibility.recommendations import get_fix_suggestion, get_learning_resource
from youber.accessibility.reporters import (
    generate_json_report,
    generate_markdown_report,
    generate_summary,
)
from youber.console import ensure_utf8_console
from youber.core.browser import BrowserManager

DEFAULT_URL = "https://example.com"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


async def audit(
    url: str,
    rules: list[str] | None = None,
    impact_levels: list[str] | None = None,
    output_dir: Path = REPORTS_DIR,
    headless: bool = True,
) -> Path:
    """Audita una URL con opciones personalizadas y guarda reporte MD + JSON.

    Args:
        url: URL a auditar.
        rules: Reglas axe-core a ejecutar (si no se indica, todas).
        impact_levels: Impactos a conservar (critical, serious, moderate, minor).
        output_dir: Directorio donde guardar los reportes.
        headless: Ejecutar el navegador sin interfaz.

    Returns:
        Ruta del reporte Markdown generado.
    """
    manager = BrowserManager(headless=headless)
    runner = AxeRunner()
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)
        await manager.navigate(page, url)

        options: dict = {}
        if rules:
            options["rules"] = rules
        if impact_levels:
            options["impactLevels"] = impact_levels

        results = await runner.run_axe(page, options)
        print(generate_summary(results))

        if results.violations:
            print("\n💡 Recomendaciones:")
            for violation in results.violations[:5]:
                rule_id = violation.get("id", "")
                element = _first_target(violation) or "?"
                print(f"  - [{rule_id}] {get_fix_suggestion(rule_id, element)}")
                print(f"    📚 Aprende más: {get_learning_resource(rule_id)}")

        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = results.timestamp.strftime("%Y%m%d-%H%M%S")
        md_out = output_dir / f"audit-custom-{_slug(url)}-{stamp}.md"
        json_out = output_dir / f"audit-custom-{_slug(url)}-{stamp}.json"
        md_out.write_text(generate_markdown_report(results), encoding="utf-8")
        json_out.write_text(
            __import__("json").dumps(generate_json_report(results), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n📄 Reportes guardados: {md_out} y {json_out}")
        return md_out
    finally:
        await manager.close()


def _first_target(violation: dict) -> str | None:
    nodes = violation.get("nodes", [])
    if not nodes:
        return None
    target = nodes[0].get("target", [])
    return str(target[0]) if isinstance(target, list) and target else str(target)


def _slug(url: str) -> str:
    """Convierte una URL en un nombre de fichero seguro (sin caracteres inválidos)."""
    raw = url.split("//")[-1].split("/")[0]
    cleaned = "".join(c if c.isalnum() else "-" for c in raw).strip("-").lower()
    return cleaned or "page"


def main() -> None:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(description="Auditoría personalizada (ejemplo BARF)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"URL a auditar (por defecto: {DEFAULT_URL})")
    parser.add_argument("--rules", nargs="*", help="Reglas axe-core a ejecutar")
    parser.add_argument(
        "--impact", nargs="*", choices=["critical", "serious", "moderate", "minor"],
        help="Impactos a conservar",
    )
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR, help="Directorio de reportes")
    parser.add_argument("--headed", action="store_true", help="Mostrar el navegador")
    args = parser.parse_args()
    asyncio.run(audit(args.url, args.rules, args.impact, args.output_dir, headless=not args.headed))


if __name__ == "__main__":
    main()
