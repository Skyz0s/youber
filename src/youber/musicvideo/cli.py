"""CLI del videoclip dirigido por la letra (``youber-musicvideo``).

Dos mandos:

- ``plan``: dirige y **enseña la dirección** (tramos, mejores momentos,
  escenas) sin generar nada — para revisar antes de gastar GPU;
- ``render``: hace las dos líneas de producción (videoclip + corto vertical).

El backend de generación es enchufable: ``--backend comfy`` (ComfyUI local, por
defecto) o ``--backend stub`` (MP4 sintético con FFmpeg, sin GPU, para probar
la tubería entera).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from youber.genvideo.client import ComfyUIClient, GenerationClient, StubClient
from youber.genvideo.models import GenConfig, Resolution
from youber.musicvideo.models import MusicVideoError
from youber.musicvideo.pipeline import (
    DEFAULT_PRESET,
    SongMeasurement,
    measure_song,
    prepare_plan,
    run_musicvideo,
)

console = Console()

#: Backends disponibles en el CLI.
BACKENDS = ("comfy", "stub")


def _client_for(backend: str, preset: Resolution) -> GenerationClient:
    """Crea el backend de generación pedido."""
    if backend == "stub":
        settings = GenConfig.for_resolution(preset)
        return StubClient(width=settings.width, height=settings.height, fps=settings.fps)
    return ComfyUIClient()


async def _measure(
    audio: str, *, with_energy: bool, max_seconds: float
) -> SongMeasurement:
    """Mide la canción (o devuelve solo la duración si se pide sin análisis)."""
    if with_energy:
        return await measure_song(audio, max_seconds=max_seconds)
    from youber.audio._ffmpeg import probe_duration

    duration = await probe_duration(Path(audio))
    return SongMeasurement(duration=duration)


def _print_plan(plan, measurement: SongMeasurement) -> None:
    """Enseña la dirección del videoclip en consola."""
    console.print(
        Panel.fit(
            f"[bold cyan]Dirección — «{plan.title or 'sin título'}»[/]\n"
            f"{plan.duration:.1f} s · {'con' if plan.timed else 'sin'} tiempos reales · "
            f"ánimo: {plan.mood.value if plan.mood else '—'} · sentimiento: {plan.sentiment}"
            + (f" · {measurement.beat_bpm:.0f} BPM" if measurement.beat_bpm else ""),
            border_style="cyan",
        )
    )

    sections = Table(title="Tramos", show_lines=False)
    sections.add_column("Inicio", justify="right")
    sections.add_column("Fin", justify="right")
    sections.add_column("Tipo")
    sections.add_column("Rep.", justify="right")
    sections.add_column("Energía", justify="right")
    for section in plan.sections:
        energy = f"{section.energy:.2f}" if section.energy is not None else "—"
        sections.add_row(
            f"{section.start:.1f}",
            f"{section.end:.1f}",
            section.kind.value,
            str(section.repetition),
            energy,
        )
    console.print(sections)

    if plan.highlights:
        highlights = Table(title="Mejores momentos (corto)", show_lines=False)
        highlights.add_column("Inicio", justify="right")
        highlights.add_column("Fin", justify="right")
        highlights.add_column("Duración", justify="right")
        highlights.add_column("Motivo")
        for moment in plan.highlights:
            highlights.add_row(
                f"{moment.start:.1f}",
                f"{moment.end:.1f}",
                f"{moment.duration:.1f} s",
                moment.reason,
            )
        console.print(highlights)
    else:
        console.print("[yellow]Sin mejores momentos detectados (sin estribillo reconocible)[/]")

    console.print(f"[bold]{len(plan.scenes)}[/] escenas (una por línea), ej.:")
    for scene in plan.scenes[:3]:
        console.print(
            f"  · [dim]{scene.start:6.1f}s[/] «{scene.text}» → {scene.beat.describe()}"
        )


async def _cmd_plan(args: argparse.Namespace) -> int:
    """Dirige el videoclip y enseña la dirección (sin generar)."""
    measurement = await _measure(
        args.audio, with_energy=not args.no_measure, max_seconds=180.0
    )
    plan, measurement = await prepare_plan(
        args.audio,
        lyrics=args.lyrics,
        title=args.title,
        artist=args.artist,
        measurement=measurement,
        align=not args.no_align,
        whisper_model=args.whisper_model,
        language=args.language,
        short_seconds=args.short_seconds,
    )
    if args.json:
        console.print(plan.model_dump_json(indent=2))
        return 0
    _print_plan(plan, measurement)
    return 0


async def _cmd_render(args: argparse.Namespace) -> int:
    """Genera las dos líneas de producción (videoclip + corto vertical)."""
    preset = Resolution(args.preset)
    client = _client_for(args.backend, preset)
    try:
        result = await run_musicvideo(
            args.audio,
            lyrics=args.lyrics,
            title=args.title,
            artist=args.artist,
            out_dir=args.out,
            client=client,
            preset=preset,
            make_full=args.only in ("both", "full"),
            make_short=args.only in ("both", "short"),
            short_seconds=args.short_seconds,
            seed_base=args.seed,
            verify=not args.no_verify,
            align=not args.no_align,
            whisper_model=args.whisper_model,
            language=args.language,
        )
    finally:
        await client.aclose()
    _print_plan(result.plan, result.measurement)
    console.print(
        Panel.fit(
            (f"🎬 Videoclip → [bold green]{result.video}[/]\n" if result.video else "")
            + (f"📱 Short    → [bold green]{result.short}[/]" if result.short else "")
            or "Nada que mostrar",
            border_style="green",
        )
    )
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    """Argumentos compartidos por los dos mandos."""
    parser.add_argument("audio", help="Fichero de la canción (mp3, wav, m4a...)")
    parser.add_argument("--lyrics", help="Letra (.lrc/.txt/.srt/.json); si falta, se busca junto al audio")
    parser.add_argument("--title", default="", help="Título de la canción")
    parser.add_argument("--artist", default=None, help="Intérprete")
    parser.add_argument(
        "--short-seconds", type=float, default=45.0, help="Duración deseada del corto"
    )
    parser.add_argument(
        "--no-align", action="store_true", help="No alinear la letra con Whisper si viene sin tiempos"
    )
    parser.add_argument(
        "--whisper-model", default="small", help="Modelo de Whisper para alinear (tiny|small|medium...)"
    )
    parser.add_argument("--language", default=None, help="Idioma de la letra (p. ej. en, es)")


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser del CLI."""
    parser = argparse.ArgumentParser(
        prog="youber-musicvideo",
        description="Videoclip dirigido por la letra: la canción manda, la letra dirige.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Dirige y enseña la dirección (sin generar)")
    _add_common(plan)
    plan.add_argument("--json", action="store_true", help="Vuelca la dirección en JSON")
    plan.add_argument(
        "--no-measure",
        action="store_true",
        help="No mide pulso ni energía (solo la duración): más rápido",
    )
    plan.set_defaults(func=_cmd_plan)

    render = subparsers.add_parser("render", help="Genera el videoclip y el corto vertical")
    _add_common(render)
    render.add_argument("--out", default="musicvideo_out", help="Carpeta de salida")
    render.add_argument(
        "--preset", choices=[item.value for item in Resolution], default=DEFAULT_PRESET.value
    )
    render.add_argument(
        "--backend", choices=BACKENDS, default="comfy", help="Backend de generación"
    )
    render.add_argument(
        "--only", choices=("both", "full", "short"), default="both", help="Qué producir"
    )
    render.add_argument("--seed", type=int, default=42, help="Semilla base de los clips")
    render.add_argument(
        "--no-verify", action="store_true", help="No verificar la calidad de los clips"
    )
    render.set_defaults(func=_cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del CLI."""
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except MusicVideoError as error:
        console.print(f"[red]Error:[/] {error}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
