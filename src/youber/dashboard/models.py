"""Modelos del dashboard de métricas de BARF.

Define los tipos de widget disponibles (:class:`WidgetType`), la
configuración de un widget (:class:`Widget`) y los datos renderizados
(:class:`WidgetData`).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WidgetType(StrEnum):
    """Tipos de widget que el dashboard puede renderizar."""

    CHANNEL_TRENDS = "channel-trends"
    MUSIC_USAGE = "music-usage"
    RECENT_PROJECTS = "recent-projects"
    UPLOAD_STATUS = "upload-status"
    ENGAGEMENT_METRICS = "engagement-metrics"
    SCHEDULED_TASKS = "scheduled-tasks"
    CHANNEL_COMPARISON = "channel-comparison"
    DAILY_ACTIVITY = "daily-activity"
    TOP_VIDEOS = "top-videos"
    CATALOG_STATS = "catalog-stats"


class Widget(BaseModel):
    """Configuración de un widget del dashboard."""

    id: str
    type: WidgetType
    title: str
    params: dict = Field(default_factory=dict)
    position: int = 0
    refresh_interval: int = 3600  # segundos (1 hora)
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime | None = None


class WidgetData(BaseModel):
    """Datos renderizados de un widget (el resultado de calcular la métrica)."""

    widget_id: str
    type: WidgetType
    title: str
    data: dict  # Datos específicos del widget
    rendered_at: datetime = Field(default_factory=datetime.now)
