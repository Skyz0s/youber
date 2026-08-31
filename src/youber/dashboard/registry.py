"""Registro de widgets disponibles del dashboard de BARF.

Asocia cada :class:`~youber.dashboard.models.WidgetType` con su función de
métricas, título por defecto, descripción y qué fuentes de datos necesita.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from youber.dashboard import metrics
from youber.dashboard.models import WidgetType

# Función de métricas: recibe los datos ya cargados y devuelve un dict.
MetricFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class WidgetDefinition:
    """Definición de un widget disponible en el dashboard."""

    type: WidgetType
    title: str
    description: str
    metric: MetricFn
    sources: tuple[str, ...]  # nombres de los parámetros que la métrica espera


# Registro canónico: un widget por tipo.
WIDGET_REGISTRY: dict[WidgetType, WidgetDefinition] = {
    WidgetType.CATALOG_STATS: WidgetDefinition(
        type=WidgetType.CATALOG_STATS,
        title="Estadísticas del catálogo de música",
        description="Pistas totales, duración, favoritas, moods y géneros",
        metric=metrics.catalog_stats,
        sources=("tracks",),
    ),
    WidgetType.MUSIC_USAGE: WidgetDefinition(
        type=WidgetType.MUSIC_USAGE,
        title="Uso del catálogo de música",
        description="Pistas más usadas y uso total",
        metric=metrics.music_usage,
        sources=("tracks",),
    ),
    WidgetType.RECENT_PROJECTS: WidgetDefinition(
        type=WidgetType.RECENT_PROJECTS,
        title="Proyectos y reportes recientes",
        description="Últimos ficheros generados (JSON/MD/CSV)",
        metric=metrics.recent_projects,
        sources=("reports",),
    ),
    WidgetType.UPLOAD_STATUS: WidgetDefinition(
        type=WidgetType.UPLOAD_STATUS,
        title="Estado de subidas a YouTube",
        description="Historial y estado de las subidas",
        metric=metrics.upload_status,
        sources=("history",),
    ),
    WidgetType.ENGAGEMENT_METRICS: WidgetDefinition(
        type=WidgetType.ENGAGEMENT_METRICS,
        title="Métricas de engagement",
        description="Vistas/likes medios de los vídeos analizados",
        metric=metrics.engagement_metrics,
        sources=("videos",),
    ),
    WidgetType.SCHEDULED_TASKS: WidgetDefinition(
        type=WidgetType.SCHEDULED_TASKS,
        title="Tareas programadas",
        description="Trabajos del scheduler por tipo y cadencia",
        metric=metrics.scheduled_tasks,
        sources=("jobs",),
    ),
    WidgetType.CHANNEL_TRENDS: WidgetDefinition(
        type=WidgetType.CHANNEL_TRENDS,
        title="Tendencias del canal",
        description="Vídeos, vistas y suscriptores de un canal",
        metric=metrics.channel_trends,
        sources=("channel",),
    ),
    WidgetType.CHANNEL_COMPARISON: WidgetDefinition(
        type=WidgetType.CHANNEL_COMPARISON,
        title="Comparación de canales",
        description="Compara varios canales lado a lado",
        metric=metrics.channel_comparison,
        sources=("channels",),
    ),
    WidgetType.DAILY_ACTIVITY: WidgetDefinition(
        type=WidgetType.DAILY_ACTIVITY,
        title="Actividad diaria",
        description="Reportes generados por día",
        metric=metrics.daily_activity,
        sources=("reports",),
    ),
    WidgetType.TOP_VIDEOS: WidgetDefinition(
        type=WidgetType.TOP_VIDEOS,
        title="Vídeos destacados",
        description="Los vídeos con más visualizaciones",
        metric=metrics.top_videos,
        sources=("videos",),
    ),
}


def list_widgets() -> list[dict[str, Any]]:
    """Devuelve la lista de widgets disponibles (para la CLI)."""
    return [
        {
            "type": definition.type.value,
            "title": definition.title,
            "description": definition.description,
            "sources": list(definition.sources),
        }
        for definition in WIDGET_REGISTRY.values()
    ]


def get_definition(widget_type: WidgetType) -> WidgetDefinition:
    """Devuelve la definición de un widget (lanza ``KeyError`` si no existe)."""
    return WIDGET_REGISTRY[widget_type]
