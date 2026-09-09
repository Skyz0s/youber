"""Tests del módulo youber.sync: timestamps, alineación, letras y CLI.

Estrategia: parsers/serializers y alineación pura se prueban offline.
La transcripción Whisper se mockea o se verifica el error claro cuando el
backend no está instalado. Los tests que necesitan FFmpeg real (probe de
duración) viven en tests/test_sync_render.py con skipif.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from youber.sync.aligner import (
    LyricsAligner,
    Segment,
    align_lines_to_segments,
    rough_align,
    transcribe_segments,
)
from youber.sync.lyrics import LyricsExtractor
from youber.sync.timestamps import (
    LyricsDocument,
    SyncError,
    SyncLine,
    format_lrc_time,
    format_srt_time,
    parse_document,
    parse_lrc,
    parse_lyrics_file,
    parse_srt,
    parse_txt,
    serialize,
    sniff_format,
    to_json,
    to_lrc,
    to_srt,
)

_HAS_WHISPER = bool(
    importlib.util.find_spec("faster_whisper") or importlib.util.find_spec("whisper")
)

LRC_SAMPLE = """\
[ti:Cancion de prueba]
[ar:Artista Test]
[00:01.00]Primera linea
[00:02.50]Segunda linea
"""

SRT_SAMPLE = """\
1
00:00:01,000 --> 00:00:02,500
Primera linea

2
00:00:02,600 --> 00:00:04,000
Segunda linea
"""


# ---------------------------------------------------------------------------
# Tiempos / formatos
# ---------------------------------------------------------------------------


def test_format_lrc_time():
    assert format_lrc_time(0) == "[00:00.00]"
    assert format_lrc_time(61.5) == "[01:01.50]"


def test_format_srt_time():
    assert format_srt_time(3661.789) == "01:01:01,789"
    assert format_srt_time(1.0) == "00:00:01,000"


# ---------------------------------------------------------------------------
# Parser LRC
# ---------------------------------------------------------------------------


def test_parse_lrc_metadatos_y_lineas():
    doc = parse_lrc(LRC_SAMPLE)
    assert doc.title == "Cancion de prueba"
    assert doc.artist == "Artista Test"
    assert doc.timed is True
    assert doc.source == "lrc"
    assert [line.text for line in doc.lines] == ["Primera linea", "Segunda linea"]
    assert doc.lines[0].start == pytest.approx(1.0)
    assert doc.lines[1].start == pytest.approx(2.5)
    assert doc.lines[0].end is None


def test_parse_lrc_varias_marcas_en_una_linea():
    doc = parse_lrc("[00:01.00][00:05.00]Estribillo")
    assert len(doc.lines) == 2
    assert sorted(line.start for line in doc.lines) == [
        pytest.approx(1.0),
        pytest.approx(5.0),
    ]


def test_parse_lrc_offset():
    doc = parse_lrc("[offset:500]\n[00:01.00]Linea")
    assert doc.lines[0].start == pytest.approx(1.5)


def test_parse_lrc_ignora_lineas_sin_contenido():
    doc = parse_lrc("[00:01.00]\n[00:02.00]Con letra\n")
    assert len(doc.lines) == 1


def test_to_lrc_roundtrip():
    doc = LyricsDocument(
        title="T",
        artist="A",
        lines=[SyncLine(start=1.0, text="Hola"), SyncLine(start=2.5, text="Mundo")],
        timed=True,
    )
    reparsed = parse_lrc(to_lrc(doc))
    assert reparsed.title == "T"
    assert reparsed.artist == "A"
    assert [(line.start, line.text) for line in reparsed.lines] == [
        (pytest.approx(1.0), "Hola"),
        (pytest.approx(2.5), "Mundo"),
    ]


# ---------------------------------------------------------------------------
# Parser SRT
# ---------------------------------------------------------------------------


def test_parse_srt():
    doc = parse_srt(SRT_SAMPLE)
    assert doc.timed is True
    assert doc.source == "srt"
    assert doc.lines[0].start == pytest.approx(1.0)
    assert doc.lines[0].end == pytest.approx(2.5)
    assert doc.lines[1].start == pytest.approx(2.6)


def test_to_srt_calcula_finales_faltantes():
    doc = LyricsDocument(
        lines=[
            SyncLine(start=1.0, text="Uno"),
            SyncLine(start=3.0, text="Dos"),
            SyncLine(start=5.0, text="Tres"),
        ],
        timed=True,
    )
    srt = to_srt(doc)
    reparsed = parse_srt(srt)
    assert len(reparsed.lines) == 3
    # final de la 1 = siguiente - gap
    assert reparsed.lines[0].end == pytest.approx(2.95)
    # final de la última usa duration o start+3
    assert reparsed.lines[2].end == pytest.approx(8.0)


def test_to_srt_sin_duration_ultima_linea():
    doc = LyricsDocument(lines=[SyncLine(start=1.0, text="Unica")], timed=True)
    reparsed = parse_srt(to_srt(doc))
    assert reparsed.lines[0].end == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# TXT / JSON / detección
# ---------------------------------------------------------------------------


def test_parse_txt_no_temporizado():
    doc = parse_txt("Primera\n\nSegunda   \n")
    assert doc.timed is False
    assert doc.source == "txt"
    assert doc.as_plain_lines() == ["Primera", "Segunda"]


def test_json_roundtrip():
    doc = LyricsDocument(
        title="T",
        lines=[SyncLine(start=1.0, end=2.0, text="Hola")],
        timed=True,
        source="lrc",
    )
    reparsed = parse_document(to_json(doc), "json")
    assert reparsed == doc


def test_sniff_format():
    assert sniff_format(LRC_SAMPLE) == "lrc"
    assert sniff_format(SRT_SAMPLE) == "srt"
    assert sniff_format('{"lines": []}') == "json"
    assert sniff_format("solo texto\nsin marcas") == "txt"


def test_parse_lyrics_file_por_sufijo(tmp_path: Path):
    lrc = tmp_path / "a.lrc"
    lrc.write_text(LRC_SAMPLE, encoding="utf-8")
    doc = parse_lyrics_file(lrc)
    assert doc.source == "lrc"
    # Sufijo desconocido -> auto-detección por contenido
    other = tmp_path / "letra.desconocido"
    other.write_text(SRT_SAMPLE, encoding="utf-8")
    assert parse_lyrics_file(other).source == "srt"


def test_parse_lyrics_file_inexistente_raise(tmp_path: Path):
    with pytest.raises(SyncError):
        parse_lyrics_file(tmp_path / "no_existe.lrc")


def test_serialize_formato_desconocido():
    doc = parse_txt("hola")
    with pytest.raises(SyncError):
        serialize(doc, "vtt")


def test_sync_line_negativa_invalida():
    with pytest.raises(ValidationError):
        SyncLine(start=-1.0, text="x")


# ---------------------------------------------------------------------------
# rough_align
# ---------------------------------------------------------------------------


def test_rough_align_estructura_y_limites():
    lines = ["primera linea bastante larga", "corta", "media linea"]
    result = rough_align(lines, 30.0)
    assert len(result) == 3
    assert result[0].start == pytest.approx(0.5)
    for prev, nxt in zip(result, result[1:], strict=False):
        assert nxt.start == pytest.approx(prev.end + 0.25)
    assert result[-1].end == pytest.approx(29.5, abs=0.01)
    assert result[-1].text == "media linea"


def test_rough_align_duracion_corta_reparto_equitativo():
    result = rough_align(["a", "b", "c"], 0.6)
    assert result[0].start == 0.0
    assert result[1].start == pytest.approx(0.2)
    assert result[-1].end == pytest.approx(0.6)


def test_rough_align_vacio():
    assert rough_align([], 30.0) == []
    assert rough_align(["", "  "], 30.0) == []


# ---------------------------------------------------------------------------
# align_lines_to_segments
# ---------------------------------------------------------------------------


def test_align_lines_a_segmento_unico():
    segments = [Segment(start=0.0, end=10.0, text="aaa bbb ccc ddd eee")]
    result = align_lines_to_segments(["aaa bbb", "ccc ddd", "eee"], segments)
    assert len(result) == 3
    assert result[0].start == 0.0
    assert result[0].end == pytest.approx(10.0 * 7 / 17, abs=0.05)
    assert result[1].start == pytest.approx(10.0 * 7 / 17, abs=0.05)
    assert result[2].end == pytest.approx(10.0)


def test_align_lineas_mas_largas_que_transcripcion():
    segments = [Segment(start=0.0, end=2.0, text="hola mundo")]
    result = align_lines_to_segments(
        ["una linea mucho mas larga que toda la transcripcion junta"], segments
    )
    assert result[0].start == 0.0
    assert result[0].end == pytest.approx(2.0)


def test_align_sin_segmentos_raise():
    with pytest.raises(SyncError):
        align_lines_to_segments(["hola"], [])


# ---------------------------------------------------------------------------
# LyricsAligner (probe/whisper mockeados)
# ---------------------------------------------------------------------------


async def _fake_probe(_path) -> float:
    return 30.0


async def test_align_lrc_ya_temporizado_pasa_tal_cual(tmp_path: Path, monkeypatch):
    import youber.sync.aligner as aligner

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"fake")
    lrc = tmp_path / "letra.lrc"
    lrc.write_text(LRC_SAMPLE, encoding="utf-8")

    doc = await LyricsAligner().align(audio, lrc)
    assert doc.timed is True
    assert doc.source == "lrc"
    assert doc.duration == 30.0
    assert doc.lines[0].start == pytest.approx(1.0)


async def test_align_txt_sin_whisper_usa_rough(tmp_path: Path, monkeypatch):
    import youber.sync.aligner as aligner

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"fake")
    txt = tmp_path / "letra.txt"
    txt.write_text("primera\nsegunda\ntercera", encoding="utf-8")

    doc = await LyricsAligner().align(audio, txt)
    assert doc.timed is True
    assert doc.source == "rough"
    assert doc.duration == 30.0
    assert len(doc.lines) == 3
    assert doc.lines[0].start >= 0.5


async def _fake_transcribe(_audio, model_size: str = "small", language=None):
    assert model_size == "base"
    return [
        Segment(start=0.0, end=1.0, text="hola"),
        Segment(start=1.0, end=3.0, text="mundo"),
    ]


async def test_align_whisper_realinea_texto(tmp_path: Path, monkeypatch):
    import youber.sync.aligner as aligner

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    monkeypatch.setattr(aligner, "transcribe_segments", _fake_transcribe)
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"fake")
    txt = tmp_path / "letra.txt"
    txt.write_text("hola\nmundo", encoding="utf-8")

    doc = await LyricsAligner().align(audio, txt, model_size="base")
    assert doc.source == "whisper"
    assert doc.lines[0].start == 0.0
    assert doc.lines[0].end == pytest.approx(1.0)
    assert doc.lines[1].start == pytest.approx(1.0)
    assert doc.lines[1].end == pytest.approx(3.0)


async def test_align_sin_letra_transcribe(tmp_path: Path, monkeypatch):
    import youber.sync.aligner as aligner

    async def fake_any(_audio, model_size="small", language=None):
        return [
            Segment(start=0.0, end=1.0, text="hola"),
            Segment(start=1.0, end=2.0, text="mundo"),
        ]

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    monkeypatch.setattr(aligner, "transcribe_segments", fake_any)
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"fake")

    doc = await LyricsAligner().align(audio)
    assert doc.source == "whisper"
    assert doc.timed is True
    assert [line.text for line in doc.lines] == ["hola", "mundo"]
    assert doc.duration == 30.0


async def test_align_audio_inexistente_raise(tmp_path: Path):
    with pytest.raises(SyncError):
        await LyricsAligner().align(tmp_path / "nope.mp3", None)


@pytest.mark.skipif(_HAS_WHISPER, reason="Whisper instalado: el error no aplica")
async def test_transcribe_sin_backend_da_error_claro(tmp_path: Path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"fake")
    with pytest.raises(SyncError, match="faster-whisper"):
        await transcribe_segments(audio, model_size="tiny")


async def test_transcribe_modelo_desconocido(tmp_path: Path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"fake")
    with pytest.raises(SyncError, match="Modelo Whisper desconocido"):
        await transcribe_segments(audio, model_size="gigante")


# ---------------------------------------------------------------------------
# LyricsExtractor
# ---------------------------------------------------------------------------


async def test_extract_from_file_lrc(tmp_path: Path):
    lrc = tmp_path / "letra.lrc"
    lrc.write_text(LRC_SAMPLE, encoding="utf-8")
    plain = await LyricsExtractor().extract_from_file(lrc)
    assert plain == "Primera linea\nSegunda linea"


async def test_extract_from_file_txt_y_srt(tmp_path: Path):
    txt = tmp_path / "letra.txt"
    txt.write_text("Hola\nMundo", encoding="utf-8")
    assert await LyricsExtractor().extract_from_file(txt) == "Hola\nMundo"

    srt = tmp_path / "letra.srt"
    srt.write_text(SRT_SAMPLE, encoding="utf-8")
    assert await LyricsExtractor().extract_from_file(srt) == (
        "Primera linea\nSegunda linea"
    )


async def test_extract_from_file_inexistente_devuelve_none(tmp_path: Path):
    assert await LyricsExtractor().extract_from_file(tmp_path / "x.lrc") is None


async def test_extract_from_audio_une_segmentos(tmp_path: Path, monkeypatch):
    import youber.sync.lyrics as lyrics

    async def fake_transcribe(_audio, model_size="small", language=None):
        return [Segment(start=0.0, end=1.0, text="hola"), Segment(start=1.0, end=2.0, text="mundo")]

    monkeypatch.setattr(lyrics, "transcribe_segments", fake_transcribe)
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"fake")
    text = await LyricsExtractor().extract_from_audio(audio)
    assert text == "hola\nmundo"


async def test_get_lyrics_sin_provider_devuelve_none(monkeypatch):
    monkeypatch.delenv("YOUBER_LYRICS_PROVIDER", raising=False)
    result = await LyricsExtractor().get_lyrics("Titulo", "Artista")
    assert result is None


# ---------------------------------------------------------------------------
# CLI youber-sync (sin FFmpeg)
# ---------------------------------------------------------------------------


def test_cli_extract_imprime_texto_plano(tmp_path: Path, capsys):
    from youber.sync.cli import main

    lrc = tmp_path / "letra.lrc"
    lrc.write_text(LRC_SAMPLE, encoding="utf-8")
    assert main(["extract", str(lrc)]) == 0
    out = capsys.readouterr().out
    assert "Primera linea" in out
    assert "[00:01.00]" not in out


def test_cli_align_stdout_lrc(tmp_path: Path, monkeypatch, capsys):
    import youber.sync.aligner as aligner
    from youber.sync.cli import main

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"fake")
    txt = tmp_path / "letra.txt"
    txt.write_text("primera\nsegunda", encoding="utf-8")

    assert main(["align", "--audio", str(audio), "--lyrics", str(txt)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("[00:00.")
    assert "primera" in out


async def test_cli_align_track_resuelve_catalogo(tmp_path: Path, monkeypatch):
    import youber.sync.aligner as aligner
    import youber.sync.cli as cli

    class FakeLibrary:
        def __init__(self, library_dir: str | Path):
            self.library_dir = library_dir

        def get(self, track_id: str):
            assert track_id == "abc"
            return SimpleNamespace(
                file_path=tmp_path / "song.mp3", title="Tema", artist="Banda"
            )

        def close(self):
            return None

    monkeypatch.setattr(aligner, "probe_duration", _fake_probe)
    # Evita el constructor real de MusicLibrary (SQLite) usando el fake directo.
    monkeypatch.setattr("youber.music.library.MusicLibrary", FakeLibrary)

    txt = tmp_path / "letra.txt"
    txt.write_text("hola mundo", encoding="utf-8")
    song = tmp_path / "song.mp3"
    song.write_bytes(b"fake")

    out = tmp_path / "salida.lrc"
    code = await cli._cmd_align(
        SimpleNamespace(
            audio=None, track="abc", library=str(tmp_path), lyrics=str(txt),
            whisper=False, model="small", language=None, format="lrc",
            output=str(out), title=None, artist=None,
        )
    )
    assert code == 0
    content = out.read_text(encoding="utf-8")
    assert "[ti:Tema]" in content
    assert "[ar:Banda]" in content


def test_cli_parser_tiene_subcomandos():
    from youber.sync.cli import build_parser

    parser = build_parser()
    for name in ("extract", "align", "burn"):
        assert name in parser._subparsers._group_actions[0].choices


def test_cli_align_sin_entrada_sale_con_error():
    from youber.sync.cli import main

    with pytest.raises(SystemExit):
        main(["align", "--lyrics", "x.txt"])
