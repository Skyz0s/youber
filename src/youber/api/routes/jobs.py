"""Ruta ``jobs`` — lanzamiento y seguimiento de trabajos de larga duración.

Un "job" ejecuta uno de los CLIs de Youber (produce/workflow/upload) en un
proceso worker *detached*: ``submit`` crea el registro (queued), guarda el
JSON en ``~/.youber/jobs/`` y lanza ``python -m youber.api.routes.jobs
<job_id>``; ese worker ejecuta el comando, vuelca stdout+stderr a
``<workdir>/run.log`` y actualiza el registro (running → done/failed).

Seguridad: los argv se construyen solo con flags de una lista blanca por
tipo (nunca shell); valores que empiezan por ``-`` se rechazan.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from youber.api.models import ApiError, JobRecord, JobStatus

DEFAULT_JOBS_DIR = Path.home() / ".youber" / "jobs"

# Ids de job: carácter seguro (alnum + guiones), nunca separadores de ruta
# ni puntos → anti path-traversal en load_record ("../../x" queda fuera).
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Tipos de job y módulos CLI asociados.
_JOB_TYPES: dict[str, str] = {
    "produce": "youber.montage.cli",
    "workflow": "youber.cli.workflow_cli",
    "upload": "youber.upload.cli",
}

# Flags permitidos por tipo: key del parámetro → (flag, tipo: value|flag).
_PRODUCE_FLAGS: dict[str, tuple[str, str]] = {
    "topic": ("--topic", "value"),
    "pattern": ("--pattern", "value"),
    "pipeline": ("--pipeline", "value"),
    "track": ("--track", "value"),
    "library": ("--library", "value"),
    "style": ("--style", "value"),
    "lyrics": ("--lyrics", "value"),
    "model": ("--model", "value"),
    "duration": ("--duration", "value"),
    "resolution": ("--resolution", "value"),
    "fps": ("--fps", "value"),
    "output": ("--output", "value"),
    "sync": ("--sync", "flag"),
    "whisper": ("--whisper", "flag"),
}
_WORKFLOW_FLAGS: dict[str, tuple[str, str]] = {
    "channel": ("--channel", "value"),
    "duration": ("--duration", "value"),
    "track": ("--track", "value"),
    "library": ("--library", "value"),
    "style": ("--style", "value"),
    "lyrics": ("--lyrics", "value"),
    "model": ("--model", "value"),
    "output_dir": ("--output-dir", "value"),
    "privacy": ("--privacy", "value"),
    "demo": ("--demo", "flag"),
    "sync": ("--sync", "flag"),
    "whisper": ("--whisper", "flag"),
    "upload": ("--upload", "flag"),
}
_UPLOAD_POSITIONAL = ("video",)
_UPLOAD_FLAGS: dict[str, tuple[str, str]] = {
    "title": ("--title", "value"),
    "description": ("--description", "value"),
    "tags": ("--tags", "value"),
    "category": ("--category", "value"),
    "privacy": ("--privacy", "value"),
}


def jobs_dir() -> Path:
    """Directorio de registros (override con ``YOUBER_JOBS_DIR`` para tests)."""
    override = os.environ.get("YOUBER_JOBS_DIR")
    return Path(override) if override else DEFAULT_JOBS_DIR


# ---------------------------------------------------------------------------
# Almacenamiento
# ---------------------------------------------------------------------------


def _record_path(job_id: str) -> Path:
    if not isinstance(job_id, str) or not _JOB_ID_RE.match(job_id):
        raise ApiError(f"Id de job inválido: {job_id!r}")
    return jobs_dir() / f"{job_id}.json"


def save_record(record: JobRecord) -> None:
    jobs_dir().mkdir(parents=True, exist_ok=True)
    _record_path(record.id).write_text(
        record.model_dump_json(indent=2), encoding="utf-8"
    )


def load_record(job_id: str) -> JobRecord:
    path = _record_path(job_id)
    if not path.is_file():
        raise ApiError(f"Job no encontrado: {job_id}")
    return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))


def list_records() -> list[JobRecord]:
    """Todos los registros, del más reciente al más antiguo."""
    if not jobs_dir().is_dir():
        return []
    records: list[JobRecord] = []
    for path in sorted(jobs_dir().glob("*.json"), reverse=True):
        try:
            records.append(JobRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records


def count_active() -> tuple[int, int]:
    """(queued, running) para el estado general del dashboard."""
    queued = running = 0
    for record in list_records():
        if record.status == JobStatus.QUEUED:
            queued += 1
        elif record.status == JobStatus.RUNNING:
            running += 1
    return queued, running


# ---------------------------------------------------------------------------
# Construcción del comando (whitelist, sin shell)
# ---------------------------------------------------------------------------


def _guard_value(value: object, label: str) -> str:
    """Valores de flags: string plano y que no empiece por '-' (anti-inyección)."""
    if not isinstance(value, str):
        raise ApiError(f"Parámetro inválido para {label}: se esperaba texto")
    if value.startswith("-"):
        raise ApiError(f"Parámetro inválido para {label}: no puede empezar por '-'")
    return value


def _append_flags(argv: list[str], params: dict[str, Any], flags: dict[str, tuple[str, str]]) -> None:
    for key, (flag, kind) in flags.items():
        if key not in params or params[key] in (None, "", False):
            continue
        if kind == "flag":
            argv.append(flag)
            continue
        raw = params[key]
        if key == "tags" and isinstance(raw, (list, tuple)):
            value = ",".join(str(tag) for tag in raw)
        else:
            value = _guard_value(raw, key)
        argv += [flag, value]


def build_command(job_type: str, params: dict[str, Any]) -> list[str]:
    """Construye el argv del job (python -m <cli> + flags permitidos)."""
    module = _JOB_TYPES.get(job_type)
    if module is None:
        raise ApiError(f"Tipo de job desconocido: {job_type!r} (produce|workflow|upload)")

    argv = [sys.executable, "-m", module]

    if job_type == "produce":
        if not params.get("topic") and not params.get("pattern"):
            raise ApiError("jobs submit produce requiere --topic o --pattern")
        _append_flags(argv, params, _PRODUCE_FLAGS)
    elif job_type == "workflow":
        if not params.get("demo") and not params.get("channel"):
            raise ApiError("jobs submit workflow requiere --channel o --demo")
        _append_flags(argv, params, _WORKFLOW_FLAGS)
    elif job_type == "upload":
        video = params.get("video")
        if not video or not params.get("title"):
            raise ApiError("jobs submit upload requiere --video y --title")
        argv.append(_guard_value(video, "video"))
        _append_flags(argv, params, _UPLOAD_FLAGS)
    return argv


# ---------------------------------------------------------------------------
# Worker (proceso detached)
# ---------------------------------------------------------------------------


async def run_job(job_id: str) -> JobRecord:
    """Ejecuta el comando del job y actualiza el registro (worker)."""
    record = load_record(job_id)
    workdir = jobs_dir() / job_id
    workdir.mkdir(parents=True, exist_ok=True)

    record.status = JobStatus.RUNNING
    record.started_at = datetime.now(UTC)
    save_record(record)

    log_path = workdir / "run.log"
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            proc = await asyncio.create_subprocess_exec(
                *record.command,
                cwd=str(workdir),
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
            exit_code = await proc.wait()
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        record.log = tail
        record.exit_code = exit_code
        if exit_code == 0:
            record.status = JobStatus.DONE
            record.output_path = _find_output(workdir)
        else:
            record.status = JobStatus.FAILED
            record.error = tail[-800:] or "Comando falló sin salida"
    except Exception as exc:  # noqa: BLE001 — el worker registra y sigue
        record.status = JobStatus.FAILED
        record.error = str(exc)
    record.finished_at = datetime.now(UTC)
    save_record(record)
    return record


def _find_output(workdir: Path) -> Path | None:
    """El .mp4 más reciente del directorio de trabajo (artefacto del job)."""
    candidates = sorted(workdir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _spawn_worker(job_id: str) -> None:
    """Lanza el worker detached (no bloquea al CLI)."""
    argv = [sys.executable, "-m", "youber.api.routes.jobs", job_id]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)  # noqa: S603 — argv controlado por whitelist


# ---------------------------------------------------------------------------
# Handlers de la ruta
# ---------------------------------------------------------------------------


def _new_job_id() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


async def submit(params: dict[str, Any]) -> dict[str, Any]:
    """Crea un job (queued) y lanza el worker en segundo plano."""
    job_type = str(params.get("type", "")).strip()
    command = build_command(job_type, params)

    record = JobRecord(
        id=_new_job_id(),
        type=job_type,
        status=JobStatus.QUEUED,
        params={k: v for k, v in params.items() if v not in (None, "")},
        command=command,
    )
    save_record(record)
    try:
        _spawn_worker(record.id)
    except Exception as exc:  # noqa: BLE001
        record.status = JobStatus.FAILED
        record.error = f"No se pudo lanzar el worker: {exc}"
        save_record(record)
    return record.model_dump(mode="json")


async def status(params: dict[str, Any]) -> dict[str, Any]:
    """Estado de un job por id."""
    job_id = str(params.get("id", "")).strip()
    if not job_id:
        raise ApiError("Falta el parámetro 'id' del job")
    return load_record(job_id).model_dump(mode="json")


async def history(params: dict[str, Any]) -> dict[str, Any]:
    """Historial de jobs (del más reciente al más antiguo)."""
    try:
        limit = max(1, min(int(params.get("limit", 20)), 200))
    except (TypeError, ValueError):
        limit = 20
    records = list_records()[:limit]
    return {
        "count": len(records),
        "jobs": [record.model_dump(mode="json") for record in records],
    }


if __name__ == "__main__":  # worker: python -m youber.api.routes.jobs <job_id>
    import asyncio

    asyncio.run(run_job(sys.argv[1]))
