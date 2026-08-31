"""Bot de Telegram de BARF.

Controla el framework desde Telegram: investigar canales, buscar/sugerir
música del catálogo, ejecutar el flujo completo de edición, renderizar
proyectos, consultar tareas, programar y subir vídeos a YouTube.

Límites éticos (igual que el resto del framework):

- Solo contenido propio o con licencia; sin spam ni scraping abusivo.
- El bot es una interfaz de control, no una herramienta de manipulación.
- Uso educativo y de investigación.
"""

from youber.telegram.commands import COMMANDS, build_application, register_handlers
from youber.telegram.keyboards import confirm_keyboard, mood_keyboard, privacy_keyboard
from youber.telegram.messages import (
    escape_html,
    format_channel,
    format_help,
    format_scheduled,
    format_status,
    format_tracks,
)

__all__ = [
    "COMMANDS",
    "build_application",
    "confirm_keyboard",
    "escape_html",
    "format_channel",
    "format_help",
    "format_scheduled",
    "format_status",
    "format_tracks",
    "mood_keyboard",
    "privacy_keyboard",
    "register_handlers",
]
