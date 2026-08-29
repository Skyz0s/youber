"""Auditoría de accesibilidad de github.com — ejemplo educativo de BARF.

Uso: python examples/audit_github.py [--url URL] [--headed] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from youber.accessibility.axe_runner import AxeRunner
from youber.accessibility.reporters import generate_markdown_report, generate_summary
from youber.console import ensure_utf8_console
from youber.core.browser import BrowserManager

DEFAULT_URL = "https://github.com"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


async def audit(url: str, output_dir: Path = REPORTS_DIR, headless: bool = True) -> Path:
    """Audita la accesibilidad de una URL y guarda el reporte Markdown.

    Args:
        url: URL a auditar.
        output_dir: Directorio donde guardar el reporte.
        headless: Ejecutar el navegador sin interfaz.

    Returns:
        Ruta del reporte generado.
    """
    manager = BrowserManager(headless=headless)
    runner = AxeRunner()
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)
        await manager.navigate(page, url)
        results = await runner.run_axe(page)
        print(generate_summary(results))
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"audit-{_slug(url)}-{results.timestamp:%Y%m%d-%H%M%S}.md"
        out.write_text(generate_markdown_report(results), encoding="utf-8")
        print(f"\n📄 Reporte guardado: {out}")
        return out
    finally:
        await manager.close()


def _slug(url: str) -> str:
    """Convierte una URL en un nombre de fichero seguro (sin caracteres inválidos)."""
    raw = url.split("//")[-1].split("/")[0]
    cleaned = "".join(c if c.isalnum() else "-" for c in raw).strip("-").lower()
    return cleaned or "page"


def main() -> None:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(description="Auditoría de accesibilidad (ejemplo BARF)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"URL a auditar (por defecto: {DEFAULT_URL})")
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR, help="Directorio de reportes")
    parser.add_argument("--headed", action="store_true", help="Mostrar el navegador")
    args = parser.parse_args()
    asyncio.run(audit(args.url, args.output_dir, headless=not args.headed))


if __name__ == "__main__":
    main()
