"""Tests del dashboard de métricas (models, data_sources, metrics, registry, widgets, renderer, cli)."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from youber.dashboard.cli import _parse_widgets, _widget_type, build_parser
from youber.dashboard.data_sources import (
    list_reports,
    load_music_tracks,
    load_scheduled_jobs,
    load_upload_history,
)
from youber.dashboard.metrics import (
    catalog_stats,
    channel_trends,
    daily_activity,
    engagement_metrics,
    music_usage,
    recent_projects,
    scheduled_tasks,
    top_videos,
    upload_status,
)
from youber.dashboard.models import Widget, WidgetData, WidgetType
from youber.dashboard.registry import WIDGET_REGISTRY, get_definition, list_widgets
from youber.dashboard.renderer import (
    render_dashboard,
    render_dashboard_html,
    render_dashboard_json,
    render_dashboard_markdown,
    render_widget_html,
    render_widget_markdown,
)
from youber.dashboard.widgets import WidgetManager, create_widget, default_widgets
from youber.music.models import Mood, Track
from youber.research.data_models import ChannelData, VideoData
from youber.scheduler.models import JobType, ScheduledJob, ScheduleType


def make_track(usage: int = 0, favorite: bool = False) -> Track:
    return Track(
        id="t1",
        file_path=Path("/tmp/musica.mp3"),
        title="Mi tema",
        artist="Artista",
        duration=180.0,
        genre="pop",
        moods=[Mood.RELAXING],
        usage_count=usage,
        favorite=favorite,
        file_hash="abc",
    )


def make_video(views: str = "1,2 K") -> VideoData:
    return VideoData(
        title="Vídeo",
        url="https://www.youtube.com/watch?v=abc",
        video_id="abc",
        views=views,
        likes="100",
        duration="12:34",
        channel_name="Canal",
        channel_url="https://www.youtube.com/@canal",
    )


def make_channel() -> ChannelData:
    return ChannelData(
        name="Canal Demo",
        url="https://www.youtube.com/@canaldemo",
        handle="canaldemo",
        subscribers="12,3 K",
        videos=[make_video(), make_video("2,5 M")],
    )


def make_job() -> ScheduledJob:
    return ScheduledJob(
        id="j1",
        name="research diario",
        job_type=JobType.RESEARCH,
        schedule_type=ScheduleType.DAILY,
        schedule_value="09:00",
        params={"channel": "@python"},
        enabled=True,
        next_run=datetime(2026, 9, 1, 9, 0, 0),
    )


def make_widget(widget_type: WidgetType = WidgetType.CATALOG_STATS) -> Widget:
    return create_widget(widget_type)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_widget_type_values():
    assert WidgetType.CHANNEL_TRENDS == "channel-trends"
    assert WidgetType.TOP_VIDEOS == "top-videos"
    assert WidgetType.CATALOG_STATS == "catalog-stats"
    assert len(WidgetType) == 10


def test_widget_defaults():
    widget = Widget(id="w1", type=WidgetType.MUSIC_USAGE, title="Uso")
    assert widget.params == {}
    assert widget.position == 0
    assert widget.refresh_interval == 3600
    assert widget.enabled is True
    assert widget.created_at is not None


def test_widget_validation():
    with pytest.raises(ValidationError):
        Widget(id="", type="nope", title="")


def test_widget_data_defaults():
    data = WidgetData(widget_id="w1", type=WidgetType.MUSIC_USAGE, title="T", data={})
    assert data.rendered_at is not None


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------


def test_load_music_tracks_empty(tmp_path: Path):
    assert load_music_tracks(tmp_path) == []


def test_list_reports(tmp_path: Path):
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.md").write_text("# x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")  # no incluido
    reports = list_reports(tmp_path)
    assert len(reports) == 2
    names = {report["name"] for report in reports}
    assert names == {"a.json", "b.md"}
    assert all("modified" in report for report in reports)


def test_load_upload_history_missing(tmp_path: Path):
    assert load_upload_history(tmp_path / "no.json") == []


def test_load_upload_history(tmp_path: Path):
    history_file = tmp_path / "history.json"
    history_file.write_text(
        json.dumps([{"title": "Vídeo", "status": "public", "url": "https://youtu.be/x"}]),
        encoding="utf-8",
    )
    history = load_upload_history(history_file)
    assert len(history) == 1
    assert history[0]["title"] == "Vídeo"


def test_load_scheduled_jobs(tmp_path: Path):
    jobs = load_scheduled_jobs(tmp_path / "jobs.json")
    assert jobs == []


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_catalog_stats():
    stats = catalog_stats([make_track(usage=3, favorite=True)])
    assert stats["total_tracks"] == 1
    assert stats["favorites"] == 1
    assert stats["total_duration_s"] == 180.0
    assert stats["moods"] == {"relajante": 1}
    assert stats["genres"] == {"pop": 1}


def test_music_usage():
    usage = music_usage([make_track(usage=3), make_track(usage=1)])
    assert usage["total_uses"] == 4
    assert usage["used_tracks"] == 2
    assert usage["top"][0]["usage_count"] == 3


def test_recent_projects():
    now = datetime(2026, 8, 31, 12, 0, 0)
    reports = [
        {"name": "b.md", "path": "/r/b.md", "modified": now},
        {"name": "a.json", "path": "/r/a.json", "modified": now},
    ]
    result = recent_projects(reports, limit=1)
    assert result["total"] == 2
    assert len(result["recent"]) == 1


def test_upload_status_empty_and_full():
    assert upload_status([])["total"] == 0
    status = upload_status([{"title": "V", "status": "public", "url": "x"}])
    assert status["total"] == 1
    assert status["statuses"] == {"public": 1}


def test_engagement_metrics():
    metrics = engagement_metrics([make_video("1,2 K"), make_video("2,5 M")])
    assert metrics["videos"] == 2
    assert metrics["avg_views"] > 0
    assert metrics["max_views"] == 2_500_000


def test_scheduled_tasks():
    result = scheduled_tasks([make_job()])
    assert result["total"] == 1
    assert result["enabled"] == 1
    assert result["by_type"] == {"research": 1}
    assert result["by_cadence"] == {"daily": 1}
    assert result["next"][0]["name"] == "research diario"


def test_channel_trends_and_top_videos():
    trends = channel_trends(make_channel())
    assert trends["channel"] == "Canal Demo"
    assert trends["videos_analyzed"] == 2
    assert trends["max_views"] == 2_500_000

    top = top_videos(make_channel().videos, limit=1)
    assert top["top"][0]["views"] == "2,5 M"


def test_daily_activity():
    reports = [
        {"name": "a", "path": "a", "modified": datetime(2026, 8, 31, 10, 0, 0)},
        {"name": "b", "path": "b", "modified": datetime(2026, 8, 31, 11, 0, 0)},
        {"name": "c", "path": "c", "modified": datetime(2026, 8, 30, 10, 0, 0)},
    ]
    activity = daily_activity(reports)
    assert activity["days"] == 2
    assert activity["total_reports"] == 3
    assert activity["by_day"]["2026-08-31"] == 2


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_has_all_types():
    assert set(WIDGET_REGISTRY.keys()) == set(WidgetType)
    assert len(list_widgets()) == len(WidgetType)


def test_get_definition():
    definition = get_definition(WidgetType.CATALOG_STATS)
    assert definition.title == "Estadísticas del catálogo de música"
    assert "tracks" in definition.sources


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


def test_create_widget_and_defaults():
    widget = create_widget("catalog-stats")
    assert widget.type == WidgetType.CATALOG_STATS
    assert widget.id
    assert widget.title == WIDGET_REGISTRY[WidgetType.CATALOG_STATS].title
    assert len(default_widgets()) == len(WidgetType)


def test_widget_manager_collect():
    manager = WidgetManager(
        sources={
            "tracks": [make_track(usage=2)],
            "reports": [],
            "history": [],
            "jobs": [],
            "videos": [],
            "channel": make_channel(),
            "channels": [],
        }
    )
    widget = create_widget(WidgetType.CATALOG_STATS)
    data = manager.collect(widget)
    assert isinstance(data, WidgetData)
    assert data.widget_id == widget.id
    assert data.data["total_tracks"] == 1


def test_widget_manager_missing_source():
    # Dict truthy pero sin la fuente 'tracks' que necesita catalog-stats.
    manager = WidgetManager(sources={"reports": []})
    widget = create_widget(WidgetType.CATALOG_STATS)
    with pytest.raises(ValueError, match="necesita la fuente"):
        manager.collect(widget)


def test_widget_manager_create_widget_method():
    manager = WidgetManager(
        sources={
            "tracks": [],
            "reports": [],
            "history": [],
            "jobs": [],
            "videos": [],
            "channel": None,
            "channels": [],
        }
    )
    widget = manager.create_widget("catalog-stats", position=2)
    assert widget.type == WidgetType.CATALOG_STATS
    assert widget.position == 2
    assert widget.title == WIDGET_REGISTRY[WidgetType.CATALOG_STATS].title


def test_widget_manager_collect_types():
    manager = WidgetManager(
        sources={
            "tracks": [make_track(usage=1)],
            "reports": [],
            "history": [],
            "jobs": [],
            "videos": [],
            "channel": None,
            "channels": [],
        }
    )
    data = manager.collect_types(
        ["catalog-stats", "scheduled-tasks", "upload-status"]
    )
    assert [item.type for item in data] == [
        WidgetType.CATALOG_STATS,
        WidgetType.SCHEDULED_TASKS,
        WidgetType.UPLOAD_STATUS,
    ]
    assert [item.position for item in data] == [0, 1, 2]
    assert data[0].data["total_tracks"] == 1


def test_widget_manager_collect_many_skips_disabled():
    manager = WidgetManager(
        sources={
            "tracks": [make_track()],
            "reports": [],
            "history": [],
            "jobs": [],
            "videos": [],
            "channel": make_channel(),
            "channels": [],
        }
    )
    enabled = create_widget(WidgetType.CATALOG_STATS)
    disabled = create_widget(WidgetType.MUSIC_USAGE)
    disabled.enabled = False
    data = manager.collect_many([enabled, disabled])
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def _sample_widget_data() -> WidgetData:
    return WidgetData(
        widget_id="w1",
        type=WidgetType.CATALOG_STATS,
        title="Catálogo",
        data={"total_tracks": 3, "favorites": 1, "moods": {"relajante": 2}},
    )


def test_render_widget_markdown():
    text = render_widget_markdown(_sample_widget_data())
    assert "### Catálogo" in text
    assert "total_tracks" in text


def test_render_widget_html():
    html = render_widget_html(_sample_widget_data())
    assert "<div" in html
    assert "Catálogo" in html


def test_render_dashboard_respects_position():
    first = WidgetData(
        widget_id="b",
        type=WidgetType.CATALOG_STATS,
        title="Catálogo",
        data={"total_tracks": 1},
        position=0,
    )
    second = WidgetData(
        widget_id="a",
        type=WidgetType.SCHEDULED_TASKS,
        title="Tareas",
        data={"total": 1},
        position=1,
    )
    # Se pasan desordenados; el render debe respetar la posición, no el id.
    html = render_dashboard_html([second, first])
    assert html.index("Catálogo") < html.index("Tareas")
    md = render_dashboard_markdown([second, first])
    assert md.index("Catálogo") < md.index("Tareas")


def test_render_dashboard_formats():
    data = [_sample_widget_data()]
    assert "Dashboard" in render_dashboard_markdown(data)
    assert "<!DOCTYPE html>" in render_dashboard_html(data)
    payload = json.loads(render_dashboard_json(data))
    assert payload[0]["title"] == "Catálogo"


def test_render_dashboard_invalid_format():
    with pytest.raises(ValueError):
        render_dashboard([], "xml")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_widget_type():
    import argparse

    assert _widget_type("catalog-stats") == WidgetType.CATALOG_STATS
    with pytest.raises(argparse.ArgumentTypeError):
        _widget_type("nope")


def test_cli_parse_widgets():
    import argparse

    assert _parse_widgets("catalog-stats,scheduled-tasks,upload-status") == [
        WidgetType.CATALOG_STATS,
        WidgetType.SCHEDULED_TASKS,
        WidgetType.UPLOAD_STATUS,
    ]
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_widgets("catalog-stats,nope")


def test_cli_parser():
    parser = build_parser()
    assert parser.parse_args(["list"]).command == "list"
    args = parser.parse_args(["render", "catalog-stats", "-f", "json"])
    assert args.type == WidgetType.CATALOG_STATS
    assert args.format == "json"
    args = parser.parse_args(["dashboard", "--format", "html", "-o", "dash.html"])
    assert args.format == "html"
    assert args.output == "dash.html"
