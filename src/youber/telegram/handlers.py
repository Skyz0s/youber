"""Manejadores de comandos del bot de Telegram de BARF.

Cada función recibe ``update`` y ``context`` de python-telegram-bot y delega
en los módulos del framework (research, music, workflow, video, upload).
Los comandos largos responden primero con un mensaje de progreso (🔄) y
luego con el resultado formateado en HTML.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes

from youber.cli.workflow_cli import run_workflow
from youber.music.library import MusicLibrary
from youber.music.models import Mood
from youber.research.channel_analyzer import ChannelAnalyzer
from youber.telegram.messages import (
    format_channel,
    format_help,
    format_scheduled,
    format_status,
    format_tracks,
)
from youber.upload.auth import YouTubeAuth
from youber.upload.metadata import VideoMetadata
from youber.upload.youtube import YouTubeUploader
from youber.video.editor import VideoEditor

Context = ContextTypes.DEFAULT_TYPE

MUSIC_DIR = Path(os.getenv("YOUBER_MUSIC_DIR", "music"))
TASKS_FILE = Path(os.getenv("YOUBER_TASKS_FILE", "~/.youber/tasks.json")).expanduser()

# Tareas en curso registradas por los comandos largos (para /status).
ACTIVE_TASKS: dict[str, str] = {}


async def _reply(update: Update, text: str, **kwargs: Any) -> bool:
    """Envía un mensaje; devuelve ``False`` si no hay chat (p. ej. callback)."""
    if update.effective_message is None:
        return False
    await update.effective_message.reply_text(text, **kwargs)
    return True


def _register_task(name: str, state: str = "en curso") -> None:
    """Registra una tarea en curso para mostrarla en /status."""
    ACTIVE_TASKS[name] = state


def _finish_task(name: str) -> None:
    """Marca una tarea como finalizada (la elimina del registro)."""
    ACTIVE_TASKS.pop(name, None)


def _parse_mood(text: str | None) -> Mood | None:
    """Convierte el texto del usuario (valor o nombre) en un :class:`Mood`."""
    if not text:
        return None
    lowered = text.strip().lower()
    for mood in Mood:
        if mood.value.lower() == lowered or mood.name.lower() == lowered:
            return mood
    return None


def _flag_value(args: list[str], flag: str) -> str | None:
    """Devuelve el valor que sigue a un flag (``--title X``) o ``None``."""
    if flag in args:
        index = args.index(flag)
        if index + 1 < len(args):
            return args[index + 1]
    return None


# ---------------------------------------------------------------------------
# Almacén de tareas programadas (JSON, para /schedule)
# ---------------------------------------------------------------------------


class TaskStore:
    """Almacén ligero de tareas programadas en un fichero JSON."""

    def __init__(self, path: Path = TASKS_FILE) -> None:
        self.path = path

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def add(self, command: str, target: str, cadence: str = "once") -> dict:
        task = {
            "id": uuid.uuid4().hex[:8],
            "command": command,
            "target": target,
            "cadence": cadence,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        tasks = self.load()
        tasks.append(task)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return task

    def remove(self, task_id: str) -> bool:
        tasks = [task for task in self.load() if task["id"] != task_id]
        self.path.write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return len(tasks) < len(self.load()) + 1


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


async def handle_research(update: Update, context: Context) -> None:
    """``/research <canal>`` — investiga un canal de YouTube."""
    channel = context.args[0] if context.args else None
    if not channel:
        await _reply(update, "Uso: /research <canal> (p. ej. /research @python)")
        return

    _register_task(f"research {channel}")
    await _reply(update, f"🔄 Investigando {channel}...")
    try:
        analyzer = ChannelAnalyzer()
        data = await analyzer.analyze(channel, max_videos=10)
    except Exception as exc:
        logger.warning(f"/research falló: {exc}")
        await _reply(update, f"❌ Error investigando {channel}: {exc}")
        return
    finally:
        _finish_task(f"research {channel}")

    await _reply(update, format_channel(data), parse_mode="HTML")


async def handle_music(update: Update, context: Context) -> None:
    """``/music search <término>`` o ``/music suggest <mood>``."""
    if not context.args or context.args[0] not in ("search", "suggest"):
        await _reply(
            update,
            "Uso:\n/music search <término>\n/music suggest <mood>",
        )
        return

    action = context.args[0]
    await _reply(update, "🔄 Buscando en el catálogo...")
    library = MusicLibrary(MUSIC_DIR)
    try:
        if action == "search":
            text = " ".join(context.args[1:]) or None
            tracks = library.search(text=text)
        else:
            mood = _parse_mood(context.args[1]) if len(context.args) > 1 else None
            tracks = library.suggest(mood=mood, limit=5)
    finally:
        library.close()

    await _reply(update, format_tracks(tracks), parse_mode="HTML")


async def handle_workflow(update: Update, context: Context) -> None:
    """``/workflow <canal> [--edit] [--upload]`` — flujo completo."""
    if not context.args:
        await _reply(
            update,
            "Uso: /workflow <canal> [--edit] [--upload] (p. ej. /workflow @python --edit)",
        )
        return

    channel = context.args[0]
    do_edit = "--edit" in context.args
    do_upload = "--upload" in context.args
    name = f"workflow {channel}"
    _register_task(name)
    await _reply(update, f"🔄 Ejecutando flujo completo para {channel}...")

    try:
        result = await run_workflow(channel_ref=channel, demo=False)
        lines = [
            f"✅ <b>Flujo completado</b> — {result['channel']}",
            f"🎬 Vídeo final: <code>{result['final_video']}</code>",
            f"📄 Datos: {result['json']} · {result['csv']}",
        ]
        if do_edit:
            lines.append("✂️ Edición: <b>incluida</b> (proyecto renderizado)")
        if do_upload:
            lines.append("📤 Subida: <b>pendiente</b> (ejecuta /upload con el vídeo)")
        await _reply(update, "\n".join(lines), parse_mode="HTML")
    except Exception as exc:
        logger.warning(f"/workflow falló: {exc}")
        await _reply(update, f"❌ Error en el flujo: {exc}")
    finally:
        _finish_task(name)


async def handle_edit(update: Update, context: Context) -> None:
    """``/edit <proyecto.json>`` — renderiza un proyecto de vídeo."""
    if not context.args:
        await _reply(update, "Uso: /edit <proyecto.json>")
        return

    project_path = context.args[0]
    _register_task(f"edit {project_path}")
    await _reply(update, f"🔄 Renderizando {project_path}...")
    try:
        project = VideoEditor.load(project_path)
        output = f"reports/{project.title.replace(' ', '_')}.mp4"
        editor = VideoEditor()
        await editor.render(project, output)
        await _reply(update, f"✅ Vídeo renderizado: <code>{output}</code>", parse_mode="HTML")
    except Exception as exc:
        logger.warning(f"/edit falló: {exc}")
        await _reply(update, f"❌ Error renderizando: {exc}")
    finally:
        _finish_task(f"edit {project_path}")


async def handle_status(update: Update, context: Context) -> None:
    """``/status`` — estado de las tareas en curso."""
    await _reply(update, format_status(ACTIVE_TASKS), parse_mode="HTML")


async def handle_schedule(update: Update, context: Context) -> None:
    """``/schedule list`` o ``/schedule add <canal> [--daily]``."""
    if not context.args or context.args[0] not in ("list", "add", "remove"):
        await _reply(
            update,
            "Uso:\n/schedule list\n/schedule add <canal> [--daily]\n/schedule remove <id>",
        )
        return

    store = TaskStore()
    action = context.args[0]
    if action == "list":
        await _reply(update, format_scheduled(store.load()), parse_mode="HTML")
    elif action == "add":
        if len(context.args) < 2:
            await _reply(update, "Uso: /schedule add <canal> [--daily]")
            return
        target = context.args[1]
        cadence = "daily" if "--daily" in context.args else "once"
        task = store.add(command="research", target=target, cadence=cadence)
        await _reply(
            update,
            f"🗓️ Tarea programada: <code>{task['id']}</code> — {target} ({cadence})",
            parse_mode="HTML",
        )
    elif action == "remove":
        if len(context.args) < 2:
            await _reply(update, "Uso: /schedule remove <id>")
            return
        removed = store.remove(context.args[1])
        await _reply(
            update,
            f"🗑️ Tarea {context.args[1]} eliminada" if removed else "❌ Tarea no encontrada",
        )


async def handle_upload(update: Update, context: Context) -> None:
    """``/upload <video> --title "..."`` — sube un vídeo a YouTube."""
    if not context.args:
        await _reply(
            update,
            'Uso: /upload <video> --title "Mi Video" [--description ...] [--tags a,b]',
        )
        return

    video = context.args[0]
    title = _flag_value(context.args, "--title") or Path(video).stem
    description = _flag_value(context.args, "--description") or ""
    tags = (_flag_value(context.args, "--tags") or "").split(",")

    _register_task(f"upload {video}")
    await _reply(update, f"🔄 Subiendo {video} a YouTube...")
    try:
        auth = YouTubeAuth()
        uploader = YouTubeUploader(auth)
        metadata = VideoMetadata(title=title, description=description, tags=tags)
        resource = await uploader.upload_video(video, metadata)
        video_id = resource.get("id", "")
        url = YouTubeUploader.get_video_url(video_id)
        await _reply(update, f"✅ Vídeo subido: {url}", parse_mode="HTML")
    except Exception as exc:
        logger.warning(f"/upload falló: {exc}")
        await _reply(
            update,
            f"❌ Error subiendo: {exc}. ¿Has ejecutado `youber-upload auth`?",
        )
    finally:
        _finish_task(f"upload {video}")


async def handle_help(update: Update, context: Context) -> None:
    """``/help`` — muestra la ayuda con todos los comandos."""
    from youber.telegram.commands import COMMANDS

    await _reply(update, format_help(COMMANDS), parse_mode="HTML")


async def handle_callback(update: Update, context: Context) -> None:
    """Procesa los botones inline (selección de mood del catálogo)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    data = query.data or ""
    if data.startswith("mood:"):
        mood = _parse_mood(data.split(":", 1)[1])
        library = MusicLibrary(MUSIC_DIR)
        try:
            tracks = library.suggest(mood=mood, limit=3)
        finally:
            library.close()
        await query.edit_message_text(format_tracks(tracks), parse_mode="HTML")
