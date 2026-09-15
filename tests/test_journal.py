"""Tests del registro de decisiones (*decision journal*) — offline.

Cubren modelos, almacén SQLite, fachada, constructores desde el workflow,
dataset/análisis estadístico, importación de CSV de YouTube Studio y la CLI.
Sin red, sin FFmpeg y sin tocar el journal real del usuario
(``YOUBER_JOURNAL_DB`` se aísla en ``conftest.py``).
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from youber.journal import (
    DecisionJournal,
    DecisionRecord,
    PerformanceSnapshot,
    TrackCandidate,
    TrackDecision,
    default_journal_path,
    import_analytics_csv,
    read_analytics_csv,
    record_from_lyrics_run,
    record_from_workflow_run,
    video_id_from_url,
)
from youber.journal.analytics import (
    build_report,
    compare_groups,
    dataset_rows,
    feature_correlations,
    pearson,
    rows_to_csv,
    summarize,
)
from youber.journal.cli import main as journal_main
from youber.journal.importers import (
    detect_columns,
    normalize_title,
    parse_duration,
    parse_number,
)
from youber.journal.models import ContentAttributes, VideoArtifact
from youber.music.models import Mood, Track
from youber.music.selector import TrackMatch, theme_profile
from youber.research.data_models import ChannelData, VideoData

SAD_TEXT = (
    "La noche cae y el dolor no se va, lágrimas en la soledad, "
    "todo está perdido, adiós, la tristeza me acompaña."
)
SAD_HIT = TrackMatch(
    track_id="sad",
    title="Adiós",
    artist="Youber",
    score=5.66,
    matched_themes=["tristeza"],
    reason="letra comparte tema tristeza (0.90)",
)


def _track(track_id: str = "sad", **kwargs: object) -> Track:
    """Pista de catálogo para los tests (sin audio real)."""
    defaults: dict[str, object] = {
        "id": track_id,
        "file_path": Path("music") / f"{track_id}.mp3",
        "title": kwargs.pop("title", "Adiós"),
        "duration": 120.0,
        "file_hash": f"hash-{track_id}",
        "lyrical_themes": {"tristeza": 0.9},
        "lyrical_sentiment": "negative",
    }
    defaults.update(kwargs)
    return Track(**defaults)  # type: ignore[arg-type]


def _channel() -> ChannelData:
    """Canal sintético con metadatos tristes."""
    return ChannelData(
        name="Canal Triste",
        url="https://www.youtube.com/@triste",
        handle="triste",
        subscribers="1 K",
        videos=[
            VideoData(
                title="La soledad de la noche",
                url="https://www.youtube.com/watch?v=1",
                video_id="t1",
                views="1 K",
                channel_name="Canal Triste",
                channel_url="https://www.youtube.com/@triste",
                description="Un vídeo sobre la tristeza y el adiós.",
                hashtags=["tristeza"],
            )
        ],
    )


def _insights() -> dict[str, object]:
    """Insights mínimos, con la forma de ``channel_overview``."""
    return {
        "channel": {"name": "Canal Triste"},
        "videos_count": 1,
        "top_hashtags": [{"hashtag": "tristeza", "count": 1}],
        "title_patterns": {"with_question": 1},
        "duration_stats": {"avg_seconds": 60.0},
        "views_summary": {"avg": 1000.0},
    }


def _record(decision_id: str = "dec-000000000001", **kwargs: object) -> DecisionRecord:
    """Decisión de ejemplo con la canción triste elegida."""
    defaults: dict[str, object] = {
        "id": decision_id,
        "topic": "La noche",
        "source_channel": "Canal Triste",
        "attributes": ContentAttributes(
            topic="La noche",
            themes={"tristeza": 0.9},
            dominant_theme="tristeza",
            sentiment="negative",
            videos_analyzed=1,
            target_duration=30.0,
        ),
        "track": TrackDecision(
            chosen_id="sad",
            chosen_title="Adiós",
            score=5.66,
            reason="letra comparte tema tristeza (0.90)",
            matched_themes=["tristeza"],
            theme_score=2.43,
            sentiment_match=True,
            catalog_size=2,
            candidates=[
                TrackCandidate(rank=1, track_id="sad", title="Adiós", score=5.66),
                TrackCandidate(rank=2, track_id="happy", title="Alegría", score=0.0),
            ],
        ),
        "video": VideoArtifact(path="out/final.mp4", duration_seconds=9.4, clip_count=3),
    }
    defaults.update(kwargs)
    return DecisionRecord(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


def test_performance_snapshot_derivadas() -> None:
    snapshot = PerformanceSnapshot(
        window="7D",
        views=100,
        impressions=1000,
        ctr=4.5,
        avg_view_percentage=42.0,
        likes=8,
        comments=3,
        shares=2,
        subscribers_gained=10,
        subscribers_lost=4,
    )
    assert snapshot.window == "7d"  # normalizada
    assert snapshot.retention == 42.0
    assert snapshot.engagement == 13
    assert snapshot.engagement_rate == 13.0
    assert snapshot.net_subscribers == 6


def test_performance_snapshot_sin_datos() -> None:
    snapshot = PerformanceSnapshot()
    assert snapshot.engagement is None
    assert snapshot.engagement_rate is None
    assert snapshot.net_subscribers is None


def test_performance_snapshot_valida_rangos_y_ventana() -> None:
    with pytest.raises(ValidationError):
        PerformanceSnapshot(ctr=120.0)
    with pytest.raises(ValidationError):
        PerformanceSnapshot(window="7 d")
    with pytest.raises(ValidationError):
        PerformanceSnapshot(avg_view_percentage=-1.0)


def test_track_decision_margin() -> None:
    decision = _record().track
    assert decision.margin == 5.66
    solo = TrackDecision(chosen_id="sad", candidates=[TrackCandidate(track_id="sad", title="A")])
    assert solo.margin is None
    assert TrackDecision().margin is None


def test_decision_record_video_id() -> None:
    assert _record().video_id is None
    record = _record(run_id="run-1")
    assert record.video_id is None and record.run_id == "run-1"
    assert record.model_dump_json()


# ---------------------------------------------------------------------------
# Almacén y fachada
# ---------------------------------------------------------------------------


def test_storage_roundtrip(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    record = _record()
    journal.record(record)

    loaded = journal.get(record.id)
    assert loaded is not None
    assert loaded.topic == "La noche"
    assert loaded.track.chosen_id == "sad"
    assert loaded.track.margin == 5.66
    assert loaded.video.clip_count == 3
    assert journal.count() == 1
    assert journal.get("no-existe") is None


def test_storage_listado_y_filtros(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    journal.record(_record("dec-1", topic="uno", source_channel="A"))
    journal.record(_record("dec-2", topic="dos", source_channel="B"))
    journal.record(_record("dec-3", topic="tres", source_channel="A"))

    assert len(journal.list_decisions()) == 3
    assert len(journal.list_decisions(limit=2)) == 2
    assert [r.topic for r in journal.list_decisions(source_channel="A")] == ["tres", "uno"]
    assert [r.id for r in journal.list_natural()] == ["dec-1", "dec-2", "dec-3"]


def test_storage_borrado(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    journal.record(_record("dec-1"))
    journal.record_performance("dec-1", PerformanceSnapshot(window="7d", views=10))

    assert journal.remove("dec-1") is True
    assert journal.remove("dec-1") is False
    assert journal.count() == 0
    assert journal.performance("dec-1") == []


def test_attach_upload_y_busqueda_por_video(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    record = journal.record(_record("dec-1"))

    attached = journal.attach_upload(
        record.id, video_id="abc123", url="https://youtu.be/abc123", privacy="public"
    )
    assert attached.video_id == "abc123"
    assert journal.find_by_video("abc123") is not None
    assert journal.get("abc123") is not None  # acepta también el id de vídeo

    with pytest.raises(KeyError):
        journal.attach_upload("nope", video_id="x")


def test_performance_por_id_o_video_y_upsert(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    journal.record(_record("dec-1"))
    journal.attach_upload("dec-1", video_id="abc123")

    journal.record_performance("abc123", PerformanceSnapshot(window="7d", views=100))
    journal.record_performance(
        "dec-1",
        PerformanceSnapshot(
            window="7d", views=250, ctr=4.0, captured_at=datetime(2026, 9, 15, 10, 0)
        ),
    )
    assert len(journal.performance("dec-1", window="7d")) == 2
    latest = journal.latest_performance("dec-1")
    assert latest is not None and latest.views == 250

    with pytest.raises(KeyError):
        journal.record_performance("nope", PerformanceSnapshot())


def test_stats_y_exportacion(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    journal.record(_record("dec-1"))
    journal.attach_upload("dec-1", video_id="abc123")
    journal.record_performance("dec-1", PerformanceSnapshot(window="7d", views=100, ctr=5.0))

    stats = journal.stats()
    assert stats["decisions"] == 1
    assert stats["with_performance"] == 1
    assert stats["uploaded"] == 1

    json_path = journal.export(tmp_path / "journal.json")
    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["id"] == "dec-1"
    jsonl_path = journal.export(tmp_path / "journal.jsonl")
    assert json.loads(jsonl_path.read_text(encoding="utf-8").strip())["id"] == "dec-1"
    csv_path = journal.export(tmp_path / "dataset.csv")
    assert csv_path.read_text(encoding="utf-8-sig").startswith("decision_id")
    with pytest.raises(ValueError):
        journal.export(tmp_path / "x.xml")

    assert journal.list_natural()[0].id == "dec-1"


def test_default_journal_path_respeta_entorno(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YOUBER_JOURNAL_DB", str(tmp_path / "custom.db"))
    assert default_journal_path() == tmp_path / "custom.db"
    monkeypatch.delenv("YOUBER_JOURNAL_DB")
    assert default_journal_path().name == "journal.db"


# ---------------------------------------------------------------------------
# Constructores desde el workflow
# ---------------------------------------------------------------------------


def test_video_id_from_url() -> None:
    assert video_id_from_url("https://youtu.be/abc123def45") == "abc123def45"
    assert video_id_from_url("https://www.youtube.com/watch?v=XYZ123") == "XYZ123"
    assert video_id_from_url("https://www.youtube.com/shorts/abcDEF12345") == "abcDEF12345"
    assert video_id_from_url("https://example.com/nada") is None
    assert video_id_from_url(None) is None


def test_record_from_lyrics_run_guarda_senales() -> None:
    profile = theme_profile(SAD_TEXT)
    track = _track(favorite=True, usage_count=2)
    record = record_from_lyrics_run(
        topic="La noche",
        channel=_channel(),
        insights=_insights(),
        profile=profile,
        match=SAD_HIT,
        candidates=[SAD_HIT, TrackMatch(track_id="happy", title="Alegría", score=0.1)],
        chosen_track=track,
        catalog_size=2,
        prompt="PROMPT",
        keywords=["tristeza"],
        target_duration=30.0,
        scenes=5,
        music_mood=Mood.SAD,
        artifacts={"brief": "brief.json"},
        video_path=None,
        clip_count=3,
        clip_source="pexels",
        metadata_text="La soledad de la noche tristeza",
    )

    assert record.track.chosen_id == "sad"
    assert record.track.sentiment_match is True
    assert record.track.theme_score > 0
    assert record.track.favorite is True
    assert record.track.usage_count == 2
    assert record.track.margin == 5.56
    assert record.attributes.dominant_theme == "tristeza"
    assert record.attributes.hashtags == ["tristeza"]
    assert record.attributes.metadata_words == 6
    assert record.video.clip_source == "pexels"
    assert record.video.music_mood == Mood.SAD.value
    assert record.artifacts["brief"] == "brief.json"


def test_record_from_lyrics_run_sin_cancion() -> None:
    record = record_from_lyrics_run(
        topic="Sin catálogo",
        channel=_channel(),
        insights=_insights(),
        profile=theme_profile(SAD_TEXT),
        match=None,
        candidates=[],
    )
    assert record.track.chosen_id is None
    assert record.track.candidates == []
    # Sin canción elegida, las features de matching no aplican.
    features = dataset_rows([_row_from(record)])[0]
    assert features["chosen_score"] is None
    assert features["sentiment_match"] == 0


def _row_from(record: DecisionRecord):
    """Construye la fila de dataset de una decisión suelta (sin métricas)."""
    from youber.journal.analytics import build_dataset

    class _FakeJournal:
        def list_natural(self) -> list[DecisionRecord]:
            return [record]

        def latest_performance(self, *_args: object, **_kwargs: object):
            return None

    return build_dataset(_FakeJournal(), window=None)[0]  # type: ignore[arg-type]


def test_record_from_workflow_run(tmp_path: Path) -> None:
    video = tmp_path / "final.mp4"
    video.write_bytes(b"x" * 2048)
    record = record_from_workflow_run(
        channel=_channel(),
        insights=_insights(),
        track=_track(),
        target_duration=30.0,
        artifacts={"json": "a.json"},
        video_path=video,
        video_duration=12.5,
        upload_url="https://youtu.be/abc123def45",
        upload_title="Mi vídeo",
        privacy="private",
        metadata_text="texto",
    )
    assert record.topic == "Mi vídeo"
    assert record.video_id == "abc123def45"
    assert record.video.size_bytes == 2048
    assert record.video.duration_seconds == 12.5
    assert record.track.chosen_id == "sad"
    assert record.track.forced is True


# ---------------------------------------------------------------------------
# Dataset y análisis
# ---------------------------------------------------------------------------


def test_pearson() -> None:
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert pearson([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert pearson([1], [1]) is None
    assert pearson([1, 1, 1], [1, 2, 3]) is None
    assert pearson([1, 2, 3], [1, 2]) is None


def _dataset(views: list[int], retention: list[float]) -> list:
    """Dataset sintético: una decisión por vídeo, con CTR/retención dadas."""
    from youber.journal.analytics import build_dataset

    class _FakeJournal:
        def __init__(self) -> None:
            self.records: list[DecisionRecord] = []
            self.snapshots: dict[str, PerformanceSnapshot] = {}

        def list_natural(self) -> list[DecisionRecord]:
            return self.records

        def latest_performance(self, decision_id: str, window: str | None = None):
            return self.snapshots.get(decision_id)

    fake = _FakeJournal()
    for index, (n_views, n_retention) in enumerate(zip(views, retention, strict=True)):
        record = _record(f"dec-{index}")
        record.track.theme_score = float(index + 1)
        fake.records.append(record)
        fake.snapshots[record.id] = PerformanceSnapshot(
            window="7d", views=n_views, ctr=n_retention
        )
    return build_dataset(fake, window="7d")  # type: ignore[arg-type]


def test_dataset_y_correlaciones() -> None:
    rows = _dataset([100, 200, 300, 400], [1.0, 2.0, 3.0, 4.0])
    assert len(rows) == 4
    assert rows[0].outcomes["views"] == 100.0
    assert rows[0].features["theme_score"] == 1.0

    correlations = feature_correlations(rows, "ctr", min_n=3)
    assert correlations
    theme = next(item for item in correlations if item.feature == "theme_score")
    assert theme.r == 1.0
    assert theme.n == 4
    assert theme.direction == "positiva"

    # Con pocos pares no se calcula nada.
    assert feature_correlations(rows[:2], "ctr", min_n=3) == []


def test_dataset_sin_metricas() -> None:
    rows = _dataset([100, 200, 300], [1.0, 2.0, 3.0])
    for row in rows:
        row.outcomes = {}
    assert feature_correlations(rows, "ctr", min_n=3) == []
    assert summarize(rows).measured == 0


def test_compare_groups_y_summarize() -> None:
    rows = _dataset([100, 200, 300, 400], [1.0, 2.0, 3.0, 4.0])
    for index, row in enumerate(rows):
        row.dominant_theme = "tristeza" if index < 2 else "calma"
    groups = compare_groups(rows, "dominant_theme", "ctr", min_n=2)
    assert [group.group for group in groups] == ["calma", "tristeza"]
    assert groups[0].mean == 3.5

    summary = summarize(rows)
    assert summary.decisions == 4
    assert summary.measured == 4
    assert summary.metrics["ctr"] == 4
    assert summary.themes == {"tristeza": 2, "calma": 2}
    assert summary.windows == {"7d": 4}


def test_build_report_con_y_sin_datos() -> None:
    rows = _dataset([100, 200, 300, 400], [1.0, 2.0, 3.0, 4.0])
    report = build_report(rows, metric="ctr", min_n=3)
    assert "# Informe del registro de decisiones" in report
    assert "## Qué correlaciona con ctr de impresiones (%)" in report
    assert "Afinidad temática" in report
    assert "Causalidad" in report or "causalidad" in report

    vacio = build_report(_dataset([1], [1.0]), metric="ctr", min_n=3)
    assert "Sin datos suficientes" in vacio


def test_dataset_rows_y_csv() -> None:
    rows = _dataset([100, 200, 300], [1.0, 2.0, 3.0])
    flat = dataset_rows(rows)
    assert flat[0]["decision_id"] == "dec-0"
    assert flat[0]["views"] == 100.0
    assert flat[0]["theme_score"] == 1.0
    csv_text = rows_to_csv(flat)
    assert csv_text.startswith("\ufeffdecision_id")
    assert rows_to_csv([]).startswith("\ufeffdecision_id")


# ---------------------------------------------------------------------------
# Importación de CSV de YouTube Studio
# ---------------------------------------------------------------------------


def test_parse_number_y_duracion() -> None:
    assert parse_number("1.234") == 1234.0
    assert parse_number("4,5 %") == 4.5
    assert parse_number("1.234,5") == 1234.5
    assert parse_number("") is None
    assert parse_number("—") is None
    assert parse_number(12) == 12.0
    assert parse_duration("12:34") == 754.0
    assert parse_duration("1:02:03") == 3723.0
    assert parse_duration("0:45") == 45.0
    assert parse_duration("") is None
    assert parse_duration("754") == 754.0


def test_detect_columns_es_y_en() -> None:
    es = detect_columns(
        [
            "ID del vídeo",
            "Título del vídeo",
            "Impresiones",
            "CTR de las impresiones (%)",
            "Visualizaciones",
            "Tiempo de visualización (horas)",
            "Duración media de la visualización",
            "Porcentaje medio visto (%)",
        ]
    )
    assert es["video_id"] == "ID del vídeo"
    assert es["title"] == "Título del vídeo"
    assert es["ctr"] == "CTR de las impresiones (%)"
    assert es["watch_time_minutes"] == "Tiempo de visualización (horas)"
    assert es["avg_view_percentage"] == "Porcentaje medio visto (%)"

    en = detect_columns(["Video ID", "Video title", "Views", "Impressions", "Likes"])
    assert en["video_id"] == "Video ID"
    assert en["views"] == "Views"
    assert en["likes"] == "Likes"


def test_normalize_title() -> None:
    assert normalize_title("Adiós, ¿Noche?") == normalize_title("adios noche")
    assert normalize_title(None) == ""


def _write_studio_csv(path: Path) -> None:
    """CSV de Studio en español (con comas decimales y horas)."""
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
            "abc123",
            "La noche",
            "1.000",
            "4,5",
            "250",
            "3,5",
            "1:12",
            "38,5",
            "45",
            "12",
            "3",
            "7",
            "2",
        ],
        ["zzz999", "Otro vídeo ajeno", "50", "2", "5", "0,1", "0:30", "20", "1", "0", "0", "0", "0"],
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle, delimiter=";").writerows(rows)


def test_read_analytics_csv(tmp_path: Path) -> None:
    path = tmp_path / "studio.csv"
    _write_studio_csv(path)
    table = read_analytics_csv(path)

    assert table.columns["video_id"] == "ID del vídeo"
    assert len(table.rows) == 2
    row = table.rows[0]
    assert row.video_id == "abc123"
    assert row.metrics["impressions"] == 1000.0
    assert row.metrics["ctr"] == 4.5
    assert row.metrics["watch_time_minutes"] == 210.0  # horas → minutos
    assert row.metrics["avg_view_duration_seconds"] == 72.0
    assert row.metrics["subscribers_lost"] == 2.0
    assert row.raw["ID del vídeo"] == "abc123"


def test_read_analytics_csv_sin_cabecera_valida(tmp_path: Path) -> None:
    path = tmp_path / "raro.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_analytics_csv(path)
    with pytest.raises(ValueError):
        read_analytics_csv(__import__("io").StringIO(""))


def test_import_analytics_csv(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    journal.record(_record("dec-1", topic="La noche"))
    journal.attach_upload("dec-1", video_id="abc123", title="La noche")

    path = tmp_path / "studio.csv"
    _write_studio_csv(path)
    result, pending = import_analytics_csv(journal.list_natural(), path, window="28d")

    assert result.parsed == 2
    assert result.applied == 1
    assert result.matched[0].matched_by == "video_id"
    assert result.matched[0].metrics["ctr"] == 4.5
    assert len(result.unmatched) == 1
    assert result.unmatched[0].video_id == "zzz999"

    for decision_id, snapshot in pending:
        journal.storage.add_performance(decision_id, snapshot)
    latest = journal.latest_performance("dec-1")
    assert latest is not None
    assert latest.window == "28d"
    assert latest.views == 250
    assert latest.retention == 38.5


def test_import_analytics_csv_por_titulo_y_dry_run(tmp_path: Path) -> None:
    journal = DecisionJournal(tmp_path / "j.db")
    journal.record(_record("dec-1", topic="La noche"))

    path = tmp_path / "studio.csv"
    _write_studio_csv(path)
    result, pending = import_analytics_csv(journal.list_natural(), path, dry_run=True)
    assert pending == []
    assert result.applied == 0
    assert result.matched[0].matched_by == "title"
    assert journal.performance("dec-1") == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(
    monkeypatch, db: Path, argv: list[str], *, global_flags: list[str] | None = None
) -> None:
    """Ejecuta ``youber-journal`` con argumentos y base de datos de test."""
    monkeypatch.setattr(
        sys, "argv", ["youber-journal", "--db", str(db), *(global_flags or []), *argv]
    )
    journal_main()


def test_cli_list_show_y_stats(monkeypatch, tmp_path: Path, capsys) -> None:
    db = tmp_path / "cli.db"
    journal = DecisionJournal(db)
    journal.record(_record("dec-1"))
    journal.attach_upload("dec-1", video_id="abc123", url="https://youtu.be/abc123")
    journal.record_performance(
        "dec-1", PerformanceSnapshot(window="7d", views=250, ctr=4.5, avg_view_percentage=38.0)
    )

    _cli(monkeypatch, db, ["list", "-n", "5", "--with-performance"])
    assert "dec-1" in capsys.readouterr().out

    _cli(monkeypatch, db, ["show", "dec-1"])
    out = capsys.readouterr().out
    assert "Adiós" in out and "Candidatas" in out

    _cli(monkeypatch, db, ["show", "abc123"], global_flags=["--json"])
    assert '"chosen_id": "sad"' in capsys.readouterr().out

    _cli(monkeypatch, db, ["stats"])
    assert "Decisiones" in capsys.readouterr().out


def test_cli_show_desconocido_falla(monkeypatch, tmp_path: Path, capsys) -> None:
    db = tmp_path / "cli.db"
    with pytest.raises(SystemExit) as excinfo:
        _cli(monkeypatch, db, ["show", "nope"])
    assert excinfo.value.code == 1
    assert "No hay ninguna decisión" in capsys.readouterr().out


def test_cli_upload_y_performance(monkeypatch, tmp_path: Path, capsys) -> None:
    db = tmp_path / "cli.db"
    DecisionJournal(db).record(_record("dec-1"))

    _cli(
        monkeypatch,
        db,
        ["upload", "dec-1", "--video-id", "abc123", "--url", "https://youtu.be/abc123"],
    )
    assert "abc123" in capsys.readouterr().out

    _cli(
        monkeypatch,
        db,
        [
            "performance",
            "abc123",
            "--window",
            "48h",
            "--views",
            "1250",
            "--ctr",
            "4,7",
            "--avg-view-percentage",
            "39",
            "--subs-gained",
            "12",
            "--subs-lost",
            "2",
            "--raw",
            "nota=prueba",
        ],
    )
    assert "CTR 4.7 %" in capsys.readouterr().out

    journal = DecisionJournal(db)
    snapshot = journal.latest_performance("dec-1")
    assert snapshot is not None
    assert snapshot.window == "48h"
    assert snapshot.views == 1250
    assert snapshot.net_subscribers == 10
    assert snapshot.raw["nota"] == "prueba"

    with pytest.raises(SystemExit):
        _cli(monkeypatch, db, ["performance", "nope", "--views", "1"])


def test_cli_import_dataset_analyze_y_remove(monkeypatch, tmp_path: Path, capsys) -> None:
    db = tmp_path / "cli.db"
    journal = DecisionJournal(db)
    journal.record(_record("dec-1", topic="La noche"))
    journal.attach_upload("dec-1", video_id="abc123", title="La noche")

    path = tmp_path / "studio.csv"
    _write_studio_csv(path)

    _cli(monkeypatch, db, ["import", str(path), "--window", "28d", "--dry-run"])
    assert "dry-run" in capsys.readouterr().out

    _cli(monkeypatch, db, ["import", str(path), "--window", "28d"])
    assert "mediciones guardadas" in capsys.readouterr().out

    _cli(monkeypatch, db, ["dataset"])
    assert "dec-1" in capsys.readouterr().out

    out_csv = tmp_path / "dataset.csv"
    _cli(monkeypatch, db, ["dataset", "-o", str(out_csv), "-f", "csv"])
    assert out_csv.is_file()

    report = tmp_path / "informe.md"
    _cli(monkeypatch, db, ["analyze", "--metric", "ctr", "-o", str(report)])
    assert report.is_file()
    assert "Informe del registro" in report.read_text(encoding="utf-8")
    capsys.readouterr()  # limpia la salida de analyze antes de leer el JSON

    _cli(monkeypatch, db, ["list"], global_flags=["--json"])
    assert json.loads(capsys.readouterr().out)[0]["id"] == "dec-1"

    with pytest.raises(SystemExit):
        _cli(monkeypatch, db, ["remove", "dec-1"])
    assert "confirmar" in capsys.readouterr().out
    _cli(monkeypatch, db, ["remove", "dec-1", "--yes"])
    assert DecisionJournal(db).count() == 0

    with pytest.raises(SystemExit):
        _cli(monkeypatch, db, ["remove", "nope", "--yes"])


def test_cli_stats_json(monkeypatch, tmp_path: Path, capsys) -> None:
    db = tmp_path / "stats.db"
    DecisionJournal(db).record(_record("dec-1"))
    _cli(monkeypatch, db, ["stats"], global_flags=["--json"])
    assert json.loads(capsys.readouterr().out)["decisions"] == 1


def test_cli_list_vacio(monkeypatch, tmp_path: Path, capsys) -> None:
    _cli(monkeypatch, tmp_path / "vacio.db", ["list"])
    assert "vacío" in capsys.readouterr().out


def test_cli_analyze_sin_datos(monkeypatch, tmp_path: Path, capsys) -> None:
    db = tmp_path / "pocos.db"
    DecisionJournal(db).record(_record("dec-1"))
    _cli(monkeypatch, db, ["analyze"])
    assert "datos suficientes" in capsys.readouterr().out
