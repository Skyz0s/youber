"""Dashboard de métricas de BARF.

Widgets visuales con métricas clave del ecosistema Youber: estadísticas del
catálogo de música, uso, proyectos recientes, estado de subidas, tareas
programadas y actividad diaria. Renderizado en Markdown, HTML o JSON.

Límites éticos (igual que el resto del framework):

- Métricas descriptivas de la propia actividad del usuario; sin manipular
  métricas ajenas ni inflar nada.
- El dashboard muestra el estado real del ecosistema local.
"""

from youber.dashboard.data_sources import (
    list_reports,
    load_music_tracks,
    load_scheduled_jobs,
    load_upload_history,
)
from youber.dashboard.metrics import (
    catalog_stats,
    channel_comparison,
    channel_trends,
    daily_activity,
    engagement_metrics,
    music_usage,
    recent_projects,
    scheduled_tasks,
    top_videos,
    upload_status,
)
from youber.dashboard.models import Widget, WidgetData, WidgetType
from youber.dashboard.registry import WIDGET_REGISTRY, get_definition, list_widgets
from youber.dashboard.renderer import (
    render_dashboard,
    render_dashboard_html,
    render_dashboard_json,
    render_dashboard_markdown,
    render_widget_html,
    render_widget_json,
    render_widget_markdown,
)
from youber.dashboard.widgets import WidgetManager, create_widget, default_widgets

__all__ = [
    "WIDGET_REGISTRY",
    "Widget",
    "WidgetData",
    "WidgetManager",
    "WidgetType",
    "catalog_stats",
    "channel_comparison",
    "channel_trends",
    "create_widget",
    "daily_activity",
    "default_widgets",
    "engagement_metrics",
    "get_definition",
    "list_reports",
    "list_widgets",
    "load_music_tracks",
    "load_scheduled_jobs",
    "load_upload_history",
    "music_usage",
    "recent_projects",
    "render_dashboard",
    "render_dashboard_html",
    "render_dashboard_json",
    "render_dashboard_markdown",
    "render_widget_html",
    "render_widget_json",
    "render_widget_markdown",
    "scheduled_tasks",
    "top_videos",
    "upload_status",
]
