"""CLI ``youber-journal``: registra decisiones y mide resultados.

Comandos:

- ``list``      — lista las decisiones registradas.
- ``show``      — detalle de una decisión (atributos, canción, candidatas, métricas).
- ``upload``    — asocia el vídeo subido (id/URL) a una decisión.
- ``performance`` — registra métricas de rendimiento (impresiones, CTR, retención...).
- ``import``    — pega un CSV de YouTube Studio a las decisiones que coincidan.
- ``dataset``   — exporta el dataset plano (features + resultados).
- ``analyze``   — informe de qué características correlacionan con un buen resultado.
- ``pending``   — vídeos publicados a los que les faltan métricas (para el CSV de Studio).
- ``stats``     — resumen del journal.

Uso:

.. code-block:: bash

    youber-journal list -n 10
    youber-journal show dec-1a2b3c4d5e6f
    youber-journal upload dec-1a2b3c4d5e6f --video-id abc123 --url https://youtu.be/abc123
    youber-journal performance dec-1a2b3c4d5e6f --window 7d --views 1200 --ctr 4.5
    youber-journal import studio_analytics.csv --window 28d
    youber-journal analyze --metric ctr -o reports/informe.md
    youber-journal pending                    # ¿qué vídeos siguen sin métricas?
    youber-journal pending --windows 7d --json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.journal.analytics import (
    OUTCOME_LABELS,
    build_report,
    dataset_rows,
    feature_correlations,
    summarize,
)
from youber.journal.importers import import_analytics_csv
from youber.journal.journal import DecisionJournal, default_journal_path
from youber.journal.models import DecisionRecord, PerformanceSnapshot
from youber.journal.reminders import (
    DEFAULT_MIN_AGE_DAYS,
    DEFAULT_WINDOWS,
    pending_metrics,
)

console = Console()

_METRIC_FLAGS: tuple[tuple[str, str], ...] = (
    ("views", "Visualizaciones"),
    ("impressions", "Impresiones"),
    ("ctr", "CTR de impresiones (%)"),
    ("avg-view-percentage", "Retención (% medio visto)"),
    ("avg-view-duration", "Duración media vista (s)"),
    ("watch-time", "Tiempo de visualización (min)"),
    ("likes", "Me gusta"),
    ("comments", "Comentarios"),
    ("shares", "Compartidos"),
    ("subs-gained", "Suscriptores ganados"),
    ("subs-lost", "Suscriptores perdidos"),
    ("revenue", "Ingresos"),
)


def _number(value: str | None) -> float | None:
    """Convierte el valor de una opción numérica (admite comas decimales)."""
    if value is None:
        return None
    text = value.strip().replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    return float(text) if text else None


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-journal``."""
    parser = argparse.ArgumentParser(
        prog="youber-journal",
        description="BARF: registro de decisiones y resultados de cada vídeo",
    )
    parser.add_argument(
        "--db",
        default=None,
        help=f"Base de datos del journal (por defecto: {default_journal_path()})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida en JSON (para encadenar con otras herramientas)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="Lista las decisiones registradas")
    listing.add_argument("-n", "--limit", type=int, default=20, help="Máximo de filas")
    listing.add_argument("--channel", default=None, help="Filtrar por canal de referencia")
    listing.add_argument(
        "--with-performance",
        action="store_true",
        help="Añade las métricas de la última medición",
    )

    show = sub.add_parser("show", help="Detalle de una decisión")
    show.add_argument("decision_id", help="Id de la decisión o id del vídeo subido")

    upload = sub.add_parser("upload", help="Asocia el vídeo subido a una decisión")
    upload.add_argument("decision_id", help="Id de la decisión")
    upload.add_argument("--video-id", required=True, help="Id del vídeo en YouTube")
    upload.add_argument("--url", default=None, help="URL del vídeo")
    upload.add_argument("--title", default=None, help="Título publicado")
    upload.add_argument("--privacy", default=None, help="Privacidad (private/unlisted/public)")
    upload.add_argument("--published-at", default=None, help="Fecha de publicación (ISO-8601)")

    performance = sub.add_parser("performance", help="Registra métricas de rendimiento")
    performance.add_argument("decision_id", help="Id de la decisión o del vídeo")
    performance.add_argument(
        "--window", default="7d", help="Ventana temporal: 24h, 48h, 7d, 28d, lifetime..."
    )
    for flag, help_text in _METRIC_FLAGS:
        performance.add_argument(f"--{flag}", default=None, help=help_text)
    performance.add_argument(
        "--raw",
        action="append",
        default=[],
        metavar="CLAVE=VALOR",
        help="Columna extra del panel (repetible)",
    )

    importer = sub.add_parser("import", help="Importa métricas desde un CSV de YouTube Studio")
    importer.add_argument("csv", help="CSV exportado de YouTube Studio (modo avanzado)")
    importer.add_argument("--window", default="28d", help="Ventana que representan los datos")
    importer.add_argument(
        "--dry-run", action="store_true", help="Solo muestra el cruce, sin guardar nada"
    )

    dataset = sub.add_parser("dataset", help="Exporta el dataset (features + resultados)")
    dataset.add_argument("-o", "--output", default=None, help="Fichero de salida")
    dataset.add_argument(
        "-f", "--format", default=None, choices=("csv", "json", "jsonl"), help="Formato"
    )
    dataset.add_argument("--window", default=None, help="Ventana de métricas a usar")

    analyze = sub.add_parser("analyze", help="¿Qué features correlacionan con el resultado?")
    analyze.add_argument(
        "--metric",
        default="ctr",
        choices=tuple(OUTCOME_LABELS),
        help="Métrica de resultado a estudiar (default: ctr)",
    )
    analyze.add_argument("--window", default=None, help="Ventana de métricas a usar")
    analyze.add_argument("-o", "--output", default=None, help="Guardar el informe en Markdown")
    analyze.add_argument(
        "--min-n", type=int, default=3, help="Pares mínimos para calcular correlaciones"
    )

    pending = sub.add_parser(
        "pending", help="Vídeos publicados a los que les faltan métricas de Studio"
    )
    pending.add_argument(
        "--windows",
        default=",".join(DEFAULT_WINDOWS),
        help=f"Ventanas a vigilar (default: {','.join(DEFAULT_WINDOWS)})",
    )
    pending.add_argument(
        "--min-age-days",
        type=float,
        default=DEFAULT_MIN_AGE_DAYS,
        help=f"Antigüedad mínima del vídeo en días (default: {DEFAULT_MIN_AGE_DAYS:g})",
    )
    pending.add_argument(
        "--include-unpublished",
        action="store_true",
        help="Incluir también decisiones sin vídeo publicado (no medibles en la plataforma)",
    )
    pending.add_argument(
        "--now",
        default=None,
        metavar="ISO",
        help=(
            "Fecha de referencia (ISO-8601) para calcular antigüedades; "
            "default: ahora (útil para probar/simular)"
        ),
    )

    sub.add_parser("stats", help="Resumen del journal")

    remove = sub.add_parser("remove", help="Elimina una decisión y sus métricas")
    remove.add_argument("decision_id", help="Id de la decisión")
    remove.add_argument("--yes", action="store_true", help="Confirma el borrado")
    return parser


def _snapshot_from_args(args: argparse.Namespace) -> PerformanceSnapshot:
    """Construye una medición a partir de las opciones de la CLI."""
    raw: dict[str, str] = {}
    for item in args.raw:
        key, _, value = item.partition("=")
        raw[key.strip()] = value.strip()
    return PerformanceSnapshot(
        window=args.window,
        views=_int(args.views),
        impressions=_int(args.impressions),
        ctr=_number(args.ctr),
        avg_view_percentage=_number(args.avg_view_percentage),
        avg_view_duration_seconds=_number(args.avg_view_duration),
        watch_time_minutes=_number(args.watch_time),
        likes=_int(args.likes),
        comments=_int(args.comments),
        shares=_int(args.shares),
        subscribers_gained=_int(args.subs_gained),
        subscribers_lost=_int(args.subs_lost),
        revenue=_number(args.revenue),
        raw=raw,
    )


def _int(value: str | None) -> int | None:
    """Convierte el valor de una opción en entero (o ``None``)."""
    number = _number(value)
    return int(number) if number is not None else None


def _performance_line(snapshot: PerformanceSnapshot) -> str:
    """Resumen de una medición en una línea."""
    parts: list[str] = []
    if snapshot.views is not None:
        parts.append(f"{snapshot.views:,} visitas".replace(",", "."))
    if snapshot.impressions is not None:
        parts.append(f"{snapshot.impressions} impresiones")
    if snapshot.ctr is not None:
        parts.append(f"CTR {snapshot.ctr:g} %")
    if snapshot.retention is not None:
        parts.append(f"retención {snapshot.retention:g} %")
    if snapshot.net_subscribers is not None:
        parts.append(f"{snapshot.net_subscribers:+d} subs")
    return f"[{snapshot.window}] " + (" · ".join(parts) if parts else "sin datos")


def _print_performance(snapshots: list[PerformanceSnapshot]) -> None:
    """Tabla con el histórico de mediciones de una decisión."""
    if not snapshots:
        console.print("[yellow]Sin métricas registradas todavía.[/]")
        return
    table = Table(title="Métricas de rendimiento")
    for column, justify in (
        ("Ventana", "left"),
        ("Captura", "left"),
        ("Vistas", "right"),
        ("Impresiones", "right"),
        ("CTR %", "right"),
        ("Retención %", "right"),
        ("Subs netos", "right"),
    ):
        table.add_column(column, justify=justify)  # type: ignore[arg-type]
    for snapshot in snapshots:
        table.add_row(
            snapshot.window,
            snapshot.captured_at.strftime("%Y-%m-%d %H:%M"),
            _format(snapshot.views),
            _format(snapshot.impressions),
            _format(snapshot.ctr),
            _format(snapshot.retention),
            _format(snapshot.net_subscribers, signed=True),
        )
    console.print(table)


def _format(value: float | int | None, *, signed: bool = False) -> str:
    """Formatea un número para la tabla (o ``-``)."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:+g}" if signed else f"{value:g}"
    return f"{value:+d}" if signed else f"{value:,}".replace(",", ".")


def _show_record(record: DecisionRecord, snapshots: list[PerformanceSnapshot]) -> None:
    """Muestra una decisión completa por consola."""
    attributes = record.attributes
    track = record.track
    themes = ", ".join(f"{name} {weight:.2f}" for name, weight in attributes.themes.items())
    lines = [
        f"[bold]Tema:[/] {record.topic}",
        f"[bold]Referencia:[/] {record.source_channel or '-'} ({record.mode})",
        f"[bold]Creada:[/] {record.created_at.strftime('%Y-%m-%d %H:%M')} · "
        f"versión {record.algorithm_version}",
        f"[bold]Atributos:[/] {themes or 'sin temas'} · sentimiento {attributes.sentiment}"
        + (f" · dominante {attributes.dominant_theme}" if attributes.dominant_theme else ""),
        f"[bold]Keywords:[/] {', '.join(attributes.keywords) or '-'}",
        f"[bold]Vídeos analizados:[/] {attributes.videos_analyzed} · "
        f"duración objetivo {attributes.target_duration:g} s",
        f"[bold]Canción:[/] {track.chosen_title or '-'}"
        + (f" — {track.chosen_artist}" if track.chosen_artist else "")
        + f" (score {track.score:g})",
        f"[bold]Motivo:[/] {track.reason or '-'}",
        f"[bold]Señales:[/] tema {track.theme_score:g} · sentimiento "
        f"{'sí' if track.sentiment_match else 'no'} · mood "
        f"{'sí' if track.mood_match else 'no'} · keywords {track.keyword_hits} · "
        f"favorita {'sí' if track.favorite else 'no'} · usos {track.usage_count}"
        + (" · forzada" if track.forced else ""),
        f"[bold]Vídeo:[/] {record.video.path or '-'}"
        + (f" · {record.video.duration_seconds:g} s" if record.video.duration_seconds else "")
        + (f" · {record.video.clip_count} clips ({record.video.clip_source})"),
    ]
    if record.video.size_bytes:
        lines.append(f"[bold]Tamaño:[/] {record.video.size_bytes / 1_048_576:.2f} MB")
    if record.upload is not None:
        lines.append(
            f"[bold]Subida:[/] {record.upload.video_id or '-'} · "
            f"{record.upload.url or ''} ({record.upload.privacy or '?'})"
        )
    if record.artifacts:
        lines.append(
            "[bold]Artefactos:[/] "
            + ", ".join(f"{key}={value}" for key, value in record.artifacts.items())
        )
    console.print(Panel("\n".join(lines), title=f"Decisión {record.id}", border_style="cyan"))

    if track.candidates:
        table = Table(title="Candidatas (ranking del selector)")
        table.add_column("#", justify="right")
        table.add_column("Canción", style="cyan")
        table.add_column("Score", justify="right")
        table.add_column("Temas")
        table.add_column("Motivo")
        for candidate in sorted(track.candidates, key=lambda item: item.rank):
            chosen = "★ " if candidate.track_id == track.chosen_id else ""
            table.add_row(
                str(candidate.rank),
                f"{chosen}{candidate.title}",
                f"{candidate.score:g}",
                ", ".join(candidate.matched_themes) or "-",
                candidate.reason or "-",
            )
        console.print(table)
    _print_performance(snapshots)


def _run_list(journal: DecisionJournal, args: argparse.Namespace) -> int:
    records = journal.list_decisions(limit=args.limit, source_channel=args.channel)
    if args.json:
        console.print(
            json.dumps(
                [json.loads(record.model_dump_json()) for record in records],
                ensure_ascii=False,
            ),
            markup=False,
            soft_wrap=True,
        )
        return 0
    if not records:
        console.print("[yellow]El journal está vacío.[/] Rellénalo con "
                      "`youber-workflow --lyrics-video` (o `--journal-db`).")
        return 0
    table = Table(title=f"Decisiones registradas ({len(records)})")
    table.add_column("Id", style="cyan")
    table.add_column("Fecha")
    table.add_column("Tema")
    table.add_column("Canción")
    table.add_column("Score", justify="right")
    table.add_column("Vídeo", overflow="fold")
    for record in records:
        video = record.video_id or "-"
        if args.with_performance:
            snapshot = journal.latest_performance(record.id)
            if snapshot is not None:
                video += " · " + _performance_line(snapshot)
        table.add_row(
            record.id,
            record.created_at.strftime("%Y-%m-%d %H:%M"),
            record.topic,
            record.track.chosen_title or "-",
            f"{record.track.score:g}" if record.track.chosen_id else "-",
            video,
        )
    console.print(table)
    return 0


def _run_show(journal: DecisionJournal, args: argparse.Namespace) -> int:
    record = journal.get(args.decision_id)
    if record is None:
        console.print(f"[red]✗ No hay ninguna decisión con id/vídeo {args.decision_id!r}[/]")
        return 1
    if args.json:
        console.print(
            json.dumps(
                json.loads(record.model_dump_json()), ensure_ascii=False, indent=2
            ),
            markup=False,
            soft_wrap=True,
        )
        return 0
    _show_record(record, journal.performance(record.id))
    return 0


def _run_upload(journal: DecisionJournal, args: argparse.Namespace) -> int:
    published = datetime.fromisoformat(args.published_at) if args.published_at else None
    try:
        record = journal.attach_upload(
            args.decision_id,
            video_id=args.video_id,
            url=args.url,
            title=args.title,
            privacy=args.privacy,
            published_at=published,
        )
    except KeyError as exc:
        console.print(f"[red]✗ {exc}[/]")
        return 1
    console.print(f"✓ Vídeo [bold]{record.video_id}[/] asociado a {record.id}")
    return 0


def _run_performance(journal: DecisionJournal, args: argparse.Namespace) -> int:
    snapshot = _snapshot_from_args(args)
    try:
        journal.record_performance(args.decision_id, snapshot)
    except KeyError as exc:
        console.print(f"[red]✗ {exc}[/]")
        return 1
    console.print(f"✓ Métricas registradas: {_performance_line(snapshot)}")
    return 0


def _run_import(journal: DecisionJournal, args: argparse.Namespace) -> int:
    result, pending = import_analytics_csv(
        journal.list_natural(), args.csv, window=args.window, dry_run=args.dry_run
    )
    console.print(
        Panel.fit(
            f"[bold cyan]Importación de métricas[/] · {result.parsed} filas · "
            f"{len(result.matched)} cruzadas · {len(result.unmatched)} sin decisión"
            + (" (dry-run)" if args.dry_run else ""),
            border_style="cyan",
        )
    )
    if result.matched:
        table = Table(title="Cruce con el journal")
        table.add_column("Decisión", style="cyan")
        table.add_column("Cruzado por")
        table.add_column("Vídeo")
        table.add_column("Vistas", justify="right")
        table.add_column("CTR %", justify="right")
        for matched in result.matched:
            table.add_row(
                matched.decision_id,
                matched.matched_by,
                matched.label[:48],
                _format(matched.metrics.get("views")),
                _format(matched.metrics.get("ctr")),
            )
        console.print(table)
    if result.unmatched:
        console.print(
            "[yellow]Sin decisión registrada (¿los subió el workflow?):[/] "
            + ", ".join((row.title or row.video_id or "?")[:40] for row in result.unmatched[:5])
            + (f" … (+{len(result.unmatched) - 5})" if len(result.unmatched) > 5 else "")
        )
    if not args.dry_run:
        for decision_id, snapshot in pending:
            journal.storage.add_performance(decision_id, snapshot)
        console.print(f"✓ {len(pending)} mediciones guardadas (ventana {args.window})")
    return 0


def _run_dataset(journal: DecisionJournal, args: argparse.Namespace) -> int:
    rows = journal.dataset(window=args.window)
    if args.output:
        path = journal.export(args.output, fmt=args.format, window=args.window)
        console.print(f"✓ Dataset exportado: [bold]{path}[/] ({len(rows)} filas)")
        return 0
    table = Table(title=f"Dataset ({len(rows)} filas)")
    table.add_column("Decisión", style="cyan")
    table.add_column("Tema")
    table.add_column("Canción")
    table.add_column("Ventana")
    table.add_column("Vistas", justify="right")
    table.add_column("CTR %", justify="right")
    table.add_column("Retención %", justify="right")
    for row in rows:
        table.add_row(
            row.decision_id,
            row.topic[:28],
            row.dominant_theme or "-",
            row.window or "-",
            _format(row.outcomes.get("views")),
            _format(row.outcomes.get("ctr")),
            _format(row.outcomes.get("retention")),
        )
    console.print(table)
    if args.json:
        console.print(
            json.dumps(dataset_rows(rows), ensure_ascii=False, default=str),
            markup=False,
            soft_wrap=True,
        )
    return 0


def _run_analyze(journal: DecisionJournal, args: argparse.Namespace) -> int:
    rows = journal.dataset(window=args.window)
    summary = summarize(rows)
    console.print(
        Panel.fit(
            f"[bold cyan]Análisis del journal[/] · {summary.decisions} decisiones · "
            f"{summary.measured} con métricas · métrica: {OUTCOME_LABELS[args.metric]}",
            border_style="cyan",
        )
    )
    correlations = feature_correlations(rows, args.metric, min_n=args.min_n)
    if correlations:
        table = Table(title=f"Correlaciones con {OUTCOME_LABELS[args.metric].lower()}")
        table.add_column("Feature")
        table.add_column("r", justify="right")
        table.add_column("n", justify="right")
        table.add_column("Media feature", justify="right")
        table.add_column("Media resultado", justify="right")
        for item in correlations:
            table.add_row(
                item.feature,
                f"{item.r:+.3f}",
                str(item.n),
                f"{item.mean_feature:g}",
                f"{item.mean_metric:g}",
            )
        console.print(table)
    else:
        console.print(
            f"[yellow]Aún no hay datos suficientes[/] (mínimo {args.min_n} vídeos con "
            f"«{OUTCOME_LABELS[args.metric]}» medido). Sigue registrando y pega el CSV "
            "de Studio con `youber-journal import`."
        )
    report = build_report(rows, metric=args.metric, min_n=args.min_n)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report, encoding="utf-8")
        console.print(f"✓ Informe guardado: [bold]{args.output}[/]")
    elif args.json:
        console.print(report, markup=False, soft_wrap=True)
    return 0


def _parse_now(raw: str | None) -> datetime | None:
    """Fecha de referencia (ISO-8601) para calcular antigüedades.

    ``None`` (o vacío) deja que ``pending_metrics`` use el reloj real; pasar una
    fecha hace el informe reproducible (útil para probar y para simular).
    """
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise ValueError(f"Fecha inválida en --now: {raw!r} (usa ISO-8601)") from error


def _run_pending(journal: DecisionJournal, args: argparse.Namespace) -> int:
    windows = tuple(part.strip() for part in args.windows.split(",") if part.strip())
    now = _parse_now(args.now)
    report = pending_metrics(
        journal,
        windows=windows or DEFAULT_WINDOWS,
        min_age_days=args.min_age_days,
        require_upload=not args.include_unpublished,
        now=now,
    )
    if args.json:
        console.print(
            json.dumps(
                json.loads(report.model_dump_json()), ensure_ascii=False, indent=2
            ),
            markup=False,
            soft_wrap=True,
        )
        return 0
    console.print(
        report.message(),
        style="yellow" if report.needs_attention else "green",
        markup=False,
        soft_wrap=True,
    )
    return 0


def _run_stats(journal: DecisionJournal, args: argparse.Namespace) -> int:
    stats = journal.stats()
    if args.json:
        console.print(
            json.dumps(stats, ensure_ascii=False), markup=False, soft_wrap=True
        )
        return 0
    console.print(
        Panel.fit(
            f"[bold]Journal:[/] {stats['db_path']}\n"
            f"Decisiones: [bold]{stats['decisions']}[/] · "
            f"con métricas: [bold]{stats['with_performance']}[/] · "
            f"mediciones: [bold]{stats['snapshots']}[/] · "
            f"subidas: [bold]{stats['uploaded']}[/]",
            title="youber-journal",
            border_style="cyan",
        )
    )
    return 0


def _run_remove(journal: DecisionJournal, args: argparse.Namespace) -> int:
    if not args.yes:
        console.print("[yellow]Añade --yes para confirmar el borrado.[/]")
        return 1
    if not journal.remove(args.decision_id):
        console.print(f"[red]✗ No existe la decisión {args.decision_id!r}[/]")
        return 1
    console.print(f"✓ Decisión {args.decision_id} eliminada")
    return 0


_COMMANDS = {
    "list": _run_list,
    "show": _run_show,
    "upload": _run_upload,
    "performance": _run_performance,
    "import": _run_import,
    "dataset": _run_dataset,
    "analyze": _run_analyze,
    "pending": _run_pending,
    "stats": _run_stats,
    "remove": _run_remove,
}


def main() -> None:
    """Entry point de ``youber-journal``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    journal = DecisionJournal(args.db)
    try:
        code = _COMMANDS[args.command](journal, args)
    except (KeyError, ValueError) as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        code = 1
    finally:
        journal.close()
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
