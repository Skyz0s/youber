"""Registro de comandos del bot de Telegram de BARF.

Define la tabla de comandos (nombre → manejador) y expone ``register_handlers``
para enchufarlos a la :class:`telegram.ext.Application` del bot.
"""

from __future__ import annotations

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from youber.telegram.handlers import (
    handle_callback,
    handle_edit,
    handle_help,
    handle_music,
    handle_research,
    handle_schedule,
    handle_status,
    handle_upload,
    handle_workflow,
)

# Tabla de comandos: nombre → manejador y descripción (para /help).
COMMANDS: dict[str, dict] = {
    "research": {
        "handler": handle_research,
        "description": "Investiga un canal: /research <canal>",
    },
    "music": {
        "handler": handle_music,
        "description": "Busca/sugiere música: /music search <término> | /music suggest <mood>",
    },
    "workflow": {
        "handler": handle_workflow,
        "description": "Flujo completo: /workflow <canal> [--edit] [--upload]",
    },
    "edit": {
        "handler": handle_edit,
        "description": "Renderiza un proyecto: /edit <proyecto.json>",
    },
    "status": {
        "handler": handle_status,
        "description": "Estado de las tareas en curso",
    },
    "schedule": {
        "handler": handle_schedule,
        "description": "Tareas programadas: /schedule list | /schedule add <canal> [--daily]",
    },
    "upload": {
        "handler": handle_upload,
        "description": "Sube un vídeo a YouTube: /upload <video> --title \"Mi Video\"",
    },
    "help": {
        "handler": handle_help,
        "description": "Muestra esta ayuda",
    },
}


def register_handlers(app: Application) -> None:
    """Registra todos los comandos y el manejador de callbacks en la aplicación."""
    for name, info in COMMANDS.items():
        app.add_handler(CommandHandler(name, info["handler"]))
    app.add_handler(CallbackQueryHandler(handle_callback))


def build_application(token: str) -> Application:
    """Construye la aplicación del bot con todos los handlers registrados.

    Args:
        token: Token del bot de BotFather.

    Returns:
        La :class:`telegram.ext.Application` lista para ``run_polling()``.
    """
    app = Application.builder().token(token).build()
    register_handlers(app)
    return app
