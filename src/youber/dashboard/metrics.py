"""Cálculo de métricas del dashboard de BARF.

Funciones puras que convierten los datos de las fuentes
(:mod:`youber.dashboard.data_sources`) en métricas estructuradas (dicts)
para cada tipo de widget. Son offline-testables: reciben datos tipados y
no tocan red.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from youber.music.models import Track
from youber.research.data_models import ChannelData, VideoData
from youber.research.patterns import parse_compact_count
from youber.scheduler.models import ScheduledJob

# ---------------------------------------------------------------------------
# Widgets del ecosistema
# ---------------------------------------------------------------------------


def catalog_stats(tracks: list[Track]) -> dict[str, Any]:
    """Estadísticas del catálogo de música."""
    moods: dict[str, int] = {}
    genres: dict[str, int] = {}
    by_source: dict[str, int] = {}
    total_duration = 0.0
    for track in tracks:
        total_duration += track.duration
        by_source[track.source.value] = by_source.get(track.source.value, 0) + 1
        for mood in track.moods:
            moods[mood.value] = moods.get(mood.value, 0) + 1
        if track.genre:
            genres[track.genre] = genres.get(track.genre, 0) + 1
    return {
        "total_tracks": len(tracks),
        "total_duration_s": round(total_duration, 1),
        "favorites": sum(1 for track in tracks if track.favorite),
        "by_source": dict(sorted(by_source.items())),
        "moods": dict(sorted(moods.items(), key=lambda item: item[1], reverse=True)),
        "genres": dict(sorted(genres.items(), key=lambda item: item[1], reverse=True)),
    }


def music_usage(tracks: list[Track], limit: int = 5) -> dict[str, Any]:
    """Pistas más usadas y uso total del catálogo."""
    ranked = sorted(
        (track for track in tracks if track.usage_count > 0),
        key=lambda track: track.usage_count,
        reverse=True,
    )
    return {
        "total_uses": sum(track.usage_count for track in tracks),
        "used_tracks": len(ranked),
        "top": [
            {
                "title": track.title,
                "artist": track.artist or "?",
                "usage_count": track.usage_count,
                "favorite": track.favorite,
            }
            for track in ranked[:limit]
        ],
    }


def recent_projects(reports: list[dict[str, Any]], limit: int = 5) -> dict[str, Any]:
    """Reportes/proyectos recientes por fecha de modificación."""
    return {
        "total": len(reports),
        "recent": [
            {
                "name": report["name"],
                "path": report["path"],
                "modified": report["modified"].isoformat(timespec="minutes"),
            }
            for report in reports[:limit]
        ],
    }


def upload_status(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen del historial de subidas a YouTube."""
    if not history:
        return {"total": 0, "statuses": {}, "recent": []}
    statuses: dict[str, int] = {}
    for entry in history:
        status = str(entry.get("status", "unknown"))
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "total": len(history),
        "statuses": statuses,
        "recent": [
            {
                "title": entry.get("title", "?"),
                "url": entry.get("url", ""),
                "status": entry.get("status", "?"),
                "uploaded_at": entry.get("uploaded_at", ""),
            }
            for entry in history[:5]
        ],
    }


def engagement_metrics(videos: list[VideoData]) -> dict[str, Any]:
    """Métricas de engagement de una lista de vídeos."""
    views = [parse_compact_count(video.views) for video in videos]
    parsed_views = [value for value in views if value is not None]
    likes = [parse_compact_count(video.likes) for video in videos if video.likes]
    parsed_likes = [value for value in likes if value is not None]

    return {
        "videos": len(videos),
        "avg_views": round(sum(parsed_views) / len(parsed_views)) if parsed_views else 0,
        "max_views": max(parsed_views) if parsed_views else 0,
        "avg_likes": round(sum(parsed_likes) / len(parsed_likes)) if parsed_likes else 0,
        "like_rate": (
            round(sum(parsed_likes) / sum(parsed_views) * 100, 2)
            if parsed_views and sum(parsed_views) > 0
            else 0.0
        ),
    }


def scheduled_tasks(jobs: list[ScheduledJob]) -> dict[str, Any]:
    """Resumen de los trabajos programados del scheduler."""
    by_type: dict[str, int] = {}
    by_cadence: dict[str, int] = {}
    enabled = 0
    for job in jobs:
        by_type[job.job_type.value] = by_type.get(job.job_type.value, 0) + 1
        by_cadence[job.schedule_type.value] = by_cadence.get(job.schedule_type.value, 0) + 1
        if job.enabled:
            enabled += 1

    upcoming = sorted(
        (job for job in jobs if job.enabled and job.next_run is not None),
        key=lambda job: job.next_run or datetime.max,
    )
    return {
        "total": len(jobs),
        "enabled": enabled,
        "by_type": by_type,
        "by_cadence": by_cadence,
        "next": [
            {
                "name": job.name,
                "type": job.job_type.value,
                "next_run": job.next_run.isoformat(timespec="minutes") if job.next_run else None,
            }
            for job in upcoming[:5]
        ],
    }


def channel_trends(channel: ChannelData) -> dict[str, Any]:
    """Tendencias de un canal: vídeos, vistas y suscriptores."""
    videos = channel.videos
    views = [
        value
        for value in (parse_compact_count(video.views) for video in videos)
        if value is not None
    ]
    return {
        "channel": channel.name,
        "subscribers": channel.subscribers,
        "videos_analyzed": len(videos),
        "total_views": round(sum(views)) if views else 0,
        "avg_views": round(sum(views) / len(views)) if views else 0,
        "max_views": max(views) if views else 0,
    }


def top_videos(videos: list[VideoData], limit: int = 5) -> dict[str, Any]:
    """Los vídeos con más visualizaciones de un canal."""
    ranked = sorted(
        videos,
        key=lambda video: parse_compact_count(video.views) or 0,
        reverse=True,
    )
    return {
        "top": [
            {
                "title": video.title,
                "views": video.views,
                "duration": video.duration,
                "url": video.url,
            }
            for video in ranked[:limit]
        ]
    }


def channel_comparison(channels: list[ChannelData]) -> dict[str, Any]:
    """Comparación de varios canales (suscriptores, vídeos, vistas)."""
    rows = []
    for channel in channels:
        views = [
            value
            for value in (parse_compact_count(video.views) for video in channel.videos)
            if value is not None
        ]
        rows.append(
            {
                "name": channel.name,
                "subscribers": channel.subscribers,
                "videos": len(channel.videos),
                "total_views": round(sum(views)) if views else 0,
            }
        )
    return {"channels": rows}


def daily_activity(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Actividad diaria (número de reportes generados por día)."""
    by_day: dict[str, int] = {}
    for report in reports:
        day = report["modified"].date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
    return {
        "days": len(by_day),
        "total_reports": len(reports),
        "by_day": dict(sorted(by_day.items())),
    }
