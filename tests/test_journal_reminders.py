"""Tests del recordatorio de métricas (`youber.journal.reminders`) — offline."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from youber.journal import DecisionJournal, DecisionRecord, PerformanceSnapshot
from youber.journal.cli import main as journal_main
from youber.journal.reminders import notify_telegram, pending_metrics

NOW = datetime(2026, 9, 15, 12, 0)


def _published(
    journal: DecisionJournal,
    decision_id: str,
    *,
    topic: str = "Vídeo",
    video_id: str = "abc123",
    days_ago: float = 10,
) -> DecisionRecord:
    """Decisión ya publicada hace ``days_ago`` días."""
    record = DecisionRecord(
        id=decision_id,
        topic=topic,
        created_at=NOW - timedelta(days=days_ago),
    )
    journal.record(record)
    journal.attach_upload(
        record.id,
        video_id=video_id,
        title=topic,
        published_at=NOW - timedelta(days=days_ago),
    )
    return journal.get(decision_id)  # type: ignore[return-value]


def test_pending_detecta_ventanas_que_faltan(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    _published(journal, "dec-viejo", topic="La noche", days_ago=20)
    _published(journal, "dec-medido", topic="Medido", video_id="def456", days_ago=10)
    journal.record_performance(
        "dec-medido", PerformanceSnapshot(window="7d", views=100, ctr=4.0)
    )

    report = pending_metrics(journal, now=NOW)

    assert report.decisions == 2
    assert report.published == 2
    assert report.measured == 1
    assert report.needs_attention is True
    pendientes = {item.decision_id: item for item in report.pending}
    assert set(pendientes) == {"dec-viejo", "dec-medido"}
    assert pendientes["dec-viejo"].missing_windows == ["7d", "28d"]
    assert pendientes["dec-viejo"].measured_windows == []
    assert pendientes["dec-medido"].missing_windows == ["28d"]
    assert pendientes["dec-medido"].measured_windows == ["7d"]
    # El más antiguo primero.
    assert [item.decision_id for item in report.pending] == ["dec-viejo", "dec-medido"]
    assert pendientes["dec-viejo"].age_days == 20.0


def test_pending_ignora_recientes_y_sin_publicar(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    _published(journal, "dec-reciente", days_ago=1)  # demasiado nuevo
    journal.record(DecisionRecord(id="dec-sin-subir", topic="Borrador"))

    report = pending_metrics(journal, now=NOW)
    assert report.pending == []
    assert report.needs_attention is False
    assert report.decisions == 2
    assert report.published == 1

    # Con --include-unpublished sí aparece el borrador (no medible en plataforma).
    ampliado = pending_metrics(
        journal, now=NOW, min_age_days=0, require_upload=False
    )
    ids = {item.decision_id for item in ampliado.pending}
    assert ids == {"dec-reciente", "dec-sin-subir"}


def test_pending_ventanas_personalizadas(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    _published(journal, "dec-1", days_ago=2)

    report = pending_metrics(journal, windows=("24h", "48h"), min_age_days=1, now=NOW)
    assert report.windows == ["24h", "48h"]
    assert report.pending[0].missing_windows == ["24h", "48h"]


def test_mensaje_cuando_todo_esta_al_dia(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    _published(journal, "dec-1", video_id="abc123", days_ago=10)
    for window in ("7d", "28d"):
        journal.record_performance(
            "dec-1", PerformanceSnapshot(window=window, views=500, ctr=5.0)
        )

    report = pending_metrics(journal, now=NOW)
    assert report.needs_attention is False
    assert report.measured == 1
    mensaje = report.message()
    assert "al día" in mensaje
    assert "youber-journal" not in mensaje


def test_mensaje_lista_pendientes_y_receta(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    for index in range(12):
        _published(
            journal,
            f"dec-{index}",
            topic=f"Vídeo {index}",
            video_id=f"vid{index}",
            days_ago=5 + index,
        )

    report = pending_metrics(journal, now=NOW)
    mensaje = report.message()
    assert "Toca pegar el CSV" in mensaje
    # Se listan los más antiguos (dec-11 tiene 16 días, dec-0 solo 5).
    assert "dec-11" in mensaje
    assert "dec-0" not in mensaje
    assert "faltan: 7d, 28d" in mensaje
    assert "y 2 más" in mensaje  # MAX_LISTED = 10
    assert "youber-journal import <csv> --window 7d" in mensaje
    assert report.as_text() == mensaje


def test_notify_telegram_sin_configuracion(monkeypatch) -> None:
    import dotenv

    # Neutraliza el `.env` del proyecto: en el runner real sí se carga.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify_telegram("hola") is False


def test_notify_telegram_envia_y_falla_con_gracia(monkeypatch) -> None:
    import youber.journal.reminders as reminders

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    class FakeResponse:
        def __init__(self, status_code: int, text: str = "ok") -> None:
            self.status_code = status_code
            self.text = text

    calls: list[dict] = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return FakeResponse(200)

    monkeypatch.setattr(reminders.httpx, "post", fake_post)
    assert notify_telegram("recordatorio") is True
    assert "token" in calls[0]["url"]
    assert calls[0]["json"]["chat_id"] == "123"
    assert calls[0]["json"]["text"] == "recordatorio"

    monkeypatch.setattr(reminders.httpx, "post", lambda *a, **k: FakeResponse(403, "nope"))
    assert notify_telegram("recordatorio") is False

    def boom(*_args, **_kwargs):
        raise RuntimeError("sin red")

    monkeypatch.setattr(reminders.httpx, "post", boom)
    assert notify_telegram("recordatorio") is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(monkeypatch, db: Path, argv: list[str], *, global_flags: list[str] | None = None) -> None:
    monkeypatch.setattr(
        sys, "argv", ["youber-journal", "--db", str(db), *(global_flags or []), *argv]
    )
    journal_main()


def test_cli_pending(monkeypatch, tmp_path: Path, capsys) -> None:
    db = tmp_path / "cli.db"
    journal = DecisionJournal(db)
    _published(journal, "dec-1", topic="La noche", days_ago=10)

    _cli(monkeypatch, db, ["pending"])
    out = capsys.readouterr().out
    assert "Toca pegar el CSV" in out and "dec-1" in out

    _cli(monkeypatch, db, ["pending"], global_flags=["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["pending"][0]["decision_id"] == "dec-1"
    assert payload["windows"] == ["7d", "28d"]


def test_cli_pending_al_dia_y_min_age(monkeypatch, tmp_path: Path, capsys) -> None:
    db = tmp_path / "cli.db"
    journal = DecisionJournal(db)
    _published(journal, "dec-1", video_id="abc", days_ago=1)

    # ``--now`` fija la fecha de referencia: sin él el informe mira el reloj real
    # y el vídeo "de ayer" envejece con los días (el test se caía solo).
    reference = ["--now", NOW.isoformat()]
    _cli(monkeypatch, db, ["pending", *reference])
    assert "al día" in capsys.readouterr().out

    _cli(
        monkeypatch,
        db,
        ["pending", "--min-age-days", "0", "--windows", "48h", *reference],
    )
    out = capsys.readouterr().out
    assert "Toca pegar el CSV" in out and "48h" in out


def test_cli_pending_now_permite_simular(monkeypatch, tmp_path: Path, capsys) -> None:
    """Con ``--now`` el informe es reproducible (misma foto siempre)."""
    db = tmp_path / "cli.db"
    journal = DecisionJournal(db)
    _published(journal, "dec-1", video_id="abc", days_ago=1)

    _cli(monkeypatch, db, ["pending", "--now", "2026-09-20T12:00"], global_flags=["--json"])
    payload = json.loads(capsys.readouterr().out)
    # Publicado el 14/09 (NOW − 1 d) y mirado el 20/09: 6 días, por encima de la
    # antigüedad mínima por defecto (3 d), así que toca medirlo.
    assert payload["pending"][0]["age_days"] == 6.0
