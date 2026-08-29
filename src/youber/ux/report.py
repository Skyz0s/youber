"""Generación de reportes de UX (Markdown y JSON)."""

from __future__ import annotations

from typing import Any

from youber.ux.journey import JourneyReport, identify_dropoff_points
from youber.ux.patterns import detect_navigation_pattern


def _recommendations(dropoffs: list[dict[str, Any]]) -> list[str]:
    """Traduce puntos de abandono en recomendaciones accionables."""
    recommendations: list[str] = []
    for dropoff in dropoffs:
        step = dropoff["step_index"] + 1
        reason = dropoff["reason"]
        if "error_de_carga" in reason:
            recommendations.append(
                f"Paso {step} ({dropoff['url']}): error de carga. "
                "Comprueba la disponibilidad y el estado HTTP."
            )
        if "tiempo_muy_bajo" in reason:
            recommendations.append(
                f"Paso {step}: el usuario apenas permanece. "
                "Revisa la relevancia del contenido y el tiempo de carga."
            )
        if "sin_interacciones" in reason:
            recommendations.append(
                f"Paso {step}: sin interacciones. "
                "Añade llamadas a la acción claras y enlaces visibles."
            )
    return recommendations or ["No se detectaron puntos de abandono claros."]


def generate_ux_report(journey_data: JourneyReport) -> str:
    """Genera un reporte UX en Markdown a partir del journey.

    Args:
        journey_data: Reporte del journey.

    Returns:
        Markdown con resumen, tabla de pasos, patrones, abandonos y
        recomendaciones.
    """
    patterns = detect_navigation_pattern([step.url for step in journey_data.steps])
    dropoffs = identify_dropoff_points(journey_data)

    lines = [
        f"# Reporte UX — {journey_data.start_url}",
        "",
        f"- **Pasos:** {len(journey_data.steps)}",
        f"- **Duración total:** {journey_data.duration_s} s",
        f"- **Completado:** {'sí' if journey_data.completed else 'no'}",
        "",
        "## Pasos",
        "",
        "| # | URL | Título | Tiempo (ms) | Interacciones | Estado |",
        "|---|---|---|---|---|---|",
    ]
    for index, step in enumerate(journey_data.steps, start=1):
        status = step.status if step.status is not None else ("error" if step.error else "-")
        lines.append(
            f"| {index} | {step.url} | {step.title or '-'} | {step.time_ms} | "
            f"{step.interactions} | {status} |"
        )
    lines += [
        "",
        "## Patrones de navegación",
        "",
        f"Patrón dominante: **{patterns['dominant'] or 'ninguno'}**",
        "",
    ]
    for name, info in patterns["patterns"].items():
        lines.append(f"- `{name}`: {info['count']} paso(s)")
    lines += [
        "",
        "## Puntos de abandono",
        "",
    ]
    if dropoffs:
        for dropoff in dropoffs:
            lines.append(
                f"- Paso {dropoff['step_index'] + 1} (`{dropoff['url']}`): "
                f"{dropoff['reason']} (tiempo {dropoff['time_ms']} ms, "
                f"{dropoff['interactions']} interacciones)"
            )
    else:
        lines.append("- ✅ Sin puntos de abandono detectados.")
    lines += ["", "## Recomendaciones", ""]
    lines.extend(f"- {recommendation}" for recommendation in _recommendations(dropoffs))
    return "\n".join(lines)


def generate_ux_json(journey_data: JourneyReport) -> dict[str, Any]:
    """Genera la estructura JSON del reporte UX para integraciones.

    Args:
        journey_data: Reporte del journey.

    Returns:
        Diccionario serializable con todo el análisis.
    """
    dropoffs = identify_dropoff_points(journey_data)
    return {
        "start_url": journey_data.start_url,
        "total_time_ms": journey_data.total_time_ms,
        "duration_s": journey_data.duration_s,
        "completed": journey_data.completed,
        "steps": [step.model_dump() for step in journey_data.steps],
        "patterns": detect_navigation_pattern([step.url for step in journey_data.steps]),
        "dropoffs": dropoffs,
        "recommendations": _recommendations(dropoffs),
    }
