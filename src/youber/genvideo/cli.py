"""CLI del motor de generación de vídeo local: ``youber-genvideo``.

Ejemplos:
    # ¿Está listo el backend y qué cabe en una noche?
    youber-genvideo check

    # Encolar los planos de un guion (JSON de youber-script) a 720p
    youber-genvideo enqueue --script guion.json --preset 720p

    # Generar de noche, de 22:00 a 07:00, sin pasar del cierre
    youber-genvideo run --start 22:00 --end 07:00 --report reports/

    # Probar el flujo completo sin GPU ni ComfyUI (MP4 sintético)
    youber-genvideo run --topic "prueba" --demo --max-clips 2

    # ¿Este clip generado sirve?
    youber-genvideo verify clips/001-plano-abc123.mp4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from youber.genvideo.client import ComfyUIClient
from youber.genvideo.models import (
    BatchReport,
    ClipRequest,
    GenConfig,
    JobStatus,
    Resolution,
    estimate_clip_seconds,
)
from youber.genvideo.queue import JobQueue, default_dir
from youber.genvideo.runner import (
    requests_from_prompts,
    requests_from_script,
    resolve_window,
    run_nightly,
    script_from_topic,
    write_report,
)
from youber.genvideo.verify import verify_clip
from youber.script.models import Script

console = Console()

#: Ventana nocturna por defecto: de 22:00 a 07:00 (cruza la medianoche).
DEFAULT_START = "22:00"
DEFAULT_END = "07:00"


def _parse_time(value: str) -> dt_time:
    """Convierte ``"22:00"`` en :class:`datetime.time`."""
    try:
        hours, _, minutes = value.partition(":")
        return dt_time(hour=int(hours), minute=int(minutes or 0))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Hora inválida: {value!r} (usa HH:MM)") from exc


def _load_script(path: str | None) -> Script | None:
    """Lee un guion de un JSON (el que exporta ``youber-script``)."""
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Script.model_validate(data)


def _load_prompts(path: str | None) -> list[str]:
    """Lee un prompt por línea (las líneas vacías se ignoran)."""
    if not path:
        return []
    text = Path(path).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _requests_for(args: argparse.Namespace, config: GenConfig) -> list[ClipRequest]:
    """Clips pedidos por la CLI a partir del guion, el fichero o el tema."""
    script = _load_script(getattr(args, "script", None))
    prompts = _load_prompts(getattr(args, "prompts", None))
    topic = getattr(args, "topic", None)
    if script is None and topic:
        script = script_from_topic(topic)
    if script is not None:
        return requests_from_script(
            script, config=config, shots=getattr(args, "shots", None), seed_base=args.seed
        )
    if prompts:
        return requests_from_prompts(prompts, config=config, seed_base=args.seed)
    return []


# -- check ----------------------------------------------------------------


def _cmd_check(args: argparse.Namespace) -> int:
    """Comprueba el backend y enseña qué se puede generar esta noche."""
    config = GenConfig.for_resolution(Resolution(args.preset), server_url=args.server)
    console.print("[bold]Configuración[/bold]")
    console.print(f"  {config.describe()}")
    per_clip = estimate_clip_seconds(config)
    console.print(
        f"  Estimación: {per_clip / 60:.1f} min/clip "
        f"→ ~{int(8 * 3600 // per_clip)} clips en una noche de 8 h "
        f"(~{int(8 * 3600 // per_clip) * config.clip_seconds / 60:.0f} min de metraje)"
    )
    console.print(f"  Cola: {default_dir() / 'queue.json'}")
    if args.demo:
        console.print("[yellow]Modo demo: no se consulta ComfyUI (backend de pruebas).[/yellow]")
        return 0

    async def probe() -> int:
        client = ComfyUIClient(config.server_url)
        try:
            if not await client.is_up():
                console.print(
                    f"[red]ComfyUI no responde en {config.server_url}.[/red] "
                    "Arráncalo (o usa --demo para probar sin GPU)."
                )
                return 1
            console.print(f"[green]ComfyUI responde[/green] en {config.server_url}")
            for node, field, wanted in (
                ("UNETLoader", "unet_name", config.unet_name),
                ("VAELoader", "vae_name", config.vae_name),
                ("CLIPLoader", "clip_name", config.clip_name),
            ):
                try:
                    options = await client.available_options(node, field)
                except Exception as exc:  # noqa: BLE001 - solo es un chequeo
                    console.print(f"  [yellow]{node}: no se pudo consultar ({exc})[/yellow]")
                    continue
                state = "[green]ok[/green]" if wanted in options else "[red]FALTA[/red]"
                console.print(f"  {node}/{field}: {wanted} → {state}")
                if wanted not in options:
                    console.print(f"    disponibles: {', '.join(options) or '—'}")
            if config.lora_name:
                options = await client.available_options("LoraLoaderModelOnly", "lora_name")
                state = "[green]ok[/green]" if config.lora_name in options else "[red]FALTA[/red]"
                console.print(f"  LoRA {config.lora_name} → {state}")
            return 0
        finally:
            await client.aclose()

    return asyncio.run(probe())


# -- enqueue / status -----------------------------------------------------


def _cmd_enqueue(args: argparse.Namespace) -> int:
    """Añade clips a la cola persistida sin generar nada."""
    config = GenConfig.for_resolution(Resolution(args.preset))
    requests = _requests_for(args, config)
    if not requests:
        console.print("[red]No hay nada que encolar: usa --script, --prompts o --topic.[/red]")
        return 1
    queue = JobQueue(args.state)
    queue.extend(requests)
    console.print(
        f"[green]{len(requests)} clip(s) encolados[/green] en {queue.path} "
        f"({queue.stats()['total']} en cola en total)"
    )
    for request in requests[:5]:
        console.print(f"  · {request.label}: {request.prompt[:70]}…")
    if len(requests) > 5:
        console.print(f"  … y {len(requests) - 5} más")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Enseña el estado de la cola persistida."""
    queue = JobQueue(args.state)
    stats = queue.stats()
    table = Table(title=f"Cola de generación ({queue.path})")
    table.add_column("Estado")
    table.add_column("Clips", justify="right")
    for key, value in stats.items():
        if key != "total":
            table.add_row(key, str(value))
    table.add_row("[bold]total[/bold]", f"[bold]{stats['total']}[/bold]")
    console.print(table)
    pending = queue.pending()[:10]
    if pending:
        console.print("[bold]Siguientes[/bold]")
        for request in pending:
            console.print(
                f"  · {request.label} · {request.config.describe()} · "
                f"{request.attempts} intento(s)"
            )
    return 0


def _cmd_clear(args: argparse.Namespace) -> int:
    """Borra de la cola los clips terminados, los fallidos o todos."""
    queue = JobQueue(args.state)
    if args.all:
        removed = queue.clear()
        console.print(f"[green]{removed} clip(s) borrados de la cola[/green]")
        return 0
    removed = 0
    if args.done:
        removed += queue.clear(JobStatus.DONE)
    if args.failed:
        removed += queue.clear(JobStatus.FAILED)
    if not (args.done or args.failed):
        removed += queue.clear(JobStatus.DONE)
    console.print(f"[green]{removed} clip(s) borrados de la cola[/green]")
    return 0


# -- run ------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    """Ejecuta el lote (el camino nocturno completo)."""
    config = GenConfig.for_resolution(Resolution(args.preset))
    script = _load_script(args.script)
    prompts = _load_prompts(args.prompts)
    start = args.start if args.start != "-" else None
    end = args.end if args.end != "-" else None
    start_time = _parse_time(start) if start else None
    end_time = _parse_time(end) if end else None
    start_at, end_at = resolve_window(start_time, end_time, allow_wait=args.wait)
    if start_at and args.wait and start_at > datetime.now():
        console.print(
            f"[yellow]El lote esperará a las {start_at:%H:%M} para empezar "
            f"(--wait activo).[/yellow]"
        )
    console.print(f"[bold]Lote de generación[/bold] · {config.describe()}")
    if end_at:
        console.print(f"  Cierre de ventana: {end_at:%Y-%m-%d %H:%M}")
    report = asyncio.run(
        run_nightly(
            script=script,
            prompts=prompts,
            topic=args.topic,
            config=config,
            preset=Resolution(args.preset),
            start=start_time,
            end=end_time,
            allow_wait=args.wait,
            max_clips=args.max_clips,
            shots=args.shots,
            output_dir=args.output,
            report_dir=args.report,
            state_path=args.state,
            verify=not args.no_verify,
            keep_awake=not args.no_keep_awake,
            stub=args.demo,
            stub_flat=args.demo_flat,
        )
    )
    console.print()
    console.print(report.to_markdown())
    return 0


# -- verify ---------------------------------------------------------------


def _cmd_verify(args: argparse.Namespace) -> int:
    """Mide un clip ya generado y dice si sirve."""
    quality = asyncio.run(
        verify_clip(
            args.path,
            width=args.width,
            height=args.height,
            fps=args.fps,
            frames=args.frames,
        )
    )
    color = "green" if quality.ok else "red"
    console.print(f"[{color}]{quality.summary()}[/{color}]")
    for reason in quality.reasons:
        console.print(f"  · {reason}")
    return 0 if quality.ok else 1


def _cmd_report(args: argparse.Namespace) -> int:
    """Enseña (y opcionalmente regenera) el resumen de un lote guardado."""
    if args.path.endswith(".md"):
        console.print(Path(args.path).read_text(encoding="utf-8"))
        return 0
    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    report = BatchReport.model_validate(data)
    console.print(report.to_markdown())
    if args.out:
        json_path, markdown_path = write_report(report, args.out)
        console.print(f"[green]Manifiesto: {json_path}[/green]")
        console.print(f"[green]Resumen:    {markdown_path}[/green]")
    return 0


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    """Fuentes de clips: guion, prompts sueltos o tema."""
    parser.add_argument("--script", help="Guion JSON (exportado por youber-script)")
    parser.add_argument("--prompts", help="Fichero con un prompt por línea")
    parser.add_argument("--topic", help="Tema suelto (genera un guion mínimo)")
    parser.add_argument("--shots", type=int, help="Número de planos a generar")
    parser.add_argument("--seed", type=int, default=42, help="Semilla del primer clip")
    parser.add_argument(
        "--preset",
        choices=[item.value for item in Resolution],
        default=Resolution.HD.value,
        help="Preset medido (por defecto: 720p)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de ``youber-genvideo``."""
    parser = argparse.ArgumentParser(
        prog="youber-genvideo",
        description="Generación de vídeo local (ComfyUI + Wan 2.2) con verificación",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Comprueba backend y capacidad")
    check.add_argument("--server", default=GenConfig().server_url)
    check.add_argument("--preset", choices=[item.value for item in Resolution], default="720p")
    check.add_argument("--demo", action="store_true", help="No consulta ComfyUI")
    check.set_defaults(func=_cmd_check)

    enqueue = subparsers.add_parser("enqueue", help="Encola clips sin generar")
    _add_source_arguments(enqueue)
    enqueue.add_argument("--state", help="Fichero de cola (por defecto, el del usuario)")
    enqueue.set_defaults(func=_cmd_enqueue)

    run = subparsers.add_parser("run", help="Genera el lote (camino nocturno)")
    _add_source_arguments(run)
    run.add_argument("--start", default=DEFAULT_START, help="Hora de inicio (HH:MM, '-' sin límite)")
    run.add_argument("--end", default=DEFAULT_END, help="Hora de cierre (HH:MM, '-' sin límite)")
    run.add_argument("--wait", action="store_true", help="Esperar a la hora de inicio")
    run.add_argument("--max-clips", type=int, help="Máximo de intentos en el lote")
    run.add_argument("-o", "--output", help="Carpeta de los clips")
    run.add_argument("--report", help="Carpeta del manifiesto y el resumen")
    run.add_argument("--state", help="Fichero de cola (por defecto, el del usuario)")
    run.add_argument("--no-verify", action="store_true", help="No verificar los clips")
    run.add_argument(
        "--no-keep-awake",
        action="store_true",
        help="Permitir que el equipo se suspenda durante el lote",
    )
    run.add_argument("--demo", action="store_true", help="Backend de pruebas (sin GPU)")
    run.add_argument("--demo-flat", action="store_true", help="Con --demo: clips planos a propósito")
    run.set_defaults(func=_cmd_run)

    status = subparsers.add_parser("status", help="Estado de la cola")
    status.add_argument("--state", help="Fichero de cola (por defecto, el del usuario)")
    status.set_defaults(func=_cmd_status)

    clear = subparsers.add_parser("clear", help="Borra clips de la cola")
    clear.add_argument("--state", help="Fichero de cola (por defecto, el del usuario)")
    clear.add_argument("--done", action="store_true", help="Borra los ya generados")
    clear.add_argument("--failed", action="store_true", help="Borra los descartados")
    clear.add_argument("--all", action="store_true", help="Borra todo")
    clear.set_defaults(func=_cmd_clear)

    verify = subparsers.add_parser("verify", help="Verifica un clip generado")
    verify.add_argument("path", help="Fichero de vídeo")
    verify.add_argument("--width", type=int)
    verify.add_argument("--height", type=int)
    verify.add_argument("--fps", type=float)
    verify.add_argument("--frames", type=int)
    verify.set_defaults(func=_cmd_verify)

    report = subparsers.add_parser("report", help="Resumen de un lote guardado")
    report.add_argument("path", help="Manifiesto JSON (o el Markdown ya generado)")
    report.add_argument("--out", help="Carpeta donde reescribirlo")
    report.set_defaults(func=_cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de ``youber-genvideo``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover - entrada manual
    sys.exit(main())
