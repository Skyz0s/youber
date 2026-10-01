"""Tubería del videoclip: de la canción a **los dos vídeos**.

Une el director (:mod:`youber.musicvideo`) con el motor: mide la canción
(duración, pulso y energía), dirige, pide los clips al generador local
(:mod:`youber.genvideo`) y monta con el motor de vídeo (:mod:`youber.video`).

Salen **dos líneas de producción** de la misma dirección:

- el **videoclip** completo (horizontal, duración = canción);
- el **corto vertical** de los mejores momentos, **re-renderizado** en 9:16
  (no recortado del horizontal): el encuadre del estribillo se piensa para
  vertical, que es donde se comparte.

Todo el trabajo pesado (medición, generación) es asíncrono. La generación usa
un backend enchufable: ComfyUI en producción y ``StubClient`` en los tests
(MP4 sintético con FFmpeg, sin GPU).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from youber.audio._ffmpeg import probe_duration
from youber.genvideo.client import GenerationClient
from youber.genvideo.models import (
    BatchReport,
    ClipRequest,
    GenConfig,
    JobStatus,
    Resolution,
)
from youber.genvideo.queue import JobQueue
from youber.genvideo.runner import NightlyRunner, requests_from_shot_plan, slugify
from youber.musicvideo.director import direct_song, plan_to_script, plan_to_shot_plan
from youber.musicvideo.models import MusicVideoError, MusicVideoPlan
from youber.script.builder import build_project
from youber.script.models import Script
from youber.sync.timestamps import LyricsDocument, parse_lyrics_file
from youber.video.editor import VideoEditor
from youber.video.models import Project
from youber.visuals.models import Aspect
from youber.visuals.short import extract_window, loudness_profile
from youber.visuals.tempo import detect_grid

#: Resolución de entrega del videoclip y del corto vertical.
FULL_RESOLUTION = (1920, 1080)
SHORT_RESOLUTION = (1080, 1920)

#: Preset de generación por defecto: 480p/Turbo, el barato (~2-3 min por clip).
DEFAULT_PRESET = Resolution.SD


class SongMeasurement(BaseModel):
    """Lo que se mide de la canción antes de dirigir.

    Attributes:
        duration: Duración (segundos), medida con FFmpeg.
        beat_bpm: Pulso estimado (BPM) o ``None`` si no se pudo medir.
        beat_offset: Segundo del primer pulso, si se midió.
        energies: Perfil de energía (RMS por ventana) para tramos y cortes.
    """

    duration: float = Field(gt=0)
    beat_bpm: float | None = Field(default=None, gt=0)
    beat_offset: float | None = Field(default=None, ge=0)
    energies: list[float] = Field(default_factory=list)


class MusicVideoResult(BaseModel):
    """Resultado de la tubería: los dos vídeos y de dónde salen.

    Attributes:
        plan: La dirección del videoclip (escenas, tramos, mejores momentos).
        video: El videoclip completo (si se pidió).
        short: El corto vertical (si había mejores momentos y se pidió).
        measurement: Lo medido de la canción.
        full_report: Informe del lote de clips del videoclip.
        short_report: Informe del lote de clips del corto.
        clips: Clips del videoclip, en orden de montaje.
        short_clips: Clips del corto, en orden de montaje.
    """

    plan: MusicVideoPlan
    video: Path | None = None
    short: Path | None = None
    measurement: SongMeasurement
    full_report: BatchReport | None = None
    short_report: BatchReport | None = None
    clips: list[Path] = Field(default_factory=list)
    short_clips: list[Path] = Field(default_factory=list)


async def measure_song(
    audio: str | Path, *, with_energy: bool = True, max_seconds: float = 180.0
) -> SongMeasurement:
    """Mide la canción: duración, pulso y perfil de energía.

    El pulso y la energía son *best-effort*: si FFmpeg o el análisis fallan, se
    sigue sin ellos (el videoclip se dirige igual, solo pierde el alineado al
    beat y la elección por energía).
    """
    path = Path(audio)
    duration = await probe_duration(path)
    bpm: float | None = None
    offset: float | None = None
    try:
        grid = await detect_grid(path, max_seconds=max_seconds)
        if grid.detected:
            bpm, offset = grid.bpm, grid.offset
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        logger.warning(f"Sin pulso medido en «{path.name}»: {exc}")
    energies: list[float] = []
    if with_energy:
        try:
            energies = list(await loudness_profile(path))
        except (RuntimeError, FileNotFoundError, OSError) as exc:
            logger.warning(f"Sin perfil de energía de «{path.name}»: {exc}")
    return SongMeasurement(
        duration=duration, beat_bpm=bpm, beat_offset=offset, energies=energies
    )


def load_lyrics(
    lyrics: str | Path | LyricsDocument | None, audio: str | Path
) -> LyricsDocument:
    """Carga la letra: del objeto, del fichero o de un hermano del audio.

    Si no se indica letra, se busca ``<audio>.lrc``/``.txt``/``.srt``/``.json``
    junto al audio (mismo nombre base).

    Raises:
        MusicVideoError: si no hay letra por ningún lado.
    """
    if isinstance(lyrics, LyricsDocument):
        return lyrics
    if lyrics is not None:
        return parse_lyrics_file(lyrics)
    source = Path(audio)
    for suffix in (".lrc", ".txt", ".srt", ".json"):
        candidate = source.with_suffix(suffix)
        if candidate.exists():
            logger.info(f"Letra encontrada junto al audio: {candidate.name}")
            return parse_lyrics_file(candidate)
    raise MusicVideoError(
        "Sin letra: pasa un fichero con --lyrics o deja «<audio>.lrc/.txt» junto al audio"
    )


def build_plan(
    document: LyricsDocument,
    measurement: SongMeasurement,
    *,
    title: str = "",
    artist: str | None = None,
    short_seconds: float = 45.0,
    min_short_seconds: float = 20.0,
    max_short_seconds: float = 60.0,
) -> MusicVideoPlan:
    """Dirige el videoclip con la letra y la canción ya medidas."""
    return direct_song(
        document,
        title=title,
        artist=artist,
        duration=measurement.duration,
        energies=measurement.energies or None,
        short_seconds=short_seconds,
        min_short_seconds=min_short_seconds,
        max_short_seconds=max_short_seconds,
    )


async def generate_clips(
    requests: Sequence[ClipRequest],
    output_dir: str | Path,
    *,
    client: GenerationClient,
    preset: Resolution = DEFAULT_PRESET,
    seed_base: int = 42,
    verify: bool = True,
    keep_awake: bool = False,
) -> tuple[BatchReport, JobQueue]:
    """Genera los clips del lote con el backend dado (cola aislada por carpeta)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    queue = JobQueue(out / "queue.json")
    runner = NightlyRunner(
        client=client,
        config=GenConfig.for_resolution(preset),
        queue=queue,
        output_dir=out,
        verify=verify,
        keep_awake=keep_awake,
    )
    report = await runner.run(list(requests))
    return report, queue


def _clips_in_order(requests: Sequence[ClipRequest], queue: JobQueue) -> list[Path]:
    """Rutas de los clips en orden de montaje (repite el anterior si falta uno).

    Un clip que no salió (falló la generación) no debe romper el montaje: se
    reutiliza el anterior para cubrir ese hueco, que es preferible a dejar el
    vídeo a medias.
    """
    by_id = {request.id: request for request in queue.requests}
    clips: list[Path] = []
    for request in requests:
        done = by_id.get(request.id)
        if done is not None and done.status == JobStatus.DONE and done.output:
            clips.append(Path(done.output))
        elif clips:
            logger.warning(f"Clip ausente «{request.label}»: se repite el anterior")
            clips.append(clips[-1])
        else:
            raise MusicVideoError(f"No se generó ni el primer clip («{request.label}»)")
    return clips


def build_project_for(
    script: Script,
    clips: Sequence[str | Path],
    *,
    resolution: tuple[int, int],
    fps: int = 30,
) -> Project:
    """Proyecto de montaje: un clip por línea, el texto de la letra encima.

    Sin música en el proyecto: la banda sonora se pasa al renderizar, así vale
    cualquier audio (la canción entera o el trozo del corto) sin depender del
    catálogo.
    """
    return build_project(
        script,
        clips,
        library=None,
        resolution=resolution,
        fps=fps,
        clip_audio=False,
        with_texts=True,
    )


async def render_line(project: Project, output: str | Path, music_path: str | Path) -> Path:
    """Renderiza un proyecto con su banda sonora y devuelve la ruta del vídeo."""
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    editor = VideoEditor()
    await editor.render(project, target, music_path=str(music_path))
    return target


async def run_musicvideo(
    audio: str | Path,
    *,
    lyrics: str | Path | LyricsDocument | None = None,
    title: str = "",
    artist: str | None = None,
    out_dir: str | Path,
    client: GenerationClient,
    preset: Resolution = DEFAULT_PRESET,
    make_full: bool = True,
    make_short: bool = True,
    short_seconds: float = 45.0,
    min_short_seconds: float = 20.0,
    max_short_seconds: float = 60.0,
    seed_base: int = 42,
    fps: int = 30,
    verify: bool = True,
    keep_awake: bool = False,
    measurement: SongMeasurement | None = None,
) -> MusicVideoResult:
    """Produce las dos líneas: el videoclip y el corto vertical.

    Args:
        audio: Fichero de la canción.
        lyrics: Letra (objeto, fichero o ``None`` para buscarla junto al audio).
        title: Título de la canción (nombra los ficheros y el guion).
        artist: Intérprete.
        out_dir: Carpeta de salida (clips y vídeos).
        client: Backend de generación (ComfyUI o ``StubClient``).
        preset: Preset medido (``480p``/``720p``).
        make_full: Generar el videoclip completo.
        make_short: Generar el corto vertical de los mejores momentos.
        short_seconds: Duración deseada del corto.
        min_short_seconds: Duración mínima del corto.
        max_short_seconds: Duración máxima del corto.
        seed_base: Semilla base de los clips.
        fps: Fotogramas por segundo del montaje.
        verify: Verificar la calidad de los clips generados.
        keep_awake: Desactivar la suspensión del equipo durante la generación.
        measurement: Medición ya hecha (se mide si falta).

    Returns:
        El :class:`MusicVideoResult` con los vídeos y los informes.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    document = load_lyrics(lyrics, audio)
    song = measurement or await measure_song(audio)
    plan = build_plan(
        document,
        song,
        title=title,
        artist=artist,
        short_seconds=short_seconds,
        min_short_seconds=min_short_seconds,
        max_short_seconds=max_short_seconds,
    )
    slug = slugify(title or Path(audio).stem)
    result = MusicVideoResult(plan=plan, measurement=song)

    if make_full:
        shot_plan = plan_to_shot_plan(plan, fps=fps)
        requests = requests_from_shot_plan(shot_plan, preset=preset, seed_base=seed_base)
        report, queue = await generate_clips(
            requests,
            out / "clips_full",
            client=client,
            preset=preset,
            verify=verify,
            keep_awake=keep_awake,
        )
        result.full_report = report
        result.clips = _clips_in_order(requests, queue)
        script = plan_to_script(plan)
        project = build_project_for(script, result.clips, resolution=FULL_RESOLUTION, fps=fps)
        result.video = await render_line(project, out / f"{slug}-videoclip.mp4", audio)

    if make_short:
        highlight = plan.highlights[0] if plan.highlights else None
        if highlight is None:
            logger.warning("Sin mejores momentos: no se genera el corto")
        else:
            scenes = plan.highlight_scenes(highlight)
            short_plan = plan_to_shot_plan(
                plan, scenes=scenes, aspect=Aspect.VERTICAL, fps=fps
            )
            requests = requests_from_shot_plan(short_plan, preset=preset, seed_base=seed_base)
            report, queue = await generate_clips(
                requests,
                out / "clips_short",
                client=client,
                preset=preset,
                verify=verify,
                keep_awake=keep_awake,
            )
            result.short_report = report
            result.short_clips = _clips_in_order(requests, queue)
            slice_path = await extract_window(
                audio,
                out / f"{slug}-short.m4a",
                start=highlight.start,
                duration=highlight.duration,
            )
            script = plan_to_script(plan, scenes=scenes)
            project = build_project_for(
                script, result.short_clips, resolution=SHORT_RESOLUTION, fps=fps
            )
            result.short = await render_line(project, out / f"{slug}-short.mp4", slice_path)

    return result
