"""Tests del videoclip dirigido por la letra (``youber.musicvideo``).

Todo offline y determinista: léxico local, letras de ejemplo y perfiles de
energía sintéticos. No se toca ni la red ni la GPU.
"""

from __future__ import annotations

import pytest

from youber.music.models import Mood
from youber.musicvideo.director import (
    best_highlight,
    direct_song,
    plan_to_script,
    plan_to_shot_plan,
)
from youber.musicvideo.lexicon import beat_from_line, keywords_from_line, normalize
from youber.musicvideo.models import MusicVideoError, SongSection
from youber.musicvideo.sections import find_highlights, score_section, sections_from_markers
from youber.sync.timestamps import LyricsDocument, SyncLine, parse_txt
from youber.visuals.models import Aspect


def _timed_document() -> LyricsDocument:
    """Letra de prueba con un estribillo que se repite tres veces."""
    return LyricsDocument(
        lines=[
            SyncLine(start=0, text="la noche se abre"),
            SyncLine(start=10, text="camino solo por la ciudad"),
            SyncLine(start=20, text="brilla el mar en tus ojos"),
            SyncLine(start=30, text="brilla el mar en tus ojos"),
            SyncLine(start=40, text="y el tiempo se detiene"),
            SyncLine(start=50, text="brilla el mar en tus ojos"),
        ],
        timed=True,
        source="lrc",
    )


# --- léxico: la línea dirige el plano --------------------------------------


def test_normalize_quita_acentos_y_signos() -> None:
    assert normalize("Caminábamos—rápido, ¡otra vez!") == "caminabamos rapido otra vez"


def test_beat_from_line_toma_sujeto_accion_y_lugar() -> None:
    beat = beat_from_line("quiero caminar contigo hasta el mar")
    assert "walking" in beat.action
    assert "sea" in beat.subject
    assert "sea" in beat.setting
    assert beat.camera


def test_beat_from_line_cae_al_animo_si_no_reconoce_nada() -> None:
    beat = beat_from_line("tu tu tu ru tu", mood=Mood.SAD)
    assert beat.subject
    assert "blue" in beat.light or "dark" in beat.light or "shadow" in beat.light


def test_beat_from_line_cambia_la_camara_por_tramo() -> None:
    verse = beat_from_line("brilla el mar", section=SongSection.VERSE)
    chorus = beat_from_line("brilla el mar", section=SongSection.CHORUS)
    assert verse.camera != chorus.camera


def test_keywords_from_line_saca_terminos_en_ingles() -> None:
    terms = keywords_from_line("brilla el mar en tus ojos")
    assert any("sea" in term for term in terms)


def test_lexicon_entiende_lineas_en_ingles() -> None:
    beat = beat_from_line("I keep walking through the rain at night")
    assert "walking" in beat.action
    assert "rain" in beat.light


def test_beat_from_line_varia_al_fallar_el_lexico() -> None:
    first = beat_from_line("la la la", index=0, mood=Mood.SAD)
    second = beat_from_line("la la la", index=1, mood=Mood.SAD)
    assert first.subject != second.subject


# --- tramos: el estribillo se repite ---------------------------------------


def test_detect_sections_marca_el_estribillo_por_repeticion() -> None:
    plan = direct_song(_timed_document(), title="Brilla", infer_profile=False)
    chorus = [section for section in plan.sections if section.kind == SongSection.CHORUS]
    assert chorus, "debería detectar al menos un estribillo"
    assert max(section.repetition for section in chorus) == 3
    assert plan.sections[0].kind == SongSection.INTRO


def test_score_section_premia_repeticion() -> None:
    plan = direct_song(_timed_document(), infer_profile=False)
    chorus = next(s for s in plan.sections if s.kind == SongSection.CHORUS)
    verse = next(s for s in plan.sections if s.kind == SongSection.VERSE)
    assert score_section(chorus) > score_section(verse)


# --- mejores momentos -------------------------------------------------------


def test_find_highlights_elige_el_estribillo() -> None:
    plan = direct_song(_timed_document(), infer_profile=False)
    highlight = best_highlight(plan)
    assert highlight is not None
    assert highlight.section == SongSection.CHORUS
    assert 20.0 <= highlight.duration <= 60.0


def test_find_highlights_sin_tramos_devuelve_vacio() -> None:
    assert find_highlights([]) == []


# --- estructura del fichero de letra (marcas de seccion) -------------------

_MARKED_TEXT = (
    "[Verse 1]\n"
    "camino solo por la ciudad\n"
    "y el mar me llama\n"
    "[Chorus | unstable]\n"
    "brilla el mar en tus ojos\n"
    "brilla el mar en tus ojos\n"
    "[Bridge]\n"
    "todo se detiene\n"
)

_MARKED_DOCUMENT = LyricsDocument(
    lines=[
        SyncLine(start=0, text="camino solo por la ciudad"),
        SyncLine(start=5, text="y el mar me llama"),
        SyncLine(start=10, text="brilla el mar en tus ojos"),
        SyncLine(start=15, text="brilla el mar en tus ojos"),
        SyncLine(start=20, text="todo se detiene"),
    ],
    timed=True,
)


def test_sections_from_markers_lee_la_estructura() -> None:
    sections = sections_from_markers(_MARKED_DOCUMENT, _MARKED_TEXT, duration=25.0)
    kinds = [section.kind for section in sections]
    assert kinds == [SongSection.VERSE, SongSection.CHORUS, SongSection.BRIDGE]
    chorus = next(section for section in sections if section.kind == SongSection.CHORUS)
    assert chorus.start == 10.0 and chorus.end == 20.0


def test_sections_from_markers_sin_marcas_devuelve_vacio() -> None:
    assert sections_from_markers(_MARKED_DOCUMENT, "hola\nmundo\n", duration=25.0) == []


def test_direct_song_con_marcas_elige_el_estribillo() -> None:
    marked = sections_from_markers(_MARKED_DOCUMENT, _MARKED_TEXT, duration=25.0)
    plan = direct_song(
        _MARKED_DOCUMENT,
        duration=25,
        infer_profile=False,
        sections=marked,
        short_seconds=8,
        min_short_seconds=5,
        max_short_seconds=20,
    )
    assert [section.kind for section in plan.sections] == [
        SongSection.VERSE,
        SongSection.CHORUS,
        SongSection.BRIDGE,
    ]
    highlight = best_highlight(plan)
    assert highlight is not None and highlight.section == SongSection.CHORUS


# --- director: escenas y tiempos -------------------------------------------


def test_direct_song_reparte_las_lineas_en_escenas() -> None:
    plan = direct_song(_timed_document(), title="Brilla", infer_profile=False)
    assert plan.timed is True
    assert len(plan.scenes) == 6
    assert plan.scenes[0].start == 0.0
    assert plan.scenes[-1].end == pytest.approx(60.0)
    for scene in plan.scenes:
        assert scene.beat.subject
        assert scene.duration > 0


def test_direct_song_marca_las_lineas_gancho() -> None:
    plan = direct_song(_timed_document(), infer_profile=False)
    hooks = [scene for scene in plan.scenes if scene.hook]
    assert len(hooks) == 3


def test_direct_song_funde_lineas_muy_cortas() -> None:
    document = LyricsDocument(
        lines=[
            SyncLine(start=0, text="oh"),
            SyncLine(start=0.4, text="ay"),
            SyncLine(start=10, text="y ahora camino"),
        ],
        timed=True,
    )
    plan = direct_song(document, duration=20, infer_profile=False, min_line_seconds=2.0)
    assert len(plan.scenes) == 2
    assert plan.scenes[0].text == "oh ay"


def test_direct_song_sin_tiempos_reparte_sobre_la_duracion() -> None:
    document = parse_txt("uno\n\ndos\n\ntres\n\ncuatro")
    plan = direct_song(document, duration=40, infer_profile=False)
    assert plan.timed is False
    assert len(plan.scenes) == 4
    assert plan.scenes[0].start == 0.0
    assert plan.scenes[-1].end == pytest.approx(40.0)


def test_direct_song_infiere_animo_de_la_letra() -> None:
    document = parse_txt("tristeza y dolor, lagrimas sin ti\nla soledad me rompe el corazon")
    plan = direct_song(document, duration=20)
    assert plan.mood == Mood.SAD
    assert plan.sentiment == "negative"


def test_direct_song_sin_lineas_falla() -> None:
    with pytest.raises(MusicVideoError):
        direct_song(LyricsDocument(lines=[]), duration=10)


def test_direct_song_usa_la_energia_para_los_tramos() -> None:
    energies = [800.0] * 20 + [9000.0] * 20 + [800.0] * 20
    plan = direct_song(_timed_document(), duration=60, energies=energies, infer_profile=False)
    chorus = next(s for s in plan.sections if s.kind == SongSection.CHORUS)
    assert chorus.energy is not None and chorus.energy > 0.5


# --- dos líneas de producción ----------------------------------------------


def test_plan_to_script_quema_el_texto_de_cada_linea() -> None:
    plan = direct_song(_timed_document(), title="Brilla", infer_profile=False)
    script = plan_to_script(plan)
    assert len(script.scenes) == len(plan.scenes)
    assert script.scenes[0].text == plan.scenes[0].text


def test_plan_to_shot_plan_no_mete_la_letra_en_el_prompt() -> None:
    plan = direct_song(_timed_document(), title="Brilla", infer_profile=False)
    shot_plan = plan_to_shot_plan(plan)
    assert len(shot_plan.shots) == len(plan.scenes)
    for scene, shot in zip(plan.scenes, shot_plan.shots, strict=True):
        assert scene.text not in shot.prompt
        assert shot.prompt


def test_plan_to_shot_plan_del_mejor_momento_es_vertical() -> None:
    plan = direct_song(_timed_document(), title="Brilla", infer_profile=False)
    highlight = best_highlight(plan)
    assert highlight is not None
    scenes = plan.highlight_scenes(highlight)
    short = plan_to_shot_plan(plan, scenes=scenes, aspect=Aspect.VERTICAL)
    assert short.aspect is Aspect.VERTICAL
    assert len(short.shots) == len(scenes)
    assert all(
        scene.end > highlight.start and scene.start < highlight.end for scene in scenes
    )
