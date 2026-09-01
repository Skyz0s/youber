"""Tests del generador de guiones (youber.script)."""

from __future__ import annotations

from pathlib import Path

import pytest

from youber.music.models import Mood, Track, TrackSource
from youber.script.builder import _pick_local_track, build_project, default_font_file
from youber.script.generator import _infer_mood, generate_script
from youber.script.models import SceneType
from youber.video.editor import VideoEditor


def _insights(**overrides: object) -> dict:
    """Insights sintéticos de un canal (estructura de channel_overview)."""
    data: dict = {
        "channel": {"name": "Canal Demo", "url": "https://www.youtube.com/@demo"},
        "videos_count": 4,
        "top_hashtags": [
            {"hashtag": "python", "count": 4},
            {"hashtag": "tutorial", "count": 3},
        ],
        "title_patterns": {
            "with_numbers": 3,
            "with_uppercase_words": 2,
            "with_question": 1,
            "with_vs": 1,
            "with_top_list": 2,
        },
        "duration_stats": {
            "count": 4,
            "avg_seconds": 600,
            "min_seconds": 120,
            "max_seconds": 1200,
        },
        "views_summary": {"parsed": 4, "avg": 100_000, "max": 500_000},
    }
    data.update(overrides)
    return data


def test_generate_script_estructura_completa():
    script = generate_script(_insights(), topic="Mi vídeo")
    types = [scene.type for scene in script.scenes]
    assert SceneType.HOOK in types
    assert SceneType.INTRO in types
    assert SceneType.CLIMAX in types
    assert SceneType.CTA in types
    assert types.count(SceneType.CONTENT) == 3
    assert script.total_duration == pytest.approx(600.0)  # media del canal
    assert script.source_channel == "Canal Demo"
    assert script.hashtags == ["python", "tutorial"]


def test_generate_script_duracion_explicita():
    script = generate_script(_insights(), topic="X", duration=90)
    assert script.total_duration == pytest.approx(90.0)
    assert sum(scene.duration for scene in script.scenes) == pytest.approx(90.0)


def test_generate_script_duracion_minima_por_escena():
    script = generate_script(_insights(), topic="X", duration=10)
    assert all(scene.duration >= 2.0 for scene in script.scenes)


def test_generate_script_duracion_minima_total():
    """Sin duración explícita, la media del canal tiene un mínimo (30 s)."""
    insights = _insights(duration_stats={"avg_seconds": 12.0})
    script = generate_script(insights, topic="X")
    assert script.total_duration == pytest.approx(30.0)


def test_generate_script_con_content_keywords():
    """Las keywords del contenido real del vídeo origen marcan cada escena."""
    content = ["cocina", "pasta", "restaurante"]
    script = generate_script(_insights(), topic="Mi vídeo", content_keywords=content)
    assert script.scenes
    for scene in script.scenes:
        assert "cocina" in scene.keywords
        assert "pasta" in scene.keywords


def test_generate_script_sin_content_keywords_fallback():
    """Sin contenido real, cada escena mantiene las keywords genéricas."""
    script = generate_script(_insights(), topic="X")
    for scene in script.scenes:
        assert scene.keywords  # no vacías


def test_infer_mood_con_content_keywords():
    """El contenido del vídeo manda sobre la duración para la música."""
    sad = _infer_mood(_insights(duration_stats={"avg_seconds": 120}), ["triste", "perdida"])
    assert sad == Mood.SAD
    energetic = _infer_mood(
        _insights(duration_stats={"avg_seconds": 1200}), ["fiesta", "carrera"]
    )
    assert energetic == Mood.ENERGETIC


def test_generate_script_tema_con_mood():
    script = generate_script(_insights(), topic="X", music_mood=Mood.RELAXING)
    assert script.music_mood == Mood.RELAXING


def test_hook_text_con_preguntas():
    insights = _insights()
    insights["title_patterns"] = {**insights["title_patterns"], "with_question": 3}
    script = generate_script(insights, topic="asyncio")
    hook = next(scene for scene in script.scenes if scene.type == SceneType.HOOK)
    assert hook.text == "¿Asyncio?"


def test_infer_mood():
    assert _infer_mood(_insights(duration_stats={"avg_seconds": 120})) == Mood.ENERGETIC
    assert _infer_mood(_insights(duration_stats={"avg_seconds": 600})) == Mood.HAPPY
    assert _infer_mood(_insights(duration_stats={"avg_seconds": 1200})) == Mood.EPIC


def test_script_timeline():
    script = generate_script(_insights(), topic="X", duration=100)
    intervals = script.timeline()
    assert len(intervals) == len(script.scenes)
    assert intervals[0][0] == 0.0
    assert intervals[-1][1] == pytest.approx(100.0)
    # contiguos
    for (_, fin), (inicio, _) in zip(intervals, intervals[1:], strict=False):
        assert fin == pytest.approx(inicio)


def test_build_project_sin_biblioteca(tmp_path: Path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    script = generate_script(_insights(), topic="Mi vídeo", duration=60)
    project = build_project(script, clips=[clip])
    assert len(project.clips) == len(script.scenes)
    assert project.music_track_id is None
    assert len(project.text_overlays) == len(script.scenes)
    # los textos arrancan en orden y duran lo de cada escena
    start = 0.0
    for overlay, scene in zip(project.text_overlays, script.scenes, strict=False):
        assert overlay.start_time == pytest.approx(start)
        assert overlay.duration == pytest.approx(scene.duration)
        start += scene.duration


def test_build_project_sin_clips():
    script = generate_script(_insights(), topic="X")
    with pytest.raises(ValueError):
        build_project(script, clips=[])


def test_build_project_con_musica_local(tmp_path: Path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    music_file = tmp_path / "musica.mp3"
    music_file.write_bytes(b"fake")

    class _FakeLibrary:
        def suggest(self, mood=None, text=None, limit=5):
            return [self._track()]

        def all(self):
            return [self._track()]

        def _track(self):
            return Track(
                id="t1",
                file_path=music_file,
                title="Mi tema",
                artist="Yo",
                duration=180.0,
                file_hash="h1",
                source=TrackSource.LOCAL,
            )

    script = generate_script(_insights(), topic="X", music_mood=Mood.EPIC)
    project = build_project(script, clips=[clip], library=_FakeLibrary())  # type: ignore[arg-type]
    assert project.music_track_id == "t1"


def test_pick_local_track_ignora_cloud(tmp_path: Path):
    """Solo pistas LOCALES son editables (las cloud no tienen fichero)."""
    local = Track(
        id="t1",
        file_path=Path("/tmp/a.mp3"),
        title="Local",
        duration=100.0,
        file_hash="h1",
        source=TrackSource.LOCAL,
    )
    cloud = Track(
        id="t2",
        file_path=Path("cloud:youtube:xyz"),
        title="Cloud",
        duration=100.0,
        file_hash="cloud:youtube:xyz",
        source=TrackSource.YOUTUBE,
    )

    class _FakeLibrary:
        def suggest(self, mood=None, text=None, limit=5):
            return [cloud, local]

        def all(self):
            return [cloud, local]

    script = generate_script(_insights(), topic="X")
    picked = _pick_local_track(_FakeLibrary(), script)  # type: ignore[arg-type]
    assert picked is not None
    assert picked.source == TrackSource.LOCAL


def test_build_project_editor_inyectado(tmp_path: Path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    script = generate_script(_insights(), topic="X", duration=45)
    editor = VideoEditor()
    project = build_project(script, clips=[clip], editor=editor)
    assert project.fps == 30
    assert project.resolution == (1920, 1080)
    assert project.title == "X"


def test_default_font_file():
    font = default_font_file()
    if font:
        assert Path(font).exists()
