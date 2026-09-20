"""CLI del generador visual: ``youber-visuals``.

Crea un vídeo desde cero (planos generados + animación + canción) y, si se
pide, también el corte vertical para Shorts.

Ejemplos:
    # Máster 16:9 con la canción completa, planos generados en la GPU
    youber-visuals --topic "el paso del tiempo" --song Ira/Antesdelatardecer.wav \\
        --out out/ --model stabilityai/sdxl-turbo

    # Vertical de 75 s del estribillo (dos ficheros de una pasada)
    youber-visuals --topic "..." --song cancion.wav --out out/ \\
        --aspect 9:16 --short 75

    # Sin GPU: mismo flujo con el generador de prueba (tests/CI)
    youber-visuals --topic "prueba" --song cancion.wav --out out/ --model stub
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console

from youber.audio._ffmpeg import probe_duration
from youber.visuals.generator import DEFAULT_MODEL, create_generator
from youber.visuals.models import Aspect, VisualStyle
from youber.visuals.render import render_visuals
from youber.visuals.selector import AUTO_STYLE, StyleSignals, build_signals
from youber.visuals.short import DEFAULT_SHORT_DURATION, extract_window, pick_window
from youber.visuals.tempo import BeatGrid

console = Console()


def _slug(text: str) -> str:
    """Nombre de fichero seguro a partir del tema."""
    safe = [char if char.isalnum() else "-" for char in text.lower()]
    return "-".join(part for part in "".join(safe).split("-") if part)[:60] or "video"


async def _song_signals(
    song: Path, *, topic: str = "", mood: str | None = None
) -> tuple[StyleSignals, BeatGrid | None]:
    """Señales de la pieza y su rejilla de pulsos.

    La energía y la dinámica salen de la canción (RMS por segundo) y el pulso
    se mide por onsets (:func:`youber.visuals.tempo.detect_grid`); el tema
    (``--topic``) hace de metadatos, así que sus palabras cuentan para el
    estilo igual que lo harían el título y las etiquetas de YouTube. Si el
    análisis de audio falla, el render sigue con lo que haya.
    """
    from youber.visuals.short import loudness_profile
    from youber.visuals.tempo import detect_grid

    energies: list[float] | None = None
    try:
        energies = await loudness_profile(song)
    except (RuntimeError, FileNotFoundError, OSError) as error:  # pragma: no cover - FFmpeg
        console.print(f"⚠️  No se pudo medir el audio ({error}); el tema manda")

    grid: BeatGrid | None = None
    try:
        grid = await detect_grid(song)
        if grid.detected:
            console.print(
                f"🥁 Pulso: [bold]{grid.bpm:.0f} BPM[/] · primer beat {grid.offset:.2f} s "
                f"(confianza {grid.confidence:.2f}, fase {grid.phase_strength:.2f})"
            )
        if grid.reliable():
            console.print("🔪 Los planos se cortarán al beat")
        else:
            console.print("🔪 Pulso poco firme: los planos se reparten uniformes")
    except (RuntimeError, FileNotFoundError, OSError) as error:  # pragma: no cover - FFmpeg
        console.print(f"⚠️  No se pudo medir el pulso ({error})")

    signals = build_signals(
        energies=energies,
        tempo_bpm=grid.bpm if grid and grid.detected else None,
        metadata_text=topic,
        mood=mood,
    )
    console.print(
        f"🔎 Señales: energía {signals.energy:.2f} · tensión {signals.tension:.2f} · "
        f"valencia {signals.valence:.2f} · tempo {signals.tempo:.2f} "
        f"({', '.join(signals.sources) or 'sin datos'})"
    )
    return signals, (grid if grid and grid.reliable() else None)


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos del CLI."""
    parser = argparse.ArgumentParser(
        prog="youber-visuals",
        description="Crea un vídeo desde cero: planos generados (IA local) + animación + canción",
    )
    parser.add_argument("--topic", required=True, help="Tema del vídeo (alimenta los prompts)")
    parser.add_argument("--song", required=True, help="Canción para la banda sonora (wav/mp3/m4a)")
    parser.add_argument("-o", "--out", default="visuals", help="Directorio de salida")
    parser.add_argument(
        "--aspect",
        choices=[aspect.value for aspect in Aspect],
        default=Aspect.LANDSCAPE.value,
        help="Formato: 16:9 (máster), 9:16 (Shorts), 1:1 (default: 16:9)",
    )
    parser.add_argument(
        "--style",
        choices=[AUTO_STYLE, *(style.value for style in VisualStyle)],
        default=AUTO_STYLE,
        help=(
            "Estilo visual de los planos (default: auto → lo eligen el audio y los "
            "metadatos; también vale cinematic/dreamy/dark/vibrant/minimal)"
        ),
    )
    parser.add_argument("--mood", default=None, help="Mood de la canción (tinte de los prompts)")
    parser.add_argument(
        "--tone", default=None, help="Tono narrativo del brief (se añade a los prompts)"
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Palabra clave para los prompts (repetible)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Duración del vídeo (default: la de la canción)",
    )
    parser.add_argument("--shots", type=int, default=None, help="Número de planos (default: auto)")
    parser.add_argument("--fps", type=int, default=30, help="Fotogramas por segundo (default: 30)")
    parser.add_argument(
        "--transition",
        type=float,
        default=None,
        help="Fundido entre planos en s (default: lo decide el audio, según el tempo)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modelo de imagen (default: {DEFAULT_MODEL}; 'stub' sin GPU)")
    parser.add_argument("--steps", type=int, default=2, help="Pasos de inferencia (default: 2)")
    parser.add_argument("--seed", type=int, default=1234, help="Semilla base (default: 1234)")
    parser.add_argument("--texts", action="store_true", help="Superponer textos del guion")
    parser.add_argument(
        "--short",
        nargs="?",
        type=float,
        const=DEFAULT_SHORT_DURATION,
        default=None,
        metavar="SEGUNDOS",
        help=f"Generar además el corte vertical del estribillo (default: {DEFAULT_SHORT_DURATION:g} s)",
    )
    parser.add_argument(
        "--no-beat",
        action="store_true",
        help="No cortar los planos al beat (reparto uniforme aunque el pulso sea claro)",
    )
    parser.add_argument("--preview", action="store_true", help="Generar preview ligero (480p)")
    parser.add_argument("--force", action="store_true", help="Regenerar stills y clips existentes")
    parser.add_argument("--json", action="store_true", help="Volcar el resumen en JSON")
    return parser


async def run(args: argparse.Namespace) -> dict[str, object]:
    """Ejecuta el flujo completo del CLI y devuelve el resumen."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    song = Path(args.song)
    if not song.exists():
        raise FileNotFoundError(f"No existe la canción: {song}")
    slug = _slug(args.topic)
    aspect = Aspect(args.aspect)
    music_mood = args.mood

    generator = create_generator(args.model, steps=args.steps)
    console.print(
        f"🎨 Generador: [bold]{generator.name}[/] · {aspect.value} "
        f"{aspect.render_size()[0]}x{aspect.render_size()[1]} (modelo {aspect.generate_size()[0]}x{aspect.generate_size()[1]})"
    )

    signals, grid = await _song_signals(song, topic=args.topic, mood=args.mood)
    if args.no_beat:
        grid = None
        console.print("🔪 Cortes al beat desactivados (--no-beat)")
    if args.style == AUTO_STYLE:
        console.print(
            "🔎 Estilo automático: el audio decide (añade --style para forzar uno)"
        )

    master = await render_visuals(
        topic=args.topic,
        output=out / f"{slug}_{aspect.value.replace(':', 'x')}.mp4",
        song=song,
        duration=args.duration,
        aspect=aspect,
        style=args.style,
        signals=signals,
        beat_grid=grid,
        mood=music_mood,
        tone=args.tone,
        keywords=args.keyword,
        shots=args.shots,
        fps=args.fps,
        transition=args.transition,
        texts=args.texts,
        generator=generator,
        seed=args.seed,
        music_volume=1.0,
        preview=args.preview,
        force=args.force,
        on_progress=console.print,
    )
    plan_path = out / f"{slug}_{aspect.value.replace(':', 'x')}_plan.json"
    plan_path.write_text(master.plan.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"✅ Vídeo: [bold green]{master.video}[/] ({master.duration:.1f} s)")
    console.print(f"📄 Plan: {plan_path.name} ({len(master.plan.shots)} planos)")

    summary: dict[str, object] = {
        "video": str(master.video),
        "duration": master.duration,
        "aspect": aspect.value,
        "shots": len(master.plan.shots),
        "plan": str(plan_path),
        "generator": generator.name,
        "style": master.plan.style,
        "style_reason": master.plan.style_reason,
        "style_scores": master.plan.style_scores,
        "transition": master.plan.transition,
        "seconds_per_shot": master.plan.seconds_per_shot,
        "motion_offset": master.plan.motion_offset,
        "beat_bpm": master.plan.beat_bpm,
        "beat_offset": master.plan.beat_offset,
        "beat_aligned": master.plan.beat_aligned,
        "preview": str(master.preview) if master.preview else None,
    }

    if args.short is not None:
        short_duration = float(args.short)
        song_duration = await probe_duration(song)
        short_duration = min(short_duration, song_duration)
        start, _ = await pick_window(song, short_duration)
        console.print(
            f"✂️  Estribillo: desde [bold]{start:.1f} s[/] "
            f"(energía máxima en {short_duration:.0f} s de {song_duration:.1f} s)"
        )
        cut = await extract_window(
            song,
            out / f"{slug}_short_audio.m4a",
            start=start,
            duration=short_duration,
        )
        # El fragmento empieza en ``start``: la rejilla se desplaza con él para
        # que los cortes sigan cayendo en el pulso de la canción original.
        short_grid = grid.shifted(start) if grid is not None else None
        short = await render_visuals(
            topic=args.topic,
            output=out / f"{slug}_short_9x16.mp4",
            song=cut,
            aspect=Aspect.VERTICAL,
            style=args.style,
            signals=signals,
            beat_grid=short_grid,
            mood=music_mood,
            tone=args.tone,
            keywords=args.keyword,
            shots=args.shots,
            fps=args.fps,
            transition=args.transition,
            texts=args.texts,
            generator=generator,
            seed=args.seed + 500,
            music_volume=1.0,
            preview=args.preview,
            force=args.force,
            on_progress=console.print,
        )
        short_plan = out / f"{slug}_short_9x16_plan.json"
        short_plan.write_text(short.plan.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"✅ Short: [bold green]{short.video}[/] ({short.duration:.1f} s)")
        summary.update(
            {
                "short_video": str(short.video),
                "short_duration": short.duration,
                "short_start": start,
                "short_plan": str(short_plan),
                "short_preview": str(short.preview) if short.preview else None,
            }
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del CLI."""
    args = build_parser().parse_args(argv)
    try:
        summary = asyncio.run(run(args))
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        console.print(f"[bold red]✖ {error}[/]")
        return 1
    if args.json:
        console.print_json(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - entrada manual
    sys.exit(main())
