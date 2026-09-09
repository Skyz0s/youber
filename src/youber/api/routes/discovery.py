"""Ruta ``discovery`` — búsqueda de canales de YouTube."""

from __future__ import annotations

import os
from typing import Any

from youber.api.models import ApiError
from youber.discovery.categories import ChannelCategory, all_categories
from youber.discovery.search import ChannelSearcher

_VALID_MODES = ("auto", "api", "html", "demo")


def parse_category(value: str | None) -> ChannelCategory | None:
    """Convierte el texto del usuario (valor o nombre) en una categoría."""
    if not value:
        return None
    text = value.strip()
    lowered = text.lower()
    for category in all_categories():
        if category.value.lower() == lowered or category.name.lower() == lowered:
            return category
    valid = ", ".join(f"{c.value} ({c.name})" for c in all_categories())
    raise ApiError(f"Categoría desconocida: {value!r}. Válidas: {valid}")


async def search_channels(params: dict[str, Any]) -> dict[str, Any]:
    """Busca canales por texto y/o categoría (API/HTML/demo)."""
    query = str(params.get("query", "")).strip()
    category = parse_category(params.get("category"))
    mode = str(params.get("mode", "auto")).lower()
    if mode not in _VALID_MODES:
        raise ApiError(f"Modo desconocido: {mode!r}. Válidos: {', '.join(_VALID_MODES)}")
    try:
        limit = max(1, min(int(params.get("limit", 10)), 50))
    except (TypeError, ValueError):
        limit = 10

    searcher = ChannelSearcher(api_key=os.environ.get("YOUTUBE_API_KEY"))
    try:
        result = await searcher.search(
            query=query or None,
            category=category,
            limit=limit,
            mode=mode,
        )
    except ValueError as exc:
        raise ApiError(str(exc)) from None

    return result.model_dump(mode="json")
