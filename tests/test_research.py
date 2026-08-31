"""Tests del módulo de investigación de YouTube (models, parsers, patterns, export)."""

from pathlib import Path

import pytest

from tests.fixtures.research_html import CHANNEL_HTML, VIDEO_HTML, VIDEO_HTML_NO_SOCIAL
from youber.research.channel_analyzer import parse_channel_html
from youber.research.data_models import ChannelData, VideoData
from youber.research.exporters import (
    export_channel,
    export_videos,
    generate_channel_json,
    generate_channel_markdown,
    generate_videos_csv,
)
from youber.research.patterns import (
    channel_overview,
    duration_stats,
    extract_hashtags,
    hashtag_frequency,
    parse_compact_count,
    parse_duration_to_seconds,
    title_patterns,
)
from youber.research.video_analyzer import extract_video_id, parse_video_html

CHANNEL_URL = "https://www.youtube.com/@canaldemo"
VIDEO_URL = "https://www.youtube.com/watch?v=abc123def45"


def make_channel() -> ChannelData:
    """Canal de prueba reutilizable para tests de patterns/export."""
    base = {
        "title": "Vídeo {n}",
        "url": "https://www.youtube.com/watch?v=id{n}",
        "video_id": "id{n}",
        "views": "1,2 K",
        "duration": "12:34",
        "publish_date": "2026-08-{d:02d}",
        "hashtags": ["test", "youtube"],
        "channel_name": "Canal Demo",
        "channel_url": CHANNEL_URL,
    }
    videos = []
    for n in range(1, 4):
        data = {
            key: value.format(n=n, d=n) if isinstance(value, str) else value
            for key, value in base.items()
        }
        videos.append(VideoData(**data))
    return ChannelData(
        name="Canal Demo",
        url=CHANNEL_URL,
        handle="canaldemo",
        subscribers="12,3 K",
        total_views="1,5 M",
        videos=videos,
    )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


def test_video_model_defaults():
    video = VideoData(
        title="T",
        url="https://www.youtube.com/watch?v=abc",
        video_id="abc",
        views="10",
        channel_name="C",
        channel_url="https://www.youtube.com/@c",
    )
    assert video.likes is None
    assert video.hashtags == []
    assert video.extracted_at is not None


def test_channel_model_defaults():
    channel = ChannelData(name="C", url="https://www.youtube.com/@c")
    assert channel.videos == []
    assert channel.subscribers is None


# ---------------------------------------------------------------------------
# Parsers HTML
# ---------------------------------------------------------------------------


def test_parse_channel_html():
    channel = parse_channel_html(CHANNEL_HTML, CHANNEL_URL)
    assert channel.name == "Canal Demo"
    assert channel.handle == "canaldemo"
    assert channel.subscribers == "12,3 K suscriptores"
    assert len(channel.videos) == 1
    video = channel.videos[0]
    assert video.title == "Vídeo de prueba #1"
    assert video.video_id == "abc123def45"
    assert video.views == "1.234 visualizaciones"
    assert video.duration == "12:34"
    assert video.publish_date == "hace 2 semanas"
    assert video.thumbnail_url == "https://i.ytimg.com/vi/abc123def45/hqdefault.jpg"


def test_parse_video_html():
    video = parse_video_html(VIDEO_HTML, VIDEO_URL)
    assert video.title == "Vídeo de prueba #1"
    assert video.video_id == "abc123def45"
    assert video.views == "1234"
    assert video.duration == "12:34"
    assert video.publish_date == "2026-08-15"
    assert video.hashtags == ["test", "youtube", "aprendizaje"]
    assert video.channel_name == "Canal Demo"
    assert video.channel_url == "https://www.youtube.com/channel/UCdemo123456789"
    assert video.description is not None and "Descripción" in video.description
    assert video.likes == "98"
    assert video.comments == "12"


def test_parse_video_html_without_social():
    video = parse_video_html(
        VIDEO_HTML_NO_SOCIAL, "https://www.youtube.com/watch?v=xyz98765432"
    )
    assert video.title == "Vídeo sin métricas sociales"
    assert video.likes is None
    assert video.comments is None
    assert video.hashtags == []


def test_extract_video_id_variants():
    assert extract_video_id("https://www.youtube.com/watch?v=abc123def45") == "abc123def45"
    assert extract_video_id("https://youtu.be/abc123def45") == "abc123def45"
    assert extract_video_id("abc123def45") == "abc123def45"
    assert extract_video_id("https://example.com/not-youtube") is None


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------


def test_extract_hashtags():
    assert extract_hashtags("hola #mundo #test #mundo") == ["mundo", "test"]


def test_parse_compact_count():
    assert parse_compact_count("1,2 M") == 1_200_000
    assert parse_compact_count("3.4M") == 3_400_000
    assert parse_compact_count("12K") == 12_000
    assert parse_compact_count("500") == 500
    assert parse_compact_count("sin datos") is None


def test_hashtag_frequency():
    channel = make_channel()
    counter = hashtag_frequency(channel.videos)
    assert counter["test"] == 3
    assert counter["youtube"] == 3


def test_title_patterns():
    titles = [
        "TOP 10 herramientas",
        "¿Cómo funciona esto?",
        "PRUEBA EN MAYÚSCULAS",
        "X vs Y",
        "vídeo normal",
        "Guía completa de Python",
    ]
    stats = title_patterns(titles)
    assert stats["total"] == 6
    assert stats["with_numbers"] == 1
    assert stats["with_uppercase_words"] == 2  # TOP 10 + PRUEBA EN MAYÚSCULAS
    assert stats["with_question"] == 1
    assert stats["with_vs"] == 1
    assert stats["with_tutorial_keyword"] == 2  # ¿Cómo + Guía
    assert stats["with_top_list"] == 1


def test_parse_duration_to_seconds():
    assert parse_duration_to_seconds("12:34") == 754
    assert parse_duration_to_seconds("1:02:03") == 3723
    assert parse_duration_to_seconds("45") == 45
    assert parse_duration_to_seconds(None) is None
    assert parse_duration_to_seconds("abc") is None


def test_duration_stats():
    channel = make_channel()
    stats = duration_stats(channel.videos)
    assert stats["count"] == 3
    assert stats["avg_seconds"] == 754
    assert stats["buckets"]["medium_4_15min"] == 3


def test_channel_overview():
    overview = channel_overview(make_channel())
    assert overview["channel"]["name"] == "Canal Demo"
    assert overview["videos_count"] == 3
    assert overview["top_hashtags"][0]["hashtag"] == "test"
    assert overview["views_summary"]["parsed"] == 3
    assert overview["views_summary"]["avg"] == 1200


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------


def test_generate_channel_json():
    payload = generate_channel_json(make_channel())
    assert '"name": "Canal Demo"' in payload
    assert '"video_id": "id1"' in payload


def test_generate_videos_csv():
    csv_text = generate_videos_csv(make_channel().videos)
    assert csv_text.startswith("\ufeff")  # BOM para Excel
    assert "title,url,video_id" in csv_text
    assert "#test #youtube" in csv_text


def test_generate_channel_markdown():
    md = generate_channel_markdown(make_channel())
    assert "# Canal — Canal Demo" in md
    assert "@canaldemo" in md
    assert "| Vídeo 1" in md


def test_export_channel(tmp_path: Path):
    out = export_channel(make_channel(), tmp_path / "canal.json", fmt="json")
    assert out.exists()
    assert '"Canal Demo"' in out.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        export_channel(make_channel(), tmp_path / "canal.xml", fmt="xml")


def test_export_videos(tmp_path: Path):
    out = export_videos(make_channel().videos, tmp_path / "videos.csv", fmt="csv")
    assert out.exists()
    assert "Vídeo 1" in out.read_text(encoding="utf-8")
