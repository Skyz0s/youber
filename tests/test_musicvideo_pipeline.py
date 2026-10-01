"""Tests de la tubería del videoclip (``youber.musicvideo.pipeline`` y CLI).

Los unitarios son offline (sin FFmpeg). El de punta a punta usa el backend
``StubClient`` (MP4 sintético con FFmpeg) y se salta si no hay FFmpeg: prueba
las dos líneas de producción sin GPU ni ComfyUI.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from youber.audio._ffmpeg import probe_duration, run_command
from youber.genvideo.client import StubClient
from youber.genvideo.models import Resolution
from youber.genvideo.runner import requests_from_shot_plan
from youber.musicvideo.cli import _client_for, build_parser
from youber.musicvideo.director import direct_song, plan_to_shot_plan
from youber.musicvideo.models import MusicVideoError
from youber.musicvideo.pipeline import (
    SongMeasurement,
    build_plan,
    load_lyrics,
    run_musicvideo,
)
from youber.sync.timestamps import LyricsDocument, SyncLine

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="Requiere FFmpeg/ffprobe")


def _timed_document() -> LyricsDocument:
    return LyricsDocument(
        lines=[
            SyncLine(start=0, text="camino solo por la ciudad"),
            SyncLine(start=5, text="brilla el mar en tus ojos"),
            SyncLine(start=10, text="brilla el mar en tus ojos"),
            SyncLine(start=15, text="y el tiempo se detiene"),
        ],
        timed=True,
        source="lrc",
    )


# --- puente ShotPlan -> ClipRequest ----------------------------------------


def test_requests_from_shot_plan_respeta_las_duraciones() -> None:
    plan = direct_song(_timed_document(), duration=20, title="Brilla", infer_profile=False)
    shot_plan = plan_to_shot_plan(plan)
    requests = requests_from_shot_plan(shot_plan, preset=Resolution.SD)
    assert len(requests) == len(shot_plan.shots)
    for shot, request in zip(shot_plan.shots, requests, strict=True):
        assert request.duration_hint == shot.duration
        assert request.prompt == shot.prompt
        # La duración se traduce a frames 4k+1 (paso temporal de Wan 2.2).
        assert (request.config.frames - 1) % 4 == 0


# --- medición -> dirección --------------------------------------------------


def test_build_plan_usa_la_medicion() -> None:
    measurement = SongMeasurement(
        duration=20.0, beat_bpm=120.0, beat_offset=0.0, energies=[3000.0] * 20
    )
    plan = build_plan(_timed_document(), measurement, title="Brilla")
    assert plan.duration == pytest.approx(20.0)
    assert plan.timed is True
    assert len(plan.scenes) == 4
    assert plan.highlights


# --- letra: del fichero o junto al audio -----------------------------------


def test_load_lyrics_busca_junto_al_audio(tmp_path: Path) -> None:
    audio = tmp_path / "cancion.m4a"
    audio.write_bytes(b"\x00")
    (tmp_path / "cancion.lrc").write_text("[00:00.00]hola\n[00:05.00]hola\n", encoding="utf-8")
    document = load_lyrics(None, audio)
    assert document.as_plain_lines() == ["hola", "hola"]


def test_load_lyrics_sin_letra_falla(tmp_path: Path) -> None:
    with pytest.raises(MusicVideoError):
        load_lyrics(None, tmp_path / "sin_letra.m4a")


# --- CLI --------------------------------------------------------------------


def test_cli_tiene_los_dos_mandos() -> None:
    parser = build_parser()
    for command in ("plan", "render"):
        args = parser.parse_args([command, "cancion.m4a"])
        assert args.audio == "cancion.m4a"


def test_cli_backend_stub_toma_las_dimensiones_del_preset() -> None:
    from youber.genvideo.models import GenConfig

    client = _client_for("stub", Resolution.SD)
    assert isinstance(client, StubClient)
    settings = GenConfig.for_resolution(Resolution.SD)
    assert (client.width, client.height) == (settings.width, settings.height)


# --- punta a punta (stub + FFmpeg) -----------------------------------------


async def _make_song(path: Path, seconds: float) -> None:
    await run_command(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(path),
        ]
    )


@needs_ffmpeg
def test_run_musicvideo_produce_las_dos_lineas(tmp_path: Path) -> None:
    song = tmp_path / "cancion.m4a"
    asyncio.run(_make_song(song, 20.0))
    lyrics = tmp_path / "cancion.lrc"
    lyrics.write_text(
        "[00:00.00]camino solo por la ciudad\n"
        "[00:05.00]brilla el mar en tus ojos\n"
        "[00:10.00]brilla el mar en tus ojos\n"
        "[00:15.00]y el tiempo se detiene\n",
        encoding="utf-8",
    )
    from youber.genvideo.models import GenConfig

    preset = Resolution.SD
    settings = GenConfig.for_resolution(preset)
    client = StubClient(width=settings.width, height=settings.height, fps=settings.fps)

    result = asyncio.run(
        run_musicvideo(
            song,
            lyrics=lyrics,
            title="Brilla",
            out_dir=tmp_path / "out",
            client=client,
            preset=preset,
            short_seconds=10.0,
            min_short_seconds=6.0,
            max_short_seconds=20.0,
            keep_awake=False,
        )
    )

    assert result.video is not None and result.video.exists()
    assert result.short is not None and result.short.exists()
    assert asyncio.run(probe_duration(result.video)) > 0
    assert asyncio.run(probe_duration(result.short)) > 0
    assert len(result.clips) == len(result.plan.scenes)
    assert result.short_clips
