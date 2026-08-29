"""Módulo de estudio de UX de BARF: patrones, heatmaps y user journeys.

Herramientas educativas para analizar cómo los usuarios (simulados) navegan
una interfaz: detección de patrones a partir de URLs, heatmaps de scroll y de
clics, trazado de journeys y generación de reportes Markdown/JSON.
"""

from youber.ux.heatmap import simulate_click_heatmap, simulate_scroll_heatmap
from youber.ux.journey import (
    JourneyReport,
    JourneyStep,
    identify_dropoff_points,
    trace_user_journey,
)
from youber.ux.patterns import analyze_click_flow, detect_navigation_pattern
from youber.ux.report import generate_ux_json, generate_ux_report

__all__ = [
    "JourneyReport",
    "JourneyStep",
    "analyze_click_flow",
    "detect_navigation_pattern",
    "generate_ux_json",
    "generate_ux_report",
    "identify_dropoff_points",
    "simulate_click_heatmap",
    "simulate_scroll_heatmap",
    "trace_user_journey",
]
