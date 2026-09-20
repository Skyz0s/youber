"""Renderiza un vídeo **creado de cero**: plan → imágenes → clips → montaje.

Es la orquestación de la ruta C: los stills los genera el modelo
(:mod:`youber.visuals.generator`), los anima FFmpeg
(:mod:`youber.visuals.animate`) y el montaje final reutiliza el motor de
vídeo del framework (:mod:`youber.video.renderer`), así que hereda
transiciones, textos, mezcla de audio a 192 kbps y duración cuadrada con la
canción.

Los artefactos se guardan por pasos (``shots/``, ``clips/``) y se reutilizan
si ya existen: regenerar solo cuesta lo que falte (``force=True`` lo repite
todo).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from youber.audio._ffmpeg import ensure_ffmpeg, probe_duration
from youber.script.builder import default_font_file
from youber.script.models import Scene
from youber.video.editor import VideoEditor
from youber.video.models import Project, TransitionType
from youber.video.renderer import render_project
from youber.visuals.animate import DEFAULT_CRF, DEFAULT_PRESET, animate_shot
from youber.visuals.generator import ImageGenerator, create_generator
from youber.visuals.models import Aspect, ShotPlan, VisualStyle
from youber.visuals.prompts import build_shot_plan
from youber.visuals.selector import (
    AUTO_STYLE,
    StyleChoice,
    StyleSignals,
    choose_style,
)
from youber.visuals.tempo import BeatGrid

#: Callback de progreso: recibe un mensaje ya formateado.
ProgressCallback = Callable[[str], None]


class VisualResult(BaseModel):
    """Resultado de un render visual: el vídeo y de dónde sale cada plano.

    Attributes:
        video: Vídeo final renderizado.
        preview: Versión ligera para mensajería (si se pidió).
        plan: Plan de planos usado (prompts, movimientos, duraciones).
        images: Stills generados, en orden de plano.
        clips: Clips animados, en orden de plano.
        song: Canción usada como banda sonora (o ``None``).
        duration: Duración del montaje (segundos).
        generator: Generador de imagen usado (modelo o ``stub``).
        seed: Semilla base de las imágenes.
        style_choice: Cómo se resolvió el estilo (señales, puntuaciones, motivo).
    """

    video: Path
    plan: ShotPlan
    images: list[Path] = Field(default_factory=list)
    clips: list[Path] = Field(default_factory=list)
    song: Path | None = None
    duration: float = 0.0
    generator: str = ""
    seed: int = 0
    preview: Path | None = None
    style_choice: StyleChoice | None = None


def _report(on_progress: ProgressCallback | None, message: str) -> None:
    """Emite progreso si hay callback (y siempre al log)."""
    logger.debug(message)
    if on_progress is not None:
        on_progress(message)


def shot_path(workdir: Path, index: int) -> Path:
    """Ruta del still del plano ``index``."""
    return workdir / "shots" / f"shot_{index:02d}.png"


def clip_path(workdir: Path, index: int) -> Path:
    """Ruta del clip animado del plano ``index``."""
    return workdir / "clips" / f"shot_{index:02d}.mp4"


async def generate_images(
    plan: ShotPlan,
    workdir: str | Path,
    generator: ImageGenerator,
    *,
    seed: int = 1234,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> list[Path]:
    """Genera (o reutiliza) el still de cada plano del plan.

    Args:
        plan: Plan de planos.
        workdir: Directorio de trabajo (los stills van a ``shots/``).
        generator: Generador de imágenes.
        seed: Semilla base; cada plano usa ``seed + índice``.
        force: Si ``True``, regenera aunque el fichero exista.
        on_progress: Callback de progreso (opcional).

    Returns:
        Las rutas de los stills, en orden de plano. También quedan anotadas
        en ``plan.shots[i].image``.
    """
    base = Path(workdir)
    (base / "shots").mkdir(parents=True, exist_ok=True)
    width, height = plan.aspect.generate_size()
    paths: list[Path] = []
    for shot in plan.shots:
        target = shot_path(base, shot.index)
        if target.exists() and target.stat().st_size > 0 and not force:
            _report(on_progress, f"[{shot.index + 1}/{len(plan.shots)}] still en disco: {target.name}")
            shot.image = target
            paths.append(target)
            continue
        _report(
            on_progress,
            f"[{shot.index + 1}/{len(plan.shots)}] generando {target.name} "
            f"({width}x{height}, {generator.name})",
        )
        data = generator.generate(shot.prompt, width=width, height=height, seed=seed + shot.index)
        target.write_bytes(data)
        shot.image = target
        paths.append(target)
    return paths


async def animate_clips(
    plan: ShotPlan,
    workdir: str | Path,
    *,
    fps: int | None = None,
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> list[Path]:
    """Anima cada still con su movimiento de cámara (Ken Burns).

    Args:
        plan: Plan de planos (usa ``shot.motion``, ``shot.duration`` y
            ``shot.image``; requiere haber generado antes los stills).
        workdir: Directorio de trabajo (los clips van a ``clips/``).
        fps: Fotogramas por segundo (por defecto, los del plan).
        crf: Calidad de ``libx264`` de los clips intermedios.
        preset: Preset de ``libx264``.
        force: Si ``True``, reanima aunque el clip exista.
        on_progress: Callback de progreso (opcional).

    Returns:
        Las rutas de los clips, en orden de plano.

    Raises:
        ValueError: si algún plano no tiene still generado.
    """
    base = Path(workdir)
    (base / "clips").mkdir(parents=True, exist_ok=True)
    size = plan.aspect.render_size()
    frame_rate = fps or plan.fps
    paths: list[Path] = []
    for shot in plan.shots:
        if shot.image is None:
            raise ValueError(f"El plano {shot.index} no tiene still: genera antes las imágenes")
        target = clip_path(base, shot.index)
        if target.exists() and target.stat().st_size > 0 and not force:
            _report(on_progress, f"[{shot.index + 1}/{len(plan.shots)}] clip en disco: {target.name}")
            shot.clip = target
            paths.append(target)
            continue
        _report(
            on_progress,
            f"[{shot.index + 1}/{len(plan.shots)}] animando {target.name} "
            f"({shot.motion.value}, {shot.duration:.1f} s)",
        )
        await animate_shot(
            shot.image,
            target,
            duration=shot.duration,
            motion=shot.motion,
            size=size,
            fps=frame_rate,
            crf=crf,
            preset=preset,
        )
        shot.clip = target
        paths.append(target)
    return paths


def build_visual_project(
    plan: ShotPlan,
    clips: Sequence[str | Path],
    *,
    title: str | None = None,
    scenes: Sequence[Scene] = (),
    transition: TransitionType = TransitionType.CROSSFADE,
    music_volume: float = 1.0,
    texts: bool = False,
) -> Project:
    """Monta el :class:`Project` de los clips ya animados.

    Args:
        plan: Plan de planos (dicta duraciones, formato y transición).
        clips: Clips animados, en orden de plano.
        title: Título del proyecto (por defecto: el tema del plan).
        scenes: Escenas del guion; si ``texts=True``, sus textos se
            superponen al principio de cada escena.
        transition: Tipo de transición entre planos.
        music_volume: Volumen de la banda sonora (0..1). La canción *es* el
            audio de la pieza, así que va a 1.0.
        texts: Si ``True``, superpone los textos de las escenas.

    Returns:
        El proyecto listo para renderizar.
    """
    editor = VideoEditor()
    project = editor.new_project(
        title=title or plan.topic,
        resolution=plan.aspect.render_size(),
        fps=plan.fps,
    )
    for index, clip in enumerate(clips):
        editor.add_clip(project, clip, duration=plan.shots[index].duration, volume=0.0)
        if index > 0:
            editor.add_transition(
                project,
                clip_index=index,
                type=transition,
                duration=plan.transition,
            )
    if texts:
        font = default_font_file()
        for scene_index, scene in enumerate(scenes):
            shot_index = plan.scene_shot_index(scene_index)
            if shot_index is None or not scene.text:
                continue
            editor.add_text(
                project,
                scene.text,
                position=scene.position,
                font_size=56 if scene.type.value == "hook" else 44,
                font_file=font,
                start_time=plan.shot_start(shot_index),
                duration=scene.duration,
            )
    project.music_volume = music_volume
    return project


async def render_visuals(
    *,
    topic: str,
    output: str | Path,
    song: str | Path | None = None,
    scenes: Sequence[Scene] = (),
    duration: float | None = None,
    aspect: Aspect | str = Aspect.LANDSCAPE,
    style: VisualStyle | str = AUTO_STYLE,
    signals: StyleSignals | None = None,
    beat_grid: BeatGrid | None = None,
    mood: str | None = None,
    tone: str | None = None,
    keywords: Sequence[str] = (),
    shots: int | None = None,
    fps: int = 30,
    transition: float | None = None,
    texts: bool = False,
    generator: ImageGenerator | None = None,
    model: str | None = None,
    steps: int = 2,
    seed: int = 1234,
    workdir: str | Path | None = None,
    crf: int = DEFAULT_CRF,
    preset: str = DEFAULT_PRESET,
    music_volume: float = 1.0,
    preview: bool = False,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> VisualResult:
    """Crea un vídeo desde cero: plan de planos, stills, animación y montaje.

    Args:
        topic: Tema del vídeo (alimenta los prompts).
        output: Fichero MP4 de salida.
        song: Canción de banda sonora (define la duración si no se indica).
        scenes: Escenas del guion (reparten los planos y los textos).
        duration: Duración objetivo del montaje (por defecto, la de la canción).
        aspect: Formato de la pieza (``16:9``, ``9:16`` o ``1:1``).
        style: Estilo visual de los planos; ``"auto"`` (por defecto) lo elige
            a partir de :mod:`youber.visuals.selector` con las ``signals``.
        signals: Señales de audio/metadatos para elegir estilo y ritmo.
        beat_grid: Rejilla de pulsos de la canción (:func:`youber.visuals.tempo.detect_grid`);
            con ella los cortes entre planos caen sobre el beat.
        mood: Mood de la música (tinte atmosférico de los prompts).
        tone: Tono narrativo del brief.
        keywords: Palabras clave para los prompts.
        shots: Número de planos (por defecto, según la duración y la energía).
        fps: Fotogramas por segundo.
        transition: Duración del fundido entre planos (segundos). ``None`` la
            deja al selector (tempo alto → fundidos cortos).
        texts: Superponer los textos del guion.
        generator: Generador de imágenes ya construido (por defecto, se crea
            con ``model``).
        model: Modelo de imagen (``None`` ⇒ generador de prueba ``stub``).
        steps: Pasos de inferencia del modelo.
        seed: Semilla base (reproducibilidad).
        workdir: Directorio de artefactos intermedios (por defecto: junto al
            vídeo de salida, en ``<salida>_work``).
        crf: Calidad de los clips intermedios.
        preset: Preset de ``libx264`` para los clips intermedios.
        music_volume: Volumen de la canción en la mezcla final.
        preview: Generar también un preview ligero para mensajería.
        force: Ignorar stills y clips ya existentes.
        on_progress: Callback de progreso (opcional).

    Returns:
        El :class:`VisualResult` con el vídeo y los artefactos.

    Raises:
        ValueError: si no hay canción ni duración explícita.
        RuntimeError: si FFmpeg falla.
    """
    ensure_ffmpeg()
    aspect = Aspect(aspect)
    target = Path(output)

    song_path = Path(song) if song is not None else None
    song_duration: float | None = None
    if song_path is not None:
        song_duration = await probe_duration(song_path)
    total = float(duration) if duration else song_duration
    if not total or total <= 0:
        raise ValueError("Indica una duración o pasa una canción de la que deducirla")

    choice = choose_style(
        style,
        signals=signals,
        variation_key=f"{topic}|{aspect.value}|{seed}",
    )
    effective_transition = transition if transition is not None else choice.transition

    plan = build_shot_plan(
        topic,
        scenes,
        duration=total,
        aspect=aspect,
        style=choice.style,
        mood=mood,
        tone=tone,
        keywords=keywords,
        shots=shots,
        transition=effective_transition,
        fps=fps,
        motion_offset=choice.motion_offset,
        seconds_per_shot=choice.seconds_per_shot,
        beat_grid=beat_grid,
    )
    plan.style_reason = choice.reason
    plan.style_scores = dict(choice.scores)
    plan.style_signals = {axis: round(value, 4) for axis, value in choice.signals.as_axes().items()}
    plan.seed = seed
    _report(
        on_progress,
        f"Plan: {len(plan.shots)} planos · {plan.total_duration:.1f} s · "
        f"{aspect.value} {aspect.render_size()[0]}x{aspect.render_size()[1]} · "
        f"estilo {choice.style.value}",
    )
    _report(on_progress, f"🎨 {choice.reason}")
    _report(
        on_progress,
        f"🎞️  Ritmo: {plan.seconds_per_shot:g} s/plano · fundidos {plan.transition:g} s · "
        f"movimientos desde #{choice.motion_offset} · candidatos "
        f"{', '.join(choice.candidates)}",
    )
    if plan.beat_bpm:
        _report(
            on_progress,
            f"🥁 Pulso {plan.beat_bpm:.0f} BPM (primer beat {plan.beat_offset:.2f} s) · "
            + ("cortes al beat" if plan.beat_aligned else "los cortes no caben al beat"),
        )

    work = Path(workdir) if workdir is not None else target.with_name(f"{target.stem}_work")
    work.mkdir(parents=True, exist_ok=True)
    images = await generate_images(plan, work, generator or create_generator(model, steps=steps),
                                  seed=seed, force=force, on_progress=on_progress)
    clips = await animate_clips(
        plan, work, fps=fps, crf=crf, preset=preset, force=force, on_progress=on_progress
    )

    project = build_visual_project(
        plan,
        clips,
        title=topic,
        scenes=scenes,
        transition=TransitionType.CROSSFADE,
        music_volume=music_volume,
        texts=texts,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    _report(on_progress, f"Montando (FFmpeg) → {target}")
    await render_project(
        project,
        str(target),
        music_path=str(song_path) if song_path is not None else None,
    )

    result = VisualResult(
        video=target,
        plan=plan,
        images=images,
        clips=clips,
        song=song_path,
        duration=plan.total_duration,
        generator=(generator or create_generator(model)).name,
        seed=seed,
        style_choice=choice,
    )
    if preview:
        from youber.video.preview import make_preview

        _report(on_progress, "Generando preview ligero (480p · audio estéreo 128 kbps)...")
        result.preview = Path(await make_preview(target))
    _report(on_progress, f"Vídeo creado: {target} ({result.duration:.1f} s)")
    return result
