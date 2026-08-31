"""Tests de la CLI ``youber-research`` (sin red: analizadores mockeados)."""

import asyncio
from pathlib import Path

import pytest

from youber.cli.research_cli import (
    build_parser,
    detect_target,
    infer_format,
)
from youber.research.data_models import ChannelData, VideoData

CHANNEL_URL = "https://www.youtube.com/@canaldemo"
VIDEO_URL = "https://www.youtube.com/watch?v=abc123def45"


# ---------------------------------------------------------------------------
# Parser de argumentos
# ---------------------------------------------------------------------------


def test_parser_defaults():
    args = build_parser().parse_args([CHANNEL_URL])
    assert args.url == CHANNEL_URL
    assert args.max_videos == 10
    assert args.output is None
    assert args.format is None
    assert args.api is False
    assert args.html is False
    assert args.insights is False


def test_parser_flags():
    args = build_parser().parse_args(
        [CHANNEL_URL, "-n", "20", "-o", "out.csv", "-f", "csv", "--api", "--insights"]
    )
    assert args.max_videos == 20
    assert args.output == "out.csv"
    assert args.format == "csv"
    assert args.api is True
    assert args.insights is True


def test_parser_api_html_mutually_exclusive():
    with pytest.raises(SystemExit):
        build_parser().parse_args([CHANNEL_URL, "--api", "--html"])


# ---------------------------------------------------------------------------
# Detección de objetivo
# ---------------------------------------------------------------------------


def test_detect_target_channel():
    assert detect_target("https://www.youtube.com/@python") == "channel"
    assert detect_target("https://www.youtube.com/channel/UCabc123") == "channel"
    assert detect_target("@python") == "channel"


def test_detect_target_video():
    assert detect_target("https://www.youtube.com/watch?v=abc123def45") == "video"
    assert detect_target("https://youtu.be/abc123def45") == "video"
    assert detect_target("abc123def45") == "video"


# ---------------------------------------------------------------------------
# Resolución de formato
# ---------------------------------------------------------------------------


def test_infer_format_explicit_wins():
    assert infer_format("out.csv", "json") == "json"
    assert infer_format("out.unknown", "md") == "md"


def test_infer_format_from_extension():
    assert infer_format("out.csv", None) == "csv"
    assert infer_format("out.json", None) == "json"
    assert infer_format("out.md", None) == "md"
    assert infer_format("out.MARKDOWN", None) == "md"


def test_infer_format_none():
    assert infer_format(None, None) is None
    assert infer_format("out.unknown", None) is None


# ---------------------------------------------------------------------------
# Flujo completo (analizadores mockeados)
# ---------------------------------------------------------------------------


def _fake_channel() -> ChannelData:
    return ChannelData(
        name="Canal Demo",
        url=CHANNEL_URL,
        handle="canaldemo",
        subscribers="12,3 K",
        videos=[
            VideoData(
                title="Vídeo de prueba #1",
                url="https://www.youtube.com/watch?v=abc123def45",
                video_id="abc123def45",
                views="1,2 K",
                duration="12:34",
                publish_date="2026-08-15",
                hashtags=["test"],
                channel_name="Canal Demo",
                channel_url=CHANNEL_URL,
            )
        ],
    )


def _fake_video() -> VideoData:
    return _fake_channel().videos[0]


class FakeChannelAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key

    async def analyze(self, url, max_videos=10, mode="html"):
        return _fake_channel()


class FakeVideoAnalyzer:
    def __init__(self, api_key=None):
        self.api_key = api_key

    async def analyze(self, url, mode="html"):
        return _fake_video()


@pytest.fixture
def mock_analyzers(monkeypatch):
    monkeypatch.setattr("youber.cli.research_cli.ChannelAnalyzer", FakeChannelAnalyzer)
    monkeypatch.setattr("youber.cli.research_cli.VideoAnalyzer", FakeVideoAnalyzer)


async def _run_with(args):
    from youber.cli.research_cli import _run

    await _run(args)


def test_run_channel_csv(tmp_path: Path, mock_analyzers):
    out = tmp_path / "canal.csv"
    args = build_parser().parse_args([CHANNEL_URL, "-o", str(out)])
    asyncio.run(_run_with(args))
    assert out.exists()
    assert "Vídeo de prueba #1" in out.read_text(encoding="utf-8")


def test_run_channel_markdown_with_insights(tmp_path: Path, mock_analyzers):
    out = tmp_path / "canal.md"
    args = build_parser().parse_args([CHANNEL_URL, "-o", str(out), "--insights"])
    asyncio.run(_run_with(args))
    content = out.read_text(encoding="utf-8")
    assert "# Canal — Canal Demo" in content
    assert "## Insights" in content
    assert "#test" in content


def test_run_video_json(tmp_path: Path, mock_analyzers):
    out = tmp_path / "video.json"
    args = build_parser().parse_args([VIDEO_URL, "-o", str(out)])
    asyncio.run(_run_with(args))
    assert out.exists()
    assert '"title": "Vídeo de prueba #1"' in out.read_text(encoding="utf-8")


def test_run_video_markdown(tmp_path: Path, mock_analyzers):
    out = tmp_path / "video.md"
    args = build_parser().parse_args([VIDEO_URL, "-o", str(out), "--insights"])
    asyncio.run(_run_with(args))
    content = out.read_text(encoding="utf-8")
    assert "# Vídeo — Vídeo de prueba #1" in content
    assert "Insights" in content


def test_run_unknown_format_raises(tmp_path: Path, mock_analyzers):
    out = tmp_path / "canal.xyz"
    args = build_parser().parse_args([CHANNEL_URL, "-o", str(out)])
    with pytest.raises(SystemExit):
        asyncio.run(_run_with(args))
