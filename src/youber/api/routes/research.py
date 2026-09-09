"""Ruta ``research`` — análisis de canales públicos de YouTube."""

from __future__ import annotations

from typing import Any

from youber.api.models import ApiError
from youber.research.channel_analyzer import ChannelAnalyzer

_VALID_MODES = ("auto", "html", "api")


async def channel_info(params: dict[str, Any]) -> dict[str, Any]:
    """Datos públicos de un canal (nombre, suscriptores, vídeos recientes)."""
    channel = str(params.get("channel", "")).strip()
    if not channel:
        raise ApiError("Falta el parámetro 'channel' (URL o @handle del canal)")
    mode = str(params.get("mode", "auto")).lower()
    if mode not in _VALID_MODES:
        raise ApiError(f"Modo desconocido: {mode!r}. Válidos: {', '.join(_VALID_MODES)}")
    try:
        limit = max(1, min(int(params.get("limit", 10)), 50))
    except (TypeError, ValueError):
        limit = 10

    analyzer = ChannelAnalyzer()
    try:
        channel_data = await analyzer.analyze(channel, max_videos=limit, mode=mode)
    except Exception as exc:
        raise ApiError(f"No se pudo analizar el canal {channel!r}: {exc}") from None

    return channel_data.model_dump(mode="json")
