"""Tests del prompt de producción derivado de letras (youber.script.prompt)."""

from __future__ import annotations

from pathlib import Path

from youber.music.models import Mood, Track
from youber.music.selector import TrackMatch, theme_profile
from youber.research.patterns import channel_overview
from youber.script.prompt import (
    VideoBrief,
    brief_keywords,
    brief_to_script,
    build_video_brief,
)

SAD_TEXT = (
    "La noche cae y el dolor no se va, lágrimas en la soledad, "
    "todo está perdido, adiós, la tristeza me acompaña."
)


def _insights():
    from youber.cli.workflow_cli import demo_channel

    return channel_overview(demo_channel())


def _track_match() -> TrackMatch:
    return TrackMatch(
        track_id="abc",
        title="Antes de desaparecer",
        artist="Skyzo",
        score=2.7,
        matched_themes=["tristeza"],
        reason="letra comparte tema tristeza (0.90)",
    )


def test_brief_con_perfil_elegido():
    brief = build_video_brief(
        _insights(),
        topic="Mi vídeo",
        duration=45,
        profile=theme_profile(SAD_TEXT),
        track_match=_track_match(),
    )
    assert isinstance(brief, VideoBrief)
    assert brief.topic == "Mi vídeo"
    assert brief.target_duration == 45
    assert brief.tone == "melancólico y nostálgico"
    assert brief.sentiment == "negative"
    assert brief.music_mood == Mood.SAD
    assert brief.track is not None
    assert brief.track.title == "Antes de desaparecer"


def test_brief_prompt_contiene_las_claves():
    brief = build_video_brief(
        _insights(),
        topic="Mi vídeo",
        duration=45,
        profile=theme_profile(SAD_TEXT),
        track_match=_track_match(),
    )
    assert "Mi vídeo" in brief.prompt
    assert "melancólico" in brief.prompt
    assert "B-roll" in brief.prompt
    assert "Antes de desaparecer" in brief.prompt
    assert "tristeza" in brief.prompt


def test_brief_keywords_usa_hashtags_y_palabras():
    keywords = brief_keywords(_insights(), theme_profile(SAD_TEXT))
    assert keywords
    assert len(keywords) <= 8
    assert "python" in keywords


def test_brief_sin_track_ni_perfil():
    brief = build_video_brief(_insights(), topic="Demo", duration=30)
    assert brief.track is None
    assert brief.tone == "neutro y descriptivo"
    assert "Demo" in brief.prompt


def test_brief_duracion_por_defecto_usa_media_del_canal():
    brief = build_video_brief(_insights(), topic="Demo")
    assert brief.target_duration > 0


def test_brief_to_script_hereda_prompt():
    brief = build_video_brief(
        _insights(),
        topic="Mi vídeo",
        duration=45,
        profile=theme_profile(SAD_TEXT),
        track_match=_track_match(),
    )
    script = brief_to_script(brief, _insights())
    assert script.topic == "Mi vídeo"
    assert script.total_duration == brief.target_duration
    assert script.music_mood == brief.music_mood
    assert len(script.scenes) == 7


def test_selector_y_prompt_juntos():
    """Integración ligera: catálogo → canción → brief (sin red ni FFmpeg)."""
    from youber.music.selector import select_best_track

    tracks = [
        Track(
            id="sad",
            file_path=Path("music/sad.mp3"),
            title="Adiós",
            duration=100.0,
            file_hash="h1",
            lyrical_themes={"tristeza": 0.9},
            lyrical_sentiment="negative",
        ),
        Track(
            id="happy",
            file_path=Path("music/happy.mp3"),
            title="Alegría",
            duration=100.0,
            file_hash="h2",
            lyrical_themes={"felicidad": 0.9},
            lyrical_sentiment="positive",
        ),
    ]
    profile = theme_profile(SAD_TEXT)
    match = select_best_track(tracks, profile)
    assert match is not None and match.track_id == "sad"
    brief = build_video_brief(
        _insights(), topic="Noche", duration=30, profile=profile, track_match=match
    )
    assert brief.track is not None
    assert brief.track.id == "sad"
    assert brief.music_mood == Mood.SAD
