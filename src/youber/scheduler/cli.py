"""CLI ``youber-schedule``: programación de tareas del scheduler de BARF.

Comandos: ``add``, ``list``, ``remove``, ``enable``, ``disable``, ``run``
(ejecuta los pendientes una vez) y ``daemon`` (servicio en segundo plano).

Ejemplos:

.. code-block:: bash

    youber-schedule add --name "research @python" --type research --schedule daily --at "09:00" --param channel=@python
    youber-schedule add --name "subir vídeo" --type upload --schedule once --at "2026-09-15 10:00:00" --param video=final.mp4 --param title="Mi Video"
    youber-schedule list
    youber-schedule remove <id>
    youber-schedule run
    youber-schedule daemon --interval 60
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from rich.console import Console
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.scheduler.models import JobType, ScheduledJob, ScheduleType
from youber.scheduler.scheduler import Scheduler

console = Console()


def _job_type(value: str) -> JobType:
    """Convierte el texto del usuario en un :class:`JobType`."""
    try:
        return JobType(value.strip().lower())
    except ValueError as exc:
        valid = ", ".join(t.value for t in JobType)
        raise argparse.ArgumentTypeError(f"Tipo de trabajo desconocido: {value!r}. Válidos: {valid}") from exc


def _schedule_type(value: str) -> ScheduleType:
    """Convierte el texto del usuario en un :class:`ScheduleType`."""
    try:
        return ScheduleType(value.strip().lower())
    except ValueError as exc:
        valid = ", ".join(t.value for t in ScheduleType)
        raise argparse.ArgumentTypeError(f"Programación desconocida: {value!r}. Válidas: {valid}") from exc


def _param(value: str) -> tuple[str, str]:
    """Convierte ``clave=valor`` en una tupla."""
    if "=" not in value:
        raise argparse.ArgumentTypeError(f"Param debe ser clave=valor: {value!r}")
    key, _, val = value.partition("=")
    return key.strip(), val.strip()


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-schedule``."""
    parser = argparse.ArgumentParser(
        prog="youber-schedule",
        description="BARF: programación de tareas (uso educativo)",
    )
    parser.add_argument("--store", default=None, help="Fichero JSON de trabajos (por defecto ~/.youber/schedule.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Añade un trabajo programado")
    add.add_argument("--name", required=True, help="Nombre descriptivo")
    add.add_argument("--type", type=_job_type, required=True, help="Tipo (research/workflow/upload/music_scan)")
    add.add_argument("--schedule", type=_schedule_type, required=True, help="once/daily/weekly/cron")
    add.add_argument("--at", required=True, help="Valor: '09:00', 'monday', '2026-09-15 10:00:00' o cron")
    add.add_argument("--param", type=_param, action="append", default=[], help="Parámetro clave=valor (repetible)")

    sub.add_parser("list", help="Lista los trabajos programados")

    remove = sub.add_parser("remove", help="Elimina un trabajo")
    remove.add_argument("id", help="Id del trabajo")

    enable = sub.add_parser("enable", help="Activa un trabajo")
    enable.add_argument("id", help="Id del trabajo")

    disable = sub.add_parser("disable", help="Desactiva un trabajo")
    disable.add_argument("id", help="Id del trabajo")

    sub.add_parser("run", help="Ejecuta los trabajos pendientes una vez")

    daemon = sub.add_parser("daemon", help="Arranca el servicio en segundo plano")
    daemon.add_argument("--interval", type=float, default=60.0, help="Segundos entre comprobaciones")

    return parser


def _print_jobs(jobs: list[ScheduledJob]) -> None:
    table = Table(title=f"{len(jobs)} trabajo(s) programado(s)")
    table.add_column("Id", style="dim")
    table.add_column("Nombre")
    table.add_column("Tipo")
    table.add_column("Programación", justify="right")
    table.add_column("Estado")
    table.add_column("Próxima ejecución", justify="right")
    for job in jobs:
        table.add_row(
            job.id,
            job.name,
            job.job_type.value,
            f"{job.schedule_type.value} ({job.schedule_value})",
            "✅ activo" if job.enabled else "⏸️ pausado",
            job.next_run.strftime("%Y-%m-%d %H:%M") if job.next_run else "-",
        )
    console.print(table)


def run(args: argparse.Namespace) -> None:
    """Ejecuta el subcomando indicado."""
    scheduler = Scheduler()
    if args.store:
        from youber.scheduler.storage import JobStorage

        scheduler.storage = JobStorage(args.store)

    if args.command == "add":
        params = dict(args.param)
        job = scheduler.add_job(
            name=args.name,
            job_type=args.type,
            schedule_type=args.schedule,
            schedule_value=args.at,
            params=params,
        )
        console.print(f"[green]Trabajo añadido:[/] {job.id} — {job.name}")
        _print_jobs([job])
    elif args.command == "list":
        _print_jobs(scheduler.list_jobs())
    elif args.command == "remove":
        ok = scheduler.remove_job(args.id)
        console.print(f"🗑️  Trabajo {args.id} eliminado" if ok else f"[red]Trabajo no encontrado: {args.id}[/]")
    elif args.command == "enable":
        ok = scheduler.set_enabled(args.id, True)
        console.print(f"✅ Trabajo {args.id} activado" if ok else f"[red]Trabajo no encontrado: {args.id}[/]")
    elif args.command == "disable":
        ok = scheduler.set_enabled(args.id, False)
        console.print(f"⏸️  Trabajo {args.id} desactivado" if ok else f"[red]Trabajo no encontrado: {args.id}[/]")
    elif args.command == "run":
        results = asyncio.run(scheduler.run_due(datetime.now()))
        if not results:
            console.print("Sin trabajos pendientes.")
        for result in results:
            status = result.get("status")
            emoji = "✅" if status == "ok" else "❌"
            console.print(f"{emoji} {result.get('job_name')}: {status}")
    elif args.command == "daemon":
        from youber.scheduler.daemon import run_daemon

        console.print(f"🔄 Daemon arrancado (intervalo {args.interval}s). Ctrl+C para detener.")
        try:
            asyncio.run(run_daemon(scheduler, interval=args.interval))
        except KeyboardInterrupt:
            console.print("Daemon detenido.")


def main() -> None:
    """Entry point de ``youber-schedule``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    try:
        run(args)
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
