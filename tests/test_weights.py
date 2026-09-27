"""Tests del bucle de aprendizaje: pesos del selector desde el journal.

Todo offline: datasets sintéticos + un journal en ``tmp_path``. Se comprueba
que el aprendizaje reescala las señales en la dirección correcta, que sin
datos se mantiene el prior y que el selector respeta los pesos recibidos.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from youber.journal.analytics import DatasetRow
from youber.journal.learn import FACTOR_CLAMP, learn_weights, shrinkage, weights_report
from youber.music.models import Mood, Track
from youber.music.selector import score_breakdown, select_tracks
from youber.music.weights import DEFAULT_WEIGHTS, SelectionWeights, default_weights_path


def make_row(index: int, ctr: float | None, **features: float) -> DatasetRow:
    """Fila del dataset con una métrica ``ctr`` y las features indicadas."""
    return DatasetRow(
        decision_id=f"d{index}",
        created_at=datetime(2026, 1, 1),
        features={key: float(value) for key, value in features.items()},
        outcomes={"ctr": ctr},
    )


def make_track(
    track_id: str = "t1",
    *,
    title: str = "Tema",
    themes: dict[str, float] | None = None,
    sentiment: str = "neutral",
    moods: list[Mood] | None = None,
    favorite: bool = False,
    usage: int = 0,
) -> Track:
    return Track(
        id=track_id,
        file_path=Path("music") / f"{track_id}.mp3",
        title=title,
        duration=120.0,
        file_hash=f"hash-{track_id}",
        moods=moods or [],
        favorite=favorite,
        usage_count=usage,
        lyrical_themes=themes or {},
        lyrical_sentiment=sentiment,
    )


# ---------------------------------------------------------------------------
# SelectionWeights
# ---------------------------------------------------------------------------


def test_defaults_igual_al_prior():
    weights = SelectionWeights.defaults()
    assert weights.learned is False
    assert weights.as_dict() == DEFAULT_WEIGHTS
    assert weights.factor("theme") == 1.0
    assert "por defecto" in weights.source_label()


def test_save_load_roundtrip(tmp_path):
    learned = SelectionWeights(
        theme=4.5, sentiment=0.75, samples=9, learned=True, metric="ctr"
    )
    path = learned.save(tmp_path / "w.json")
    back = SelectionWeights.load(path)
    assert back.theme == 4.5
    assert back.sentiment == 0.75
    assert back.learned is True
    assert back.samples == 9
    assert back.source_label() == "aprendidos (9 vídeos, ctr)"


def test_load_sin_fichero_devuelve_prior(tmp_path):
    weights = SelectionWeights.load(tmp_path / "no.json")
    assert weights.learned is False
    assert weights.as_dict() == DEFAULT_WEIGHTS
    assert "sin pesos guardados" in weights.reason


def test_load_fichero_corrupto_no_rompe(tmp_path):
    path = tmp_path / "w.json"
    path.write_text("{esto no es json", encoding="utf-8")
    assert SelectionWeights.load(path).learned is False


def test_clear(tmp_path):
    path = SelectionWeights.defaults().save(tmp_path / "w.json")
    assert SelectionWeights.clear(path) is True
    assert SelectionWeights.clear(path) is False


def test_default_path_respeta_env(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUBER_WEIGHTS", str(tmp_path / "custom.json"))
    assert default_weights_path() == tmp_path / "custom.json"


def test_describe_con_evidencia():
    weights = SelectionWeights(
        theme=4.0,
        signals={
            "theme": {
                "name": "theme",
                "base": 3.0,
                "weight": 4.0,
                "factor": 1.33,
                "r": 0.8,
                "n": 9,
            }
        }
    )
    rows = {row[0]: row for row in weights.describe()}
    assert rows["Afinidad temática"][2] == 4.0
    assert rows["Afinidad temática"][3] == "×1.33"
    assert "r=+0.80 (n=9)" in rows["Afinidad temática"][4]
    assert rows["Estado de ánimo"][4] == "—"


# ---------------------------------------------------------------------------
# Aprendizaje
# ---------------------------------------------------------------------------


def test_shrinkage():
    assert shrinkage(0, min_samples=5) == 0.0
    assert shrinkage(5, min_samples=5) == pytest.approx(0.5)
    assert shrinkage(95, min_samples=5) == pytest.approx(0.95)


def test_factor_for_acotado():
    from youber.journal.learn import factor_for

    # Con la fuerza por defecto el factor vive en [0.5, 1.5]: los topes son red
    # de seguridad para fuerzas altas o correlaciones perfectas.
    assert factor_for(1.0, 1_000, +1.0) == pytest.approx(1.4975, abs=1e-3)
    assert factor_for(1.0, 1_000, +1.0, strength=8.0) == FACTOR_CLAMP[1]
    assert factor_for(-1.0, 1_000, +1.0, strength=8.0) == FACTOR_CLAMP[0]
    # El encogimiento deja el factor cerca de 1 con pocas muestras.
    assert factor_for(1.0, 1, +1.0) == pytest.approx(1 + 0.5 / 6, abs=1e-6)
    # Dirección de penalización: una correlación negativa sube el castigo.
    assert factor_for(-0.6, 20, -1.0) > 1.0


def test_learn_sin_datos_suficientes():
    rows = [make_row(1, 2.0, theme_score=1.0), make_row(2, 3.0, theme_score=2.0)]
    weights = learn_weights(rows)
    assert weights.learned is False
    assert weights.as_dict() == DEFAULT_WEIGHTS
    assert "5" in weights.reason


def test_learn_sin_la_metrica_pedida():
    rows = [make_row(i, ctr=None, theme_score=i) for i in range(6)]
    assert learn_weights(rows, metric="ctr").learned is False


def test_learn_reescala_las_senales():
    rows = [
        make_row(0, 1.0, theme_score=0, usage_count=5, sentiment_match=0),
        make_row(1, 1.1, theme_score=1, usage_count=4, sentiment_match=0),
        make_row(2, 1.2, theme_score=2, usage_count=3, sentiment_match=0),
        make_row(3, 4.0, theme_score=3, usage_count=2, sentiment_match=1),
        make_row(4, 4.2, theme_score=4, usage_count=1, sentiment_match=1),
        make_row(5, 4.4, theme_score=5, usage_count=0, sentiment_match=1),
    ]
    weights = learn_weights(rows)
    assert weights.learned is True
    assert weights.samples == 6
    # Señales que suben con el resultado: pesan más que el prior.
    assert weights.theme > DEFAULT_WEIGHTS["theme"]
    assert weights.sentiment > DEFAULT_WEIGHTS["sentiment"]
    # Señal de castigo con correlación negativa: el castigo sube.
    assert weights.usage > DEFAULT_WEIGHTS["usage"]
    # Señales sin pares suficientes se quedan en el prior.
    assert weights.signals["mood"].factor == 1.0
    assert weights.signals["mood"].r is None
    for name in DEFAULT_WEIGHTS:
        assert FACTOR_CLAMP[0] <= weights.factor(name) <= FACTOR_CLAMP[1]


def test_learn_metric_alternativa():
    rows = [make_row(i, None, theme_score=i) for i in range(6)]
    for index, row in enumerate(rows):
        row.outcomes["retention"] = 10.0 + index
    weights = learn_weights(rows, metric="retention")
    assert weights.learned is True
    assert weights.metric == "retention"


def test_weights_report():
    report = weights_report(SelectionWeights.defaults())
    assert "Pesos del selector" in report
    assert "| Señal |" in report


# ---------------------------------------------------------------------------
# Integración con el selector
# ---------------------------------------------------------------------------


def test_score_breakdown_sigue_igual_sin_pesos():
    track = make_track(
        themes={"calma": 0.5}, sentiment="positive", moods=[Mood.RELAXING]
    )
    breakdown = score_breakdown(
        track,
        themes={"calma": 0.5},
        sentiment="positive",
        mood=Mood.RELAXING,
        keywords=["tema"],
    )
    assert breakdown.theme_score == pytest.approx(3.0 * 0.5 * 0.5)
    assert breakdown.sentiment_score == 1.5
    assert breakdown.mood_score == 2.0
    assert breakdown.total == pytest.approx(
        breakdown.theme_score + 1.5 + 2.0 + breakdown.keyword_score
    )


def test_selector_respeta_los_pesos():
    track = make_track(themes={"tristeza": 1.0}, sentiment="negative")
    default = score_breakdown(track, themes={"tristeza": 1.0}, sentiment="negative")
    boosted = score_breakdown(
        track,
        themes={"tristeza": 1.0},
        sentiment="negative",
        weights=SelectionWeights(theme=6.0, sentiment=3.0),
    )
    assert default.total == pytest.approx(3.0 + 1.5)
    assert boosted.total == pytest.approx(6.0 + 3.0)


def test_select_tracks_ordena_con_pesos():
    from youber.music.lyrics_analyzer import LyricsAnalysis

    bueno = make_track("bueno", title="Triste", themes={"tristeza": 1.0})
    flojo = make_track(
        "flojo", title="Alegre", themes={"tristeza": 0.05}, favorite=True
    )
    profile = LyricsAnalysis(themes={"tristeza": 1.0}, sentiment="neutral")

    default = select_tracks([bueno, flojo], profile, limit=2)
    assert default[0].track_id == "bueno"

    # Con la "favorita" disparada, el orden cambia: los pesos mandan.
    pesos = SelectionWeights(theme=0.1, favorite=50.0)
    reordenado = select_tracks([bueno, flojo], profile, limit=2, weights=pesos)
    assert reordenado[0].track_id == "flojo"


# ---------------------------------------------------------------------------
# CLI youber-journal
# ---------------------------------------------------------------------------


def test_cli_parser_learn_y_weights():
    from youber.journal.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["learn", "--metric", "views", "--min-samples", "8"])
    assert args.command == "learn"
    assert args.metric == "views"
    assert args.min_samples == 8

    args = parser.parse_args(["weights", "--clear"])
    assert args.command == "weights"
    assert args.clear is True


def test_cli_learn_sin_datos(tmp_path, monkeypatch):
    from youber.journal import DecisionJournal
    from youber.journal.cli import _run_learn, build_parser

    weights_file = tmp_path / "w.json"
    monkeypatch.setenv("YOUBER_WEIGHTS", str(weights_file))
    journal = DecisionJournal(tmp_path / "j.db")
    try:
        assert _run_learn(journal, build_parser().parse_args(["learn"])) == 0
    finally:
        journal.close()
    assert not weights_file.exists()


def test_cli_learn_con_datos_guarda(tmp_path, monkeypatch):
    from youber.journal import DecisionJournal
    from youber.journal.cli import _run_learn, build_parser

    weights_file = tmp_path / "w.json"
    monkeypatch.setenv("YOUBER_WEIGHTS", str(weights_file))
    journal = DecisionJournal(tmp_path / "j.db")
    try:
        for index in range(6):
            record = _record_with_metrics(index)
            journal.record(record)
            journal.record_performance(record.id, _snapshot(ctr=1.0 + index))
    finally:
        journal.close()

    journal = DecisionJournal(tmp_path / "j.db")
    try:
        args = build_parser().parse_args(["learn", "--report", str(tmp_path / "r.md")])
        assert _run_learn(journal, args) == 0
    finally:
        journal.close()

    loaded = SelectionWeights.load(weights_file)
    assert loaded.learned is True
    assert loaded.samples == 6
    assert (tmp_path / "r.md").is_file()


def test_cli_weights_show_y_clear(tmp_path):
    from youber.journal import DecisionJournal
    from youber.journal.cli import _run_weights, build_parser

    file = tmp_path / "w.json"
    SelectionWeights(learned=True, samples=7, theme=5.0).save(file)
    journal = DecisionJournal(tmp_path / "j.db")
    try:
        assert _run_weights(journal, build_parser().parse_args(["weights", "--file", str(file)])) == 0
        args = build_parser().parse_args(["weights", "--file", str(file), "--clear"])
        assert _run_weights(journal, args) == 0
    finally:
        journal.close()
    assert not file.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_with_metrics(index: int):
    from youber.journal import ContentAttributes, DecisionRecord, TrackDecision

    record = DecisionRecord(
        id=f"d{index}",
        topic=f"Tema {index}",
        attributes=ContentAttributes(
            themes={"tristeza": 1.0}, dominant_theme="tristeza"
        ),
    )
    record.track = TrackDecision(
        chosen_id=f"t{index}",
        score=float(index),
        theme_score=float(index),
        sentiment_match=bool(index % 2),
        keyword_hits=index,
        usage_count=index,
        favorite=bool(index % 3 == 0),
    )
    return record


def _snapshot(ctr: float):
    from youber.journal import PerformanceSnapshot

    return PerformanceSnapshot(window="7d", ctr=ctr, views=int(ctr * 100))
