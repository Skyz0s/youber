"""Tests del análisis de transcripciones públicas (youber.script.transcripts)."""

from __future__ import annotations

from youber.research.data_models import VideoData
from youber.script.transcripts import (
    TranscriptAnalysis,
    TranscriptSnippet,
    _clean,
    _cta_from_tail,
    _first_words,
    analyze_channel,
    analyze_video,
    extract_keywords,
    fetch_transcript,
    hook_template,
)


def _snippets() -> list[TranscriptSnippet]:
    return [
        TranscriptSnippet(start=0.5, text="Detrás de mí hay 100 policías,"),
        TranscriptSnippet(start=1.7, text="y si nos arrestan ganarán medio millón."),
        TranscriptSnippet(start=5.2, text="¡Vamos a empezar!"),
        TranscriptSnippet(start=10.0, text="Hoy el reto es enorme."),
        TranscriptSnippet(start=1195.0, text="Gracias por ver el vídeo."),
        TranscriptSnippet(start=1200.0, text="Suscríbete y activa la campana."),
        TranscriptSnippet(start=1205.0, text="COMPRA MI LIBRO POR UNA GALLETA"),
    ]


def test_fetch_transcript_sin_libreria(monkeypatch):
    """Si la librería no está, devuelve lista vacía sin reventar."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("youtube_transcript_api"):
            raise ImportError("no instalada")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert fetch_transcript("abc123") == []


def test_first_words():
    words = _first_words(_snippets(), seconds=6.0)
    assert "100 policías" in words
    assert "Vamos a empezar" in words


def test_cta_from_tail():
    ctas = _cta_from_tail(_snippets())
    assert any("Suscríbete" in c for c in ctas)
    assert any("COMPRA MI LIBRO" in c for c in ctas)


def test_clean():
    assert _clean("Hola\n  mundo  ") == "Hola mundo"


def test_analyze_video_sin_transcripcion(monkeypatch):
    monkeypatch.setattr(
        "youber.script.transcripts.fetch_transcript", lambda video_id, **kw: []
    )
    assert analyze_video("xyz") is None


def test_extract_keywords_filtra_stopwords():
    text = "Hola a todos, hoy cocinamos pasta con tomate y cocinamos salsa"
    keywords = extract_keywords(text, top_n=4)
    assert "cocinamos" in keywords  # la más frecuente (x2)
    assert "pasta" in keywords
    assert "tomate" in keywords
    assert "hola" not in keywords  # token corto/stopword
    assert len(keywords) <= 4


def test_extract_keywords_vacio():
    assert extract_keywords("de la que el y los") == []


def test_analyze_video_ok(monkeypatch):
    monkeypatch.setattr(
        "youber.script.transcripts.fetch_transcript",
        lambda video_id, **kw: _snippets(),
    )
    analysis = analyze_video("abc")
    assert analysis is not None
    assert analysis.video_count == 1
    assert analysis.hooks
    assert "100 policías" in analysis.hooks[0]
    assert analysis.ctas
    # keywords reales del contenido (sin stopwords)
    assert analysis.keywords
    assert "policías" in analysis.keywords


def test_analyze_channel(monkeypatch):
    videos = [
        VideoData(
            title=f"Vídeo {i}",
            url=f"https://www.youtube.com/watch?v=vid{i}",
            video_id=f"vid{i}",
            views="10 K de visualizaciones",
            duration="10:00",
            channel_name="Canal",
            channel_url="https://www.youtube.com/@canal",
        )
        for i in range(1, 5)
    ]

    def fake_fetch(video_id, **kw):
        return [
            TranscriptSnippet(start=0.3, text=f"Hook del {video_id}"),
            TranscriptSnippet(start=50.0, text="Suscríbete al canal"),
        ]

    monkeypatch.setattr(
        "youber.script.transcripts.fetch_transcript", fake_fetch
    )
    analysis = analyze_channel(videos, max_videos=3)
    assert analysis.video_count == 3
    assert any("Hook del vid1" in h for h in analysis.hooks)
    assert analysis.ctas
    assert analysis.keywords  # agregadas del contenido real


def test_hook_template_con_transcripcion():
    analysis = TranscriptAnalysis(
        hooks=["Detrás de mí hay 100 policías"], video_count=1
    )
    template = hook_template("Mi reto", analysis)
    assert "100 policías" in template
    assert "Mi reto" in template


def test_hook_template_sin_transcripcion():
    template = hook_template("Mi reto", None)
    assert "Mi reto" in template
