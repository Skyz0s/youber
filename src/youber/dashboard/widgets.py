"""Generación y gestión de widgets del dashboard de BARF.

:class:`WidgetManager` crea :class:`~youber.dashboard.models.Widget`,
recolecta los datos de cada widget (llamando a su función de métricas con
las fuentes correspondientes) y devuelve :class:`WidgetData` listos para
renderizar.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from youber.dashboard.models import Widget, WidgetData, WidgetType
from youber.dashboard.registry import get_definition


def create_widget(
    widget_type: WidgetType | str,
    title: str | None = None,
    params: dict[str, Any] | None = None,
    position: int = 0,
    refresh_interval: int = 3600,
    enabled: bool = True,
) -> Widget:
    """Crea un widget configurado (sin datos todavía).

    Args:
        widget_type: Tipo de widget (acepta ``WidgetType`` o su valor str).
        title: Título (por defecto, el de la definición del registro).
        params: Parámetros específicos (p. ej. ``{"channel": "@python"}``).
        position: Orden en el dashboard.
        refresh_interval: Segundos entre actualizaciones (por defecto 1 h).
        enabled: Si el widget está activo.

    Returns:
        El widget creado (con ``id`` generado).
    """
    if isinstance(widget_type, str):
        widget_type = WidgetType(widget_type)
    definition = get_definition(widget_type)
    return Widget(
        id=uuid.uuid4().hex[:8],
        type=widget_type,
        title=title or definition.title,
        params=params or {},
        position=position,
        refresh_interval=refresh_interval,
        enabled=enabled,
    )


def default_widgets() -> list[Widget]:
    """Devuelve un conjunto de widgets por defecto (uno por tipo)."""
    return [
        create_widget(widget_type, position=index)
        for index, widget_type in enumerate(WidgetType)
    ]


class WidgetManager:
    """Gestiona widgets: recolecta los datos de cada uno a partir de fuentes."""

    def __init__(self, sources: dict[str, Any] | None = None) -> None:
        """Crea el gestor.

        Args:
            sources: Mapa ``nombre → dato`` que las funciones de métricas
                necesitan (``music``, ``reports``, ``uploads``, ``videos``,
                ``scheduler``, ``channel``, ``channels``). Si se omite, se
                cargan desde las fuentes por defecto.
        """
        self.sources = sources or _default_sources()

    def collect(self, widget: Widget) -> WidgetData:
        """Recolecta los datos de un widget (llama a su función de métricas).

        Args:
            widget: Widget configurado.

        Returns:
            Los datos renderizados del widget.

        Raises:
            ValueError: si falta alguna fuente de datos que el widget necesita.
        """
        definition = get_definition(widget.type)
        kwargs: dict[str, Any] = {}
        for source in definition.sources:
            if source not in self.sources:
                raise ValueError(
                    f"El widget {widget.type.value} necesita la fuente '{source}'"
                )
            kwargs[source] = self.sources[source]
        # Los params del widget se pasan como argumentos adicionales (limit, etc.).
        kwargs.update(widget.params)

        data = definition.metric(**kwargs)
        logger.debug(f"Widget {widget.id} ({widget.type.value}) recolectado")
        return WidgetData(
            widget_id=widget.id,
            type=widget.type,
            title=widget.title,
            data=data,
        )

    def collect_many(self, widgets: list[Widget]) -> list[WidgetData]:
        """Recolecta los datos de varios widgets (solo los activos)."""
        return [self.collect(widget) for widget in widgets if widget.enabled]


def _default_sources() -> dict[str, Any]:
    """Carga las fuentes por defecto del ecosistema (música, scheduler, reportes)."""
    from youber.dashboard import data_sources

    return {
        "tracks": data_sources.load_music_tracks(),
        "reports": data_sources.list_reports(),
        "history": data_sources.load_upload_history(),
        "jobs": data_sources.load_scheduled_jobs(),
        "videos": [],
        "channel": None,
        "channels": [],
    }
