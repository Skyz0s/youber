"""Prueba de funcionamiento de **todo el proceso** (end-to-end, offline).

Ejecuta la cadena completa de BARF sobre datos sintéticos, sin red y sin
cuentas externas, comprobando cada etapa y saliendo con código 0 solo si todo
pasa:

1. **Catálogo**: genera audio (FFmpeg) + letras `.txt` (una triste, una alegre).
2. **Clips propios**: dos clips de vídeo sintéticos (los pasa el flujo como
   clips locales, sin depender de stock).
3. **Pipeline**: ``youber-workflow --lyrics-video`` (canal sintético temático)
   → perfil de metadatos → canción elegida por su letra → prompt/guion →
   render con FFmpeg.
4. **Journal**: la decisión queda registrada (atributos, canción + motivo,
   ranking de candidatas, artefactos, vídeo).
5. **Subida + métricas**: se asocia un id de vídeo y se anotan métricas de 7d.
6. **Importación**: CSV de YouTube Studio (modo avanzado, es-ES) → ventana 28d.
7. **Dataset + análisis**: features → resultados + informe de correlaciones.
8. **Recordatorio**: `pending_metrics` detecta lo que falta medir.

Uso:

.. code-block:: bash

    python examples/e2e_pipeline.py                  # escribe en ./e2e-run
    python examples/e2e_pipeline.py --workdir C:/tmp/e2e --duration 6

Todo lo generado queda en el directorio de trabajo para inspeccionarlo.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from youber.cli import workflow_cli
from youber.cli.workflow_cli import run_lyrics_video
from youber.journal import (
    DecisionJournal,
    DecisionRecord,
    PerformanceSnapshot,
    build_report,
    import_analytics_csv,
)
from youber.journal.reminders import pending_metrics
from youber.research.data_models import ChannelData, VideoData

console = Console()

SAD_LYRICS = (
    "La noche cae y el dolor no se va, lágrimas en la soledad, "
    "todo está perdido, adiós, la tristeza me acompaña."
)
HAPPY_LYRICS = "Hoy es un día feliz, alegría y risas, celebramos el amor y la luz."

E2E_VIDEO_ID = "e2e0001abc"


@dataclass
class Step:
    """Una etapa comprobada del proceso."""

    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Preparación de datos sintéticos
# ---------------------------------------------------------------------------


def _run_ffmpeg(args: list[str]) -> None:
    """Ejecuta FFmpeg y falla con un mensaje claro si algo va mal."""
    result = subprocess.run(
        ["ffmpeg", *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg falló: {result.stderr[-500:]}")


def build_catalog(workdir: Path) -> tuple[Path, Path]:
    """Genera el catálogo de música (2 pistas) y las letras (2 ficheros)."""
    music_dir = workdir / "music"
    lyrics_dir = workdir / "letras"
    music_dir.mkdir(parents=True, exist_ok=True)
    lyrics_dir.mkdir(parents=True, exist_ok=True)
    for name, freq in (("Adios", 220), ("Alegria", 660)):
        _run_ffmpeg(
            [
                "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=8",
                "-c:a", "libmp3lame", str(music_dir / f"{name}.mp3"),
            ]
        )
    (lyrics_dir / "Adios.txt").write_text(SAD_LYRICS, encoding="utf-8")
    (lyrics_dir / "Alegria.txt").write_text(HAPPY_LYRICS, encoding="utf-8")
    return music_dir, lyrics_dir


def build_clips(workdir: Path, duration: int) -> list[Path]:
    """Genera dos clips de vídeo sintéticos (B-roll propio)."""
    clips_dir = workdir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    sources = ["testsrc", "smptebars"]
    clips: list[Path] = []
    for index, source in enumerate(sources):
        clip = clips_dir / f"clip{index}.mp4"
        _run_ffmpeg(
            [
                "-y", "-f", "lavfi",
                "-i", f"{source}=duration={duration}:size=640x360:rate=25",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
            ]
        )
        clips.append(clip)
    return clips


def themed_channel() -> ChannelData:
    """Canal sintético con metadatos tristes (para que el matching sea visible).

    Con ``--demo`` el flujo usa un canal genérico de programación; aquí se
    sustituye por uno temático para comprobar que la canción elegida por la
    letra encaja con el contenido.
    """
    base = "https://www.youtube.com/@e2e"
    return ChannelData(
        name="Canal E2E (sintético)",
        url=base,
        handle="e2e",
        subscribers="1 K",
        videos=[
            VideoData(
                title="La soledad de la noche",
                url=f"{base}/watch?v=1",
                video_id="e2e1",
                views="1 K",
                description="Un vídeo sobre la tristeza y las lágrimas del adiós.",
                hashtags=["tristeza", "soledad"],
                channel_name="Canal E2E (sintético)",
                channel_url=base,
            )
        ],
    )


def write_studio_csv(path: Path) -> Path:
    """CSV de YouTube Studio (modo avanzado, es-ES, delimitado por ``;``)."""
    rows = [
        [
            "ID del vídeo",
            "Título del vídeo",
            "Impresiones",
            "CTR de las impresiones (%)",
            "Visualizaciones",
            "Tiempo de visualización (horas)",
            "Duración media de la visualización",
            "Porcentaje medio visto (%)",
            "Me gusta",
            "Comentarios",
            "Compartidos",
            "Suscriptores ganados",
            "Suscriptores perdidos",
        ],
        [
            E2E_VIDEO_ID,
            "La noche",
            "28.500",
            "4,8",
            "1.310",
            "11,5",
            "1:32",
            "39,2",
            "88",
            "21",
            "6",
            "17",
            "3",
        ],
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle, delimiter=";").writerows(rows)
    return path


# ---------------------------------------------------------------------------
# Proceso completo
# ---------------------------------------------------------------------------


async def run_e2e(workdir: Path, *, duration: int = 6) -> dict[str, Any]:
    """Ejecuta y comprueba todo el proceso.

    Args:
        workdir: Directorio donde se genera todo (se crea si no existe).
        duration: Duración de los clips/canción sintéticos (segundos).

    Returns:
        ``{"ok": bool, "checks": [Step], "artifacts": {nombre: Path}, ...}``.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    checks: list[Step] = []
    artifacts: dict[str, Path] = {}

    # --- 1. Catálogo de música + letras ---------------------------------
    music_dir, lyrics_dir = build_catalog(workdir)
    tracks = list(music_dir.glob("*.mp3"))
    lyrics = list(lyrics_dir.glob("*.txt"))
    checks.append(
        Step(
            "1. Catálogo (audio + letras)",
            len(tracks) == 2 and len(lyrics) == 2,
            f"{len(tracks)} pistas · {len(lyrics)} letras",
        )
    )

    # --- 2. Clips propios ------------------------------------------------
    clips = build_clips(workdir, duration)
    checks.append(
        Step(
            "2. Clips locales (FFmpeg)",
            all(clip.is_file() and clip.stat().st_size > 0 for clip in clips),
            f"{len(clips)} clips en {clips[0].parent.name}/",
        )
    )

    # --- 3. Pipeline metadatos → letras → prompt → vídeo ----------------
    workflow_cli.demo_channel = themed_channel
    journal_db = workdir / "journal.db"
    out_dir = workdir / "out"
    result = await run_lyrics_video(
        demo=True,
        topic="La noche y el adiós",
        output_dir=str(out_dir),
        library_dir=str(music_dir),
        lyrics_dir=str(lyrics_dir),
        clips=[str(clip) for clip in clips],
        stock="none",
        duration=duration,
        journal_db=str(journal_db),
    )
    final_video = Path(result["final_video"]) if result["final_video"] else None
    if final_video is not None:
        artifacts["vídeo final"] = final_video
    checks.append(
        Step(
            "3. Pipeline completo (workflow --lyrics-video)",
            bool(final_video and final_video.is_file() and final_video.stat().st_size > 1000),
            f"{final_video.name} · {final_video.stat().st_size // 1024} KB"
            if final_video and final_video.is_file()
            else "sin vídeo",
        )
    )

    # --- 4. Decisión registrada en el journal ---------------------------
    journal = DecisionJournal(journal_db)
    record = journal.get(str(result["decision_id"])) if result["decision_id"] else None
    chosen = record.track.chosen_title if record else None
    checks.append(
        Step(
            "4. Decisión en el journal",
            bool(
                record
                and chosen == "Adios"  # gana la canción triste (metadatos tristes)
                and record.attributes.dominant_theme == "tristeza"
                and len(record.track.candidates) >= 2
                and record.video.clip_source == "local"
            ),
            (
                f"{record.id} · canción «{chosen}» · candidatas "
                f"{[c.track_id[:6] for c in record.track.candidates]} · "
                f"tema {record.attributes.dominant_theme}"
            )
            if record
            else "no se registró la decisión",
            data={"decision_id": record.id} if record else {},
        )
    )

    # --- 5. Subida + métricas a 7 días ----------------------------------
    if record is not None:
        journal.attach_upload(
            record.id,
            video_id=E2E_VIDEO_ID,
            url=f"https://youtu.be/{E2E_VIDEO_ID}",
            title="La noche",
            privacy="public",
            published_at=datetime.now() - timedelta(days=10),
        )
        journal.record_performance(
            record.id,
            PerformanceSnapshot(
                window="7d", views=410, impressions=8200, ctr=5.0, avg_view_percentage=41.5
            ),
        )
    week = journal.latest_performance(str(result["decision_id"]), window="7d")
    checks.append(
        Step(
            "5. Subida + métricas 7d",
            bool(week and week.views == 410 and week.ctr == 5.0),
            f"vistas {week.views} · CTR {week.ctr} % · retención {week.retention} %"
            if week
            else "sin métricas",
        )
    )

    # --- 6. Importación del CSV de Studio (28d) -------------------------
    csv_path = write_studio_csv(workdir / "studio_analytics.csv")
    artifacts["CSV de Studio"] = csv_path
    import_result, pending = import_analytics_csv(
        journal.list_natural(), csv_path, window="28d"
    )
    for decision_id, snapshot in pending:
        journal.storage.add_performance(decision_id, snapshot)
    month = journal.latest_performance(str(result["decision_id"]), window="28d")
    checks.append(
        Step(
            "6. Importación CSV de Studio (28d)",
            bool(
                import_result.applied == 1
                and import_result.matched
                and import_result.matched[0].matched_by == "video_id"
                and month
                and month.views == 1310
                and month.retention == 39.2
            ),
            (
                f"1 fila cruzada por {import_result.matched[0].matched_by} · "
                f"vistas {month.views} · CTR {month.ctr} % · retención {month.retention} %"
            )
            if month and import_result.matched
            else "sin cruce",
        )
    )

    # --- 7. Dataset + informe de análisis --------------------------------
    rows = journal.dataset(window="28d")
    row = rows[0] if rows else None
    report = build_report(rows, metric="ctr")
    report_path = workdir / "informe.md"
    report_path.write_text(report, encoding="utf-8")
    artifacts["informe de análisis"] = report_path
    checks.append(
        Step(
            "7. Dataset + informe",
            bool(
                row
                and row.outcomes.get("views") == 1310
                and row.outcomes.get("ctr") == 4.8
                and row.features.get("theme_score") is not None
                and "Informe del registro" in report
            ),
            (
                f"features: theme_score={row.features.get('theme_score')} · "
                f"resultados: CTR {row.outcomes.get('ctr')} %"
            )
            if row
            else "dataset vacío",
        )
    )

    # --- 8. Recordatorio de métricas -------------------------------------
    al_dia = pending_metrics(journal, min_age_days=0)
    journal.record(
        DecisionRecord(
            id="dec-e2e-pendiente",
            topic="Vídeo pendiente de medir",
            created_at=datetime.now() - timedelta(days=12),
        )
    )
    journal.attach_upload(
        "dec-e2e-pendiente",
        video_id="e2e0002xyz",
        published_at=datetime.now() - timedelta(days=12),
    )
    con_pendientes = pending_metrics(journal, min_age_days=0)
    checks.append(
        Step(
            "8. Recordatorio de métricas",
            not al_dia.needs_attention and len(con_pendientes.pending) == 1,
            "al día con el vídeo medido · detecta el pendiente"
            if not al_dia.needs_attention and len(con_pendientes.pending) == 1
            else f"al_dia={len(al_dia.pending)} · pendientes={len(con_pendientes.pending)}",
        )
    )

    artifacts["journal"] = journal_db
    journal.close()
    return {
        "ok": all(check.ok for check in checks),
        "checks": checks,
        "artifacts": artifacts,
        "result": result,
        "decision_id": record.id if record else None,
        "workdir": workdir,
    }


def _print_summary(outcome: dict[str, Any]) -> None:
    """Tabla resumen con el resultado de cada etapa."""
    table = Table(title="Prueba de funcionamiento (end-to-end, offline)")
    table.add_column("#", justify="right")
    table.add_column("Etapa")
    table.add_column("Estado", justify="center")
    table.add_column("Detalle")
    for check in outcome["checks"]:
        table.add_row(
            check.name.split(".")[0],
            check.name.split(". ", 1)[-1],
            "✅" if check.ok else "❌",
            check.detail,
        )
    console.print(table)
    console.print("Artefactos generados:")
    for name, path in outcome["artifacts"].items():
        console.print(f"  • {name}: [cyan]{path}[/]")
    estilo = "green" if outcome["ok"] else "red"
    console.print(
        Panel.fit(
            "TODO OK ✅ — el proceso completo funciona de punta a punta"
            if outcome["ok"]
            else "HAY FALLOS ❌ — revisa las etapas marcadas",
            border_style=estilo,
        )
    )


def main() -> None:
    """Entry point de la prueba end-to-end."""
    parser = argparse.ArgumentParser(
        prog="e2e_pipeline",
        description="Prueba de funcionamiento de todo el proceso de BARF (offline)",
    )
    parser.add_argument(
        "--workdir", default="e2e-run", help="Directorio de trabajo (default: e2e-run)"
    )
    parser.add_argument("--duration", type=int, default=6, help="Duración de los medios (s)")
    args = parser.parse_args()

    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        console.print(f"[red]✗ Falta FFmpeg ({', '.join(missing)}): instalalo para la prueba.[/]")
        raise SystemExit(2)

    outcome = asyncio.run(run_e2e(Path(args.workdir), duration=args.duration))
    _print_summary(outcome)
    if not outcome["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
