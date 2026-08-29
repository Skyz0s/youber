"""Módulo de accesibilidad de BARF: auditoría WCAG con axe-core.

Incluye ejecución de auditorías (``AxeRunner``), generación de reportes
(Markdown, JSON y resumen), mapeo de reglas a criterios WCAG 2.1/2.2 y
recomendaciones automáticas con recursos educativos.
"""

from youber.accessibility.axe_runner import AxeResults, AxeRunner
from youber.accessibility.recommendations import get_fix_suggestion, get_learning_resource
from youber.accessibility.reporters import (
    generate_json_report,
    generate_markdown_report,
    generate_summary,
)
from youber.accessibility.wcag import get_wcag_guideline, wcag_map, wcag_quickref_url

__all__ = [
    "AxeResults",
    "AxeRunner",
    "generate_json_report",
    "generate_markdown_report",
    "generate_summary",
    "get_fix_suggestion",
    "get_learning_resource",
    "get_wcag_guideline",
    "wcag_map",
    "wcag_quickref_url",
]
