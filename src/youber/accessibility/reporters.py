"""Generación de reportes de accesibilidad (Markdown, JSON y resumen)."""

from __future__ import annotations

from typing import Any

from youber.accessibility.axe_runner import AxeResults
from youber.accessibility.wcag import get_wcag_guideline, wcag_quickref_url

IMPACT_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "serious": "🟠",
    "moderate": "🟡",
    "minor": "🔵",
}


def _elements(violation: dict[str, Any]) -> str:
    """Devuelve los selectores de los elementos afectados por una violación."""
    nodes = violation.get("nodes", [])
    targets: list[str] = []
    for node in nodes:
        target = node.get("target", [])
        if isinstance(target, list):
            targets.append(", ".join(str(t) for t in target[:3]))
        else:
            targets.append(str(target))
    return "; ".join(targets[:5]) or "-"


def generate_markdown_report(results: AxeResults) -> str:
    """Genera un reporte Markdown con tabla de violaciones y enlaces WCAG.

    Args:
        results: Resultados de la auditoría.

    Returns:
        Contenido del reporte en Markdown.
    """
    lines = [
        f"# Reporte de accesibilidad — {results.url}",
        "",
        f"- **Fecha:** {results.timestamp:%Y-%m-%d %H:%M:%S} UTC",
        f"- **Violaciones:** {results.total_violations}",
        f"- **Checks superados:** {len(results.passes)}",
        f"- **Incompletos (revisión manual):** {len(results.incomplete)}",
        "",
        "## Violaciones",
        "",
        "| ID | Impacto | Descripción | Elementos afectados | WCAG |",
        "|---|---|---|---|---|",
    ]
    if not results.violations:
        lines.append("| ✅ Sin violaciones detectadas | | | | |")
    for violation in results.violations:
        rule_id = violation.get("id", "-")
        impact = violation.get("impact", "-")
        lines.append(
            f"| `{rule_id}` | {IMPACT_EMOJI.get(impact, '')} {impact} | "
            f"{violation.get('description', '')} | {_elements(violation)} | "
            f"[{get_wcag_guideline(rule_id)}]({wcag_quickref_url(rule_id)}) |"
        )
    lines += [
        "",
        f"*Generado con BARF el {results.timestamp:%Y-%m-%d %H:%M:%S} UTC*",
    ]
    return "\n".join(lines)


def generate_json_report(results: AxeResults) -> dict[str, Any]:
    """Genera la estructura JSON completa para integraciones.

    Añade a cada violación su mapeo WCAG (guía y URL) para que otras
    herramientas puedan consumir el reporte sin conocimiento de axe-core.

    Args:
        results: Resultados de la auditoría.

    Returns:
        Diccionario serializable (JSON) con el reporte completo.
    """
    return {
        "url": results.url,
        "timestamp": results.timestamp.isoformat(),
        "totals": {
            "violations": results.total_violations,
            "passes": len(results.passes),
            "incomplete": len(results.incomplete),
            "inapplicable": len(results.inapplicable),
            "by_impact": results.violations_by_impact(),
        },
        "violations": [
            {
                **violation,
                "wcag": get_wcag_guideline(violation.get("id", "")),
                "wcag_url": wcag_quickref_url(violation.get("id", "")),
            }
            for violation in results.violations
        ],
        "passes": results.passes,
        "incomplete": results.incomplete,
        "inapplicable": results.inapplicable,
    }


def generate_summary(results: AxeResults) -> str:
    """Genera un resumen ejecutivo en texto plano para consola.

    Args:
        results: Resultados de la auditoría.

    Returns:
        Resumen con totales por impacto y principales violaciones.
    """
    by_impact = results.violations_by_impact()
    lines = [
        f"🔎 Auditoría de accesibilidad: {results.url}",
        f"   Violaciones: {results.total_violations}",
    ]
    for level in ("critical", "serious", "moderate", "minor"):
        count = by_impact.get(level, 0)
        if count:
            lines.append(f"   {IMPACT_EMOJI[level]} {level.capitalize()}: {count}")
    if results.violations:
        lines.append("   Principales:")
        for violation in results.violations[:5]:
            impact = violation.get("impact", "-")
            help_text = violation.get("help", "")[:90]
            lines.append(f"     - [{impact}] {violation.get('id', '-')}: {help_text}")
    else:
        lines.append("   ✅ Sin violaciones de accesibilidad detectadas.")
    return "\n".join(lines)
