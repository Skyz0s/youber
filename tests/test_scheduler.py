"""Tests del scheduler de BARF (models, storage, jobs, executor, scheduler, daemon, cli)."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from youber.scheduler.cli import _job_type, _param, _schedule_type, build_parser
from youber.scheduler.daemon import Daemon, run_daemon
from youber.scheduler.executor import JobExecutor, next_run_for
from youber.scheduler.jobs import run_job
from youber.scheduler.models import JobType, ScheduledJob, ScheduleType
from youber.scheduler.scheduler import Scheduler
from youber.scheduler.storage import JobStorage

NOW = datetime(2026, 8, 31, 12, 0, 0)  # lunes 2026-08-31 12:00


def make_job(
    schedule_type: ScheduleType = ScheduleType.DAILY,
    schedule_value: str = "09:00",
    enabled: bool = True,
    **kwargs,
) -> ScheduledJob:
    defaults = {
        "id": "job1",
        "name": "test",
        "job_type": JobType.RESEARCH,
        "schedule_type": schedule_type,
        "schedule_value": schedule_value,
        "params": {"channel": "@python"},
        "enabled": enabled,
    }
    defaults.update(kwargs)
    return ScheduledJob(**defaults)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_job_type_values():
    assert JobType.RESEARCH == "research"
    assert JobType.WORKFLOW == "workflow"
    assert JobType.UPLOAD == "upload"
    assert JobType.MUSIC_SCAN == "music_scan"


def test_schedule_type_values():
    assert ScheduleType.ONCE == "once"
    assert ScheduleType.DAILY == "daily"
    assert ScheduleType.WEEKLY == "weekly"
    assert ScheduleType.CRON == "cron"


def test_scheduled_job_defaults():
    job = ScheduledJob(id="x", name="n", job_type=JobType.RESEARCH, schedule_type=ScheduleType.DAILY, schedule_value="09:00")
    assert job.params == {}
    assert job.enabled is True
    assert job.last_run is None
    assert job.next_run is None
    assert job.created_at is not None


def test_scheduled_job_validation():
    with pytest.raises(ValidationError):
        ScheduledJob(id="", name="", job_type="nope", schedule_type="nope", schedule_value="")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def test_storage_roundtrip(tmp_path: Path):
    storage = JobStorage(tmp_path / "jobs.json")
    job = make_job()
    storage.add(job)
    assert storage.get("job1") is not None
    assert storage.get("no") is None

    job.enabled = False
    assert storage.update(job) is True
    assert storage.get("job1").enabled is False  # type: ignore[union-attr]

    assert storage.remove("job1") is True
    assert storage.load() == []
    assert storage.remove("job1") is False


# ---------------------------------------------------------------------------
# next_run_for
# ---------------------------------------------------------------------------


def test_next_run_once_future():
    job = make_job(ScheduleType.ONCE, "2026-09-15 10:00:00")
    nxt = next_run_for(job, NOW)
    assert nxt == datetime(2026, 9, 15, 10, 0, 0)


def test_next_run_once_past_returns_none():
    job = make_job(ScheduleType.ONCE, "2026-01-01 10:00:00")
    assert next_run_for(job, NOW) is None


def test_next_run_daily_today_or_tomorrow():
    job = make_job(ScheduleType.DAILY, "10:00")
    assert next_run_for(job, NOW) == datetime(2026, 9, 1, 10, 0, 0)  # hoy ya pasó → mañana
    job2 = make_job(ScheduleType.DAILY, "14:00")
    assert next_run_for(job2, NOW) == datetime(2026, 8, 31, 14, 0, 0)  # hoy


def test_next_run_weekly():
    job = make_job(ScheduleType.WEEKLY, "monday 09:00")
    nxt = next_run_for(job, NOW)
    # NOW es lunes 12:00 → ya pasó el lunes 09:00 → próximo lunes
    assert nxt.weekday() == 0
    assert nxt.hour == 9
    assert nxt > NOW

    job2 = make_job(ScheduleType.WEEKLY, "wednesday 10:30")
    nxt2 = next_run_for(job2, NOW)
    assert nxt2.weekday() == 2
    assert nxt2.hour == 10
    assert nxt2.minute == 30


def test_next_run_cron():
    # Cada día a las 00:30
    job = make_job(ScheduleType.CRON, "30 0 * * *")
    nxt = next_run_for(job, NOW)
    assert nxt == datetime(2026, 9, 1, 0, 30, 0)

    # Cada hora en el minuto 5 (desde las 12:00 → la próxima es las 12:05)
    job2 = make_job(ScheduleType.CRON, "5 * * * *")
    nxt2 = next_run_for(job2, NOW)
    assert nxt2 == datetime(2026, 8, 31, 12, 5, 0)


def test_next_run_invalid():
    assert next_run_for(make_job(ScheduleType.DAILY, "abc"), NOW) is None
    assert next_run_for(make_job(ScheduleType.WEEKLY, "noday"), NOW) is None
    assert next_run_for(make_job(ScheduleType.CRON, "solo-2-campos"), NOW) is None


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def test_scheduler_add_and_list(tmp_path: Path):
    scheduler = Scheduler(storage=JobStorage(tmp_path / "j.json"))
    job = scheduler.add_job("mi trabajo", "research", "daily", "09:00", {"channel": "@python"})
    assert job.id
    assert job.next_run is not None
    assert len(scheduler.list_jobs()) == 1
    assert scheduler.get_job(job.id) is not None

    assert scheduler.remove_job(job.id) is True
    assert scheduler.list_jobs() == []


def test_scheduler_enable_disable(tmp_path: Path):
    scheduler = Scheduler(storage=JobStorage(tmp_path / "j.json"))
    job = scheduler.add_job("t", "research", "daily", "09:00")
    assert scheduler.set_enabled(job.id, False) is True
    assert scheduler.get_job(job.id).enabled is False  # type: ignore[union-attr]
    assert scheduler.set_enabled("no", True) is False


def test_scheduler_due_jobs(tmp_path: Path):
    scheduler = Scheduler(storage=JobStorage(tmp_path / "j.json"))
    due = scheduler.add_job("due", "research", "once", "2026-01-01 00:00:00")  # en el pasado → next_run None
    assert due.next_run is None
    # Un trabajo diario a las 10:00: el próximo run es futuro → no pendiente ahora
    scheduler.add_job("futuro", "research", "daily", "10:00")
    assert scheduler.due_jobs(NOW) == []

    # Fuerza next_run en el pasado
    past = make_job(schedule_type=ScheduleType.ONCE, schedule_value="2026-01-01 00:00:00")
    past.next_run = datetime(2026, 1, 1, 0, 0, 0)
    scheduler.storage.add(past)
    due_jobs = scheduler.due_jobs(NOW)
    assert any(job.id == "job1" for job in due_jobs)


async def test_scheduler_run_due_disables_once(tmp_path: Path):
    scheduler = Scheduler(storage=JobStorage(tmp_path / "j.json"))

    async def fake_execute(job):
        job.last_run = datetime.now()
        return {"status": "ok", "result": {"ok": True}, "error": None}

    scheduler.executor = FakeExecutor(fake_execute)

    job = scheduler.add_job("once", "research", "once", "2026-09-15 10:00:00")
    job.next_run = datetime(2026, 1, 1, 0, 0, 0)  # forzado al pasado
    scheduler.storage.update(job)

    results = await scheduler.run_due(NOW)
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    stored = scheduler.get_job(job.id)
    assert stored.enabled is False  # type: ignore[union-attr]
    assert stored.next_run is None  # type: ignore[union-attr]


class FakeExecutor:
    def __init__(self, fake):
        self._fake = fake

    async def execute(self, job):
        return await self._fake(job)


# ---------------------------------------------------------------------------
# Jobs (runners con mocks)
# ---------------------------------------------------------------------------


async def test_run_job_research(monkeypatch):
    class FakeAnalyzer:
        async def analyze(self, channel, max_videos=10, mode="html"):
            return SimpleNamespace(name="Canal", videos=[1, 2], subscribers="10")

    from types import SimpleNamespace

    # El runner importa ChannelAnalyzer dentro de la función → mockear la fuente.
    monkeypatch.setattr("youber.research.channel_analyzer.ChannelAnalyzer", FakeAnalyzer)
    job = make_job(params={"channel": "@python", "max_videos": 5})
    result = await run_job(job)
    assert result["channel"] == "Canal"
    assert result["videos"] == 2


async def test_run_job_unknown_type(monkeypatch):
    # Sin runners registrados, cualquier tipo válido debe lanzar ValueError.
    monkeypatch.setattr("youber.scheduler.jobs.JOB_RUNNERS", {})
    job = make_job()
    with pytest.raises(ValueError):
        await run_job(job)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


async def test_executor_ok(monkeypatch):
    async def fake_run(job):
        return {"channel": "X"}

    monkeypatch.setattr("youber.scheduler.executor.run_job", fake_run)
    executor = JobExecutor()
    job = make_job()
    result = await executor.execute(job)
    assert result["status"] == "ok"
    assert result["result"] == {"channel": "X"}
    assert job.last_run is not None


async def test_executor_error(monkeypatch):
    async def fake_run(job):
        raise RuntimeError("boom")

    monkeypatch.setattr("youber.scheduler.executor.run_job", fake_run)
    executor = JobExecutor()
    result = await executor.execute(make_job())
    assert result["status"] == "error"
    assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


async def test_run_daemon_stops_on_event(tmp_path: Path):
    scheduler = Scheduler(storage=JobStorage(tmp_path / "j.json"))
    stop = asyncio.Event()

    async def fake_run_due(now):
        return []

    scheduler.run_due = fake_run_due  # type: ignore[method-assign]
    task = asyncio.create_task(run_daemon(scheduler, interval=0.05, stop_event=stop))
    await asyncio.sleep(0.15)
    stop.set()
    await task  # no debe colgar


async def test_daemon_wrapper(tmp_path: Path):
    scheduler = Scheduler(storage=JobStorage(tmp_path / "j.json"))
    daemon = Daemon(scheduler, interval=0.05)

    async def fake_run_due(now):
        return []

    scheduler.run_due = fake_run_due  # type: ignore[method-assign]
    await daemon.start()
    await asyncio.sleep(0.1)
    await daemon.stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_types():
    import argparse

    assert _job_type("research") == JobType.RESEARCH
    assert _schedule_type("DAILY") == ScheduleType.DAILY
    assert _param("channel=@python") == ("channel", "@python")
    with pytest.raises(argparse.ArgumentTypeError):
        _job_type("nope")
    with pytest.raises(argparse.ArgumentTypeError):
        _param("sin-igual")


def test_cli_parser():
    parser = build_parser()
    args = parser.parse_args(
        ["add", "--name", "t", "--type", "research", "--schedule", "daily", "--at", "09:00", "--param", "channel=@python"]
    )
    assert args.command == "add"
    assert args.type == JobType.RESEARCH
    assert args.param == [("channel", "@python")]
    assert parser.parse_args(["list"]).command == "list"
    assert parser.parse_args(["daemon", "--interval", "5"]).interval == 5
