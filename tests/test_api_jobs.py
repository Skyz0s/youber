"""Tests del job runner de youber.api (routes/jobs.py).

Sin red: se construyen argv con la whitelist, el submit se prueba con el
spawn mockeado (no lanzamos workers reales en tests salvo run_job con un
comando trivial de python), y run_job ejecuta subprocesos reales rápidos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from youber.api.models import ApiError, JobRecord, JobStatus
from youber.api.routes.jobs import (
    build_command,
    count_active,
    history,
    run_job,
    save_record,
    status,
    submit,
)

# ---------------------------------------------------------------------------
# build_command (whitelist por tipo)
# ---------------------------------------------------------------------------


def test_build_produce_con_flags():
    argv = build_command(
        "produce",
        {
            "topic": "Python",
            "pipeline": "screen-demo",
            "track": "mi cancion",
            "sync": True,
            "style": "box",
        },
    )
    assert argv[:3] == [sys.executable, "-m", "youber.montage.cli"]
    assert "--topic" in argv and "Python" in argv
    assert "--pipeline" in argv and "screen-demo" in argv
    assert "--sync" in argv
    assert "--style" in argv and "box" in argv


def test_build_produce_requiere_topic_o_pattern():
    with pytest.raises(ApiError, match="--topic o --pattern"):
        build_command("produce", {})


def test_build_workflow_requiere_channel_o_demo():
    with pytest.raises(ApiError, match="--channel o --demo"):
        build_command("workflow", {})
    argv = build_command("workflow", {"channel": "@python", "sync": True})
    assert "-m" in argv and "youber.cli.workflow_cli" in argv


def test_build_upload_requiere_video_y_title():
    with pytest.raises(ApiError, match="--video y --title"):
        build_command("upload", {"video": "x.mp4"})
    argv = build_command("upload", {"video": "x.mp4", "title": "Mi vídeo"})
    assert argv[-2:] == ["--title", "Mi vídeo"]


def test_build_tipo_desconocido():
    with pytest.raises(ApiError, match="Tipo de job desconocido"):
        build_command("magia", {})


def test_build_rechaza_valores_con_guion():
    with pytest.raises(ApiError, match="no puede empezar por '-'"):
        build_command("produce", {"topic": "--sync"})


# ---------------------------------------------------------------------------
# submit / status / history (spawn mockeado)
# ---------------------------------------------------------------------------


async def test_submit_y_status_queued(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUBER_JOBS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "youber.api.routes.jobs._spawn_worker", lambda _job_id: None
    )

    record = await submit(
        {"type": "produce", "topic": "Python", "pipeline": "screen-demo", "sync": True}
    )
    assert record["status"] == JobStatus.QUEUED.value
    job_id = record["id"]

    saved = await status({"id": job_id})
    assert saved["type"] == "produce"
    assert saved["command"][0] == sys.executable

    hist = await history({})
    assert any(job["id"] == job_id for job in hist["jobs"])

    queued, running = count_active()
    assert queued >= 1 and running == 0


async def test_status_job_desconocido(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUBER_JOBS_DIR", str(tmp_path))
    from youber.api.server import handle

    envelope = await handle("jobs.status", {"id": "no-existe"})
    assert envelope["ok"] is False
    assert "no encontrado" in envelope["error"]


async def test_status_rechaza_id_con_traversal(tmp_path: Path, monkeypatch):
    """Ids tipo '../../x' no pueden salir del directorio de jobs."""
    monkeypatch.setenv("YOUBER_JOBS_DIR", str(tmp_path))
    from youber.api.server import handle

    for evil in ("../../etc/passwd", "..%2F..", "a/b", "\\evil", "....//x"):
        envelope = await handle("jobs.status", {"id": evil})
        assert envelope["ok"] is False
        assert "inválido" in envelope["error"], evil


def test_record_path_rechaza_ids_peligrosos(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUBER_JOBS_DIR", str(tmp_path))
    from youber.api.routes.jobs import _record_path

    for evil in ("..", ".", "../../x", "a/b", "a\\b", "a..b/../c", ""):
        with pytest.raises(ApiError, match="inválido"):
            _record_path(evil)
    # Ids legítimos (hex del runner y de ejemplo) pasan.
    assert _record_path("00f21a2a637c").name == "00f21a2a637c.json"
    assert _record_path("jobtest").name == "jobtest.json"


# ---------------------------------------------------------------------------
# run_job: subproceso real trivial (rápido y sin red)
# ---------------------------------------------------------------------------


async def _submit_trivial(tmp_path: Path, code: str) -> str:
    record = JobRecord(
        id="jobtest",
        type="produce",
        status=JobStatus.QUEUED,
        command=[sys.executable, "-c", code],
    )
    save_record(record)
    return record.id


async def test_run_job_exitoso_registra_log(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUBER_JOBS_DIR", str(tmp_path))
    job_id = await _submit_trivial(tmp_path, "print('hola job')")

    record = await run_job(job_id)
    assert record.status == JobStatus.DONE
    assert record.exit_code == 0
    assert "hola job" in record.log
    assert record.finished_at is not None


async def test_run_job_fallido_guarda_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUBER_JOBS_DIR", str(tmp_path))
    job_id = await _submit_trivial(tmp_path, "import sys; sys.exit(3)")

    record = await run_job(job_id)
    assert record.status == JobStatus.FAILED
    assert record.exit_code == 3
    assert record.error is not None


async def test_run_job_registro_inexistente(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUBER_JOBS_DIR", str(tmp_path))
    with pytest.raises(ApiError):
        await run_job("nada")
