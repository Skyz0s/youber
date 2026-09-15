"""Definición de trabajos del scheduler de BARF.

Asocia cada :class:`~youber.scheduler.models.JobType` con una función
asíncrona (runner) que lo ejecuta con los parámetros del trabajo. Los
runners delegan en los módulos del framework.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from youber.scheduler.models import JobType, ScheduledJob

# Runner: recibe los params del trabajo y devuelve un dict con el resultado.
JobRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def _run_research(params: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta un trabajo de investigación de canal."""
    from youber.research.channel_analyzer import ChannelAnalyzer

    channel = params["channel"]
    max_videos = int(params.get("max_videos", 10))
    analyzer = ChannelAnalyzer()
    data = await analyzer.analyze(channel, max_videos=max_videos)
    return {
        "channel": data.name,
        "videos": len(data.videos),
        "subscribers": data.subscribers,
    }


async def _run_workflow(params: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta un trabajo de flujo completo (investigación + edición)."""
    from youber.cli.workflow_cli import run_workflow

    result = await run_workflow(
        channel_ref=params["channel"],
        demo=bool(params.get("demo", False)),
        output_dir=params.get("output_dir", "reports"),
    )
    return {
        "channel": result["channel"],
        "final_video": result["final_video"],
    }


async def _run_upload(params: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta un trabajo de subida a YouTube."""
    from youber.upload.auth import YouTubeAuth
    from youber.upload.metadata import VideoMetadata
    from youber.upload.youtube import YouTubeUploader

    auth = YouTubeAuth()
    uploader = YouTubeUploader(auth)
    metadata = VideoMetadata(
        title=params["title"],
        description=params.get("description", ""),
        tags=params.get("tags", []),
    )
    resource = await uploader.upload_video(params["video"], metadata)
    return {"video_id": resource.get("id", "")}


async def _run_music_scan(params: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta un trabajo de escaneo del catálogo de música."""
    from youber.music.library import MusicLibrary

    library = MusicLibrary(params.get("library", "music"))
    try:
        summary = await library.scan()
    finally:
        library.close()
    return summary


async def _run_journal_reminder(params: dict[str, Any]) -> dict[str, Any]:
    """Recuerda qué vídeos siguen sin las métricas de Studio.

    Parámetros:
        db: ruta del journal (por defecto ``YOUBER_JOURNAL_DB``/``~/.youber``).
        windows: lista o texto ``"7d,28d"`` de ventanas a vigilar.
        min_age_days: antigüedad mínima del vídeo para reclamarle métricas.
        notify: si es verdadero, envía el aviso por Telegram (best-effort).
    """
    from youber.journal.journal import DecisionJournal
    from youber.journal.reminders import (
        DEFAULT_MIN_AGE_DAYS,
        DEFAULT_WINDOWS,
        notify_telegram,
        pending_metrics,
    )

    raw_windows = params.get("windows") or DEFAULT_WINDOWS
    if isinstance(raw_windows, str):
        windows = tuple(part.strip() for part in raw_windows.split(",") if part.strip())
    else:
        windows = tuple(str(part) for part in raw_windows)

    journal = DecisionJournal(params.get("db"))
    try:
        report = pending_metrics(
            journal,
            windows=windows or DEFAULT_WINDOWS,
            min_age_days=float(params.get("min_age_days", DEFAULT_MIN_AGE_DAYS)),
            require_upload=bool(params.get("require_upload", True)),
        )
    finally:
        journal.close()

    message = report.message()
    notified = notify_telegram(message) if params.get("notify") else False
    logger.info(f"Recordatorio de métricas: {len(report.pending)} pendientes · "
                f"Telegram={'sí' if notified else 'no'}")
    return {
        "decisions": report.decisions,
        "published": report.published,
        "pending": len(report.pending),
        "notified": notified,
        "message": message,
    }


# Registro de runners por tipo de trabajo.
JOB_RUNNERS: dict[JobType, JobRunner] = {
    JobType.RESEARCH: _run_research,
    JobType.WORKFLOW: _run_workflow,
    JobType.UPLOAD: _run_upload,
    JobType.MUSIC_SCAN: _run_music_scan,
    JobType.JOURNAL_REMINDER: _run_journal_reminder,
}


async def run_job(job: ScheduledJob) -> dict[str, Any]:
    """Ejecuta un trabajo según su tipo.

    Args:
        job: Trabajo programado con sus parámetros.

    Returns:
        El resultado del runner (dict).

    Raises:
        ValueError: si el tipo de trabajo no tiene runner registrado.
    """
    runner = JOB_RUNNERS.get(job.job_type)
    if runner is None:
        raise ValueError(f"No hay runner para el tipo de trabajo: {job.job_type}")
    logger.info(f"Ejecutando trabajo {job.name} ({job.job_type.value})…")
    return await runner(job.params)
