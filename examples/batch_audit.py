"""Auditoría por lotes de múltiples URLs desde un CSV — ejemplo educativo.

El CSV debe tener cabecera ``url`` y, opcionalmente, ``name``.

Uso: python examples/batch_audit.py --csv urls.csv [--headed]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from youber.accessibility.axe_runner import AxeRunner
from youber.accessibility.reporters import generate_markdown_report, generate_summary
from youber.console import ensure_utf8_console
from youber.core.browser import BrowserManager

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


async def audit_csv(
    csv_path: Path,
    output_dir: Path = REPORTS_DIR,
    headless: bool = True,
) -> Path:
    """Audita todas las URLs del CSV y guarda un reporte por sitio + resumen.

    Las URLs se auditan de forma secuencial y con volumen bajo (uso
    respetuoso). Cada sitio genera su reporte Markdown y al final se escribe
    un ``summary.md`` con el total de violaciones por sitio.

    Args:
        csv_path: Fichero CSV con cabecera ``url[,name]``.
        output_dir: Directorio de salida de los reportes.
        headless: Ejecutar el navegador sin interfaz.

    Returns:
        Ruta del reporte resumen (``summary.md``).
    """
    manager = BrowserManager(headless=headless)
    runner = AxeRunner()
    entries: list[tuple[str, str, int]] = []
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)

        with csv_path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise ValueError(f"El CSV {csv_path} no tiene filas")

        output_dir.mkdir(parents=True, exist_ok=True)
        for row in rows:
            url = row["url"].strip()
            name = row.get("name", "").strip() or url
            try:
                await manager.navigate(page, url)
                results = await runner.run_axe(page)
                out = output_dir / f"{_slug(name)}.md"
                out.write_text(generate_markdown_report(results), encoding="utf-8")
                print(generate_summary(results))
                print(f"📄 Reporte: {out}\n")
                entries.append((name, url, results.total_violations))
            except Exception as exc:
                logger.error(f"Error auditando {url}: {exc}")

        summary = output_dir / "summary.md"
        lines = [
            "# Resumen de auditorías por lotes",
            "",
            f"- **Fecha:** {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC",
            f"- **Sitios auditados:** {len(entries)}",
            "",
            "| Sitio | URL | Violaciones |",
            "|---|---|---|",
        ]
        for name, url, total in entries:
            lines.append(f"| {name} | {url} | {total} |")
        summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"📊 Resumen: {summary}")
        return summary
    finally:
        await manager.close()


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name).strip("-").lower()


def main() -> None:
    ensure_utf8_console()
    parser = argparse.ArgumentParser(description="Auditoría por lotes (ejemplo BARF)")
    parser.add_argument("--csv", type=Path, required=True, help="CSV con cabecera url[,name]")
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR, help="Directorio de reportes")
    parser.add_argument("--headed", action="store_true", help="Mostrar el navegador")
    args = parser.parse_args()
    asyncio.run(audit_csv(args.csv, args.output_dir, headless=not args.headed))


if __name__ == "__main__":
    main()
