"""Formateo de mensajes del bot de Telegram de BARF.

Funciones puras que convierten los modelos del framework (canales, pistas,
tareas) en mensajes legibles con formato HTML (el que soporta el bot).
"""

from __future__ import annotations

from html import escape

from youber.music.models import Track
from youber.research.data_models import ChannelData


def escape_html(text: str) -> str:
    """Escapa texto para parse_mode=HTML (evita HTML injection)."""
    return escape(text)


def format_help(commands: dict[str, dict]) -> str:
    """Genera el mensaje de ayuda a partir del registro de comandos."""
    lines = ["<b>BARF · Comandos</b>", ""]
    for name in sorted(commands):
        info = commands[name]
        lines.append(f"<code>/{name}</code> — {info['description']}")
    return "\n".join(lines)


def format_channel(channel: ChannelData, max_videos: int = 10) -> str:
    """Formatea un canal con sus vídeos recientes."""
    lines = [
        f"<b>{escape_html(channel.name)}</b>",
        f"🔗 {channel.url}",
        f"👥 Suscriptores: {channel.subscribers or '-'}",
        f"🎬 Vídeos analizados: {len(channel.videos)}",
        "",
        "<b>Vídeos recientes:</b>",
    ]
    for video in channel.videos[:max_videos]:
        lines.append(f"• {escape_html(video.title)} — {video.views}")
    return "\n".join(lines)


def format_tracks(tracks: list[Track]) -> str:
    """Formatea una lista de pistas del catálogo de música."""
    if not tracks:
        return "🎵 No hay pistas que coincidan con la búsqueda."
    lines = ["<b>🎵 Pistas:</b>"]
    for track in tracks:
        moods = ", ".join(mood.value for mood in track.moods) or "-"
        favorite = " ⭐" if track.favorite else ""
        lines.append(
            f"• {escape_html(track.title)} — {escape_html(track.artist or '?')} "
            f"({track.duration:.0f}s) [{moods}]{favorite}"
        )
    return "\n".join(lines)


def format_scheduled(tasks: list[dict]) -> str:
    """Formatea las tareas programadas."""
    if not tasks:
        return "🗓️ No hay tareas programadas."
    lines = ["<b>🗓️ Tareas programadas:</b>"]
    for task in tasks:
        lines.append(
            f"• <code>{task['id']}</code> — {escape_html(task['command'])} "
            f"{escape_html(task['target'])} ({task['cadence']})"
        )
    return "\n".join(lines)


def format_status(active: dict[str, str]) -> str:
    """Formatea las tareas en curso (para /status)."""
    if not active:
        return "✅ Sin tareas en curso."
    lines = ["<b>🔄 Tareas en curso:</b>"]
    for name, state in active.items():
        lines.append(f"• {escape_html(name)} — {escape_html(state)}")
    return "\n".join(lines)
