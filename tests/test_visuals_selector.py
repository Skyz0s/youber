"""Tests del selector de estilo visual (`youber.visuals.selector`).

El selector decide estilo, fundidos, arranque del ciclo de movimientos y
segundos por plano a partir del audio y de los metadatos. Todo es determinista
y offline: aquí se comprueba que cada señal mueve el estilo en la dirección
esperada y que dos piezas distintas no reciben siempre lo mismo.
"""

from __future__ import annotations

import shutil

import pytest

from youber.music.audio_features.models import AudioFeatures, AudioProfile
from youber.script.models import Scene, SceneType
from youber.visuals.models import DEFAULT_MOTION_CYCLE, Aspect, VisualStyle
from youber.visuals.prompts import build_shot_plan, plan_shots_count
from youber.visuals.selector import (
    AUTO_STYLE,
    build_signals,
    choose_style,
    keyword_hits,
    motion_offset_for,
    score_styles,
    seconds_per_shot_for,
    signals_from_audio,
    signals_from_loudness,
    signals_from_themes,
    transition_for,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _profile(
    *,
    energy: float = 0.5,
    valence: float = 0.5,
    tempo: float = 110.0,
    dance: float = 0.5,
    acoustic: float = 0.3,
    mode: int = 1,
    moods: list[str] | None = None,
) -> AudioProfile:
    """Perfil de audio sintético para los tests (sin red ni Spotify)."""
    features = AudioFeatures(
        danceability=dance,
        energy=energy,
        valence=valence,
        acousticness=acoustic,
        instrumentalness=0.2,
        liveness=0.1,
        speechiness=0.05,
        tempo=tempo,
        duration_ms=120_000,
        key=5,
        mode=mode,
        time_signature=4,
        confidence=0.5,
    )
    return AudioProfile(
        track_id="t1",
        track_title="Prueba",
        artist="Youber",
        features=features,
        moods=moods or [],
    )


def _scenes() -> list[Scene]:
    """Tres escenas de guion (gancho, desarrollo y cierre)."""
    return [
        Scene(type=SceneType.HOOK, title="Gancho", duration=10.0, text="Empieza aquí"),
        Scene(type=SceneType.CONTENT, title="Desarrollo", duration=20.0, text="El detalle"),
        Scene(type=SceneType.CTA, title="Cierre", duration=10.0, text="Suscríbete"),
    ]


# ---------------------------------------------------------------------------
# Señales
# ---------------------------------------------------------------------------


def test_signals_from_audio_mapea_los_ejes():
    axes = signals_from_audio(
        _profile(energy=0.9, valence=0.8, tempo=180.0, dance=0.85, acoustic=0.05, mode=1)
    )
    assert axes["energy"][0] == pytest.approx(0.9)
    assert axes["valence"][0] == pytest.approx(0.8)
    assert axes["tempo"][0] == pytest.approx(1.0)
    assert axes["dance"][0] == pytest.approx(0.85)
    assert axes["tension"][0] < 0.2  # alegre y en mayor → poca tensión
    assert axes["intimacy"][0] < 0.2


def test_signals_from_audio_sin_perfil():
    assert signals_from_audio(None) == {}


def test_signals_from_audio_triste_en_menor_sube_la_tension():
    axes = signals_from_audio(_profile(energy=0.2, valence=0.1, acoustic=0.8, mode=0))
    assert axes["tension"][0] > 0.8
    assert axes["intimacy"][0] > 0.6


def test_signals_from_loudness_energia_y_dinamica():
    axes = signals_from_loudness([100.0, 200.0, 300.0, 400.0])
    assert 0.0 < axes["energy"][0] <= 1.0
    assert 0.0 < axes["tension"][0] <= 1.0
    assert signals_from_loudness([]) == {}
    assert signals_from_loudness([0.0, 0.0]) == {}


def test_signals_from_loudness_saturado_en_uno():
    axes = signals_from_loudness([9000.0] * 10)
    assert axes["energy"][0] == 1.0
    assert axes["tension"][0] == 0.0  # sin dinámica no hay tensión


def test_signals_from_themes_tristeza_y_amor():
    dark = signals_from_themes({"tristeza": 1.0})
    assert dark["tension"][0] > 0.5
    assert dark["valence"][0] < 0.2
    love = signals_from_themes({"amor": 1.0})
    assert love["intimacy"][0] > 0.5
    assert love["valence"][0] > 0.5


def test_signals_from_themes_sentimiento_y_vacio():
    assert signals_from_themes({}) == {}
    with_sentiment = signals_from_themes({"calma": 1.0}, sentiment="positivo")
    without = signals_from_themes({"calma": 1.0})
    assert with_sentiment["valence"][0] >= without["valence"][0]


def test_keyword_hits_por_estilo():
    hits = keyword_hits("Tutorial de python para analizar datos")
    assert hits[VisualStyle.MINIMAL] >= 3
    assert hits[VisualStyle.VIBRANT] == 0
    assert keyword_hits("lofi beats para dormir")[VisualStyle.DREAMY] >= 2


def test_build_signals_sin_fuentes_es_neutro():
    signals = build_signals()
    assert signals.as_axes() == {axis: 0.5 for axis in signals.as_axes()}
    assert signals.sources == []


def test_build_signals_mezcla_fuentes():
    signals = build_signals(
        profile=_profile(energy=0.2, valence=0.15, acoustic=0.9, mode=0),
        energies=[200.0, 400.0, 800.0],
        themes={"tristeza": 0.9, "misterio": 0.4},
        metadata_text="lofi triste para la noche",
        mood="tristeza",
    )
    assert {"audio", "sonoridad", "temas", "palabras clave", "mood"} <= set(signals.sources)
    assert signals.energy < 0.4
    assert signals.tension > 0.5
    assert signals.themes == {"tristeza": 0.9, "misterio": 0.4}
    assert all(0.0 <= value <= 1.0 for value in signals.as_axes().values())


def test_dominant_ordena_por_desvio():
    signals = build_signals(profile=_profile(energy=0.95, valence=0.9, mode=1))
    dominant = signals.dominant(limit=2)
    assert dominant[0][0] in {"energy", "valence"}
    assert dominant[0][1] > 0.5


# ---------------------------------------------------------------------------
# Puntuación y elección
# ---------------------------------------------------------------------------


def test_score_styles_neutro_solo_destaca_cinematic():
    scores = score_styles(build_signals())
    ranked = sorted(scores.items(), key=lambda item: -item[1])
    assert ranked[0][0] is VisualStyle.CINEMATIC
    assert all(score == 0.0 for style, score in scores.items() if style is not VisualStyle.CINEMATIC)


def test_choose_style_sin_clave_elige_el_primero_empatado():
    choice = choose_style(AUTO_STYLE)
    assert choice.style is VisualStyle.CINEMATIC
    assert choice.explicit is False
    assert len(choice.candidates) == len(list(VisualStyle))


def test_estilo_automatico_audio_triste_da_dark():
    signals = build_signals(
        profile=_profile(energy=0.2, valence=0.1, tempo=70.0, dance=0.2, acoustic=0.6, mode=0),
        themes={"tristeza": 1.0},
    )
    choice = choose_style(AUTO_STYLE, signals=signals, variation_key="video-1")
    assert choice.style is VisualStyle.DARK
    assert "dark" in choice.reason
    assert choice.scores["dark"] > choice.scores["vibrant"]


def test_estilo_automatico_audio_energico_da_vibrant():
    signals = build_signals(
        profile=_profile(energy=0.95, valence=0.9, tempo=150.0, dance=0.9, acoustic=0.05)
    )
    choice = choose_style(AUTO_STYLE, signals=signals, variation_key="video-2")
    assert choice.style is VisualStyle.VIBRANT


def test_estilo_automatico_calma_da_dreamy():
    signals = build_signals(
        profile=_profile(energy=0.25, valence=0.6, tempo=80.0, dance=0.3, acoustic=0.9),
        themes={"calma": 1.0},
    )
    choice = choose_style(AUTO_STYLE, signals=signals, variation_key="video-3")
    assert choice.style is VisualStyle.DREAMY


def test_estilo_automatico_metadatos_tecnicos_dan_minimal():
    signals = build_signals(metadata_text="Tutorial de python y análisis de datos")
    choice = choose_style(AUTO_STYLE, signals=signals, variation_key="video-4")
    assert choice.style is VisualStyle.MINIMAL


def test_estilo_forzado_se_respeta():
    signals = build_signals(profile=_profile(energy=0.95, valence=0.9))
    choice = choose_style("dark", signals=signals, variation_key="video-5")
    assert choice.style is VisualStyle.DARK
    assert choice.explicit is True
    assert choice.candidates == ["dark"]
    assert "a mano" in choice.reason
    # El ritmo y los fundidos siguen saliendo del audio, no del estilo forzado.
    assert choice.transition == transition_for(signals)
    assert choice.seconds_per_shot == seconds_per_shot_for(signals)


def test_estilo_invalido_falla():
    with pytest.raises(ValueError, match="no_es_un_estilo"):
        choose_style("no_es_un_estilo")


def test_choice_determinista_para_la_misma_clave():
    signals = build_signals()
    first = choose_style(AUTO_STYLE, signals=signals, variation_key="misma-clave")
    second = choose_style(AUTO_STYLE, signals=signals, variation_key="misma-clave")
    assert first == second


def test_choice_varia_entre_piezas_distintas():
    signals = build_signals()
    styles = {
        choose_style(AUTO_STYLE, signals=signals, variation_key=f"video-{index}").style
        for index in range(40)
    }
    assert len(styles) > 1  # señales empatadas: la clave reparte el estilo
    assert styles <= set(VisualStyle)


def test_ritmo_del_montaje_responde_a_las_senales():
    slow = build_signals(profile=_profile(tempo=60.0))
    fast = build_signals(profile=_profile(tempo=170.0))
    assert transition_for(slow) > transition_for(fast)
    calm = build_signals(profile=_profile(energy=0.1))
    energetic = build_signals(profile=_profile(energy=1.0))
    assert seconds_per_shot_for(calm) > seconds_per_shot_for(energetic)


def test_ritmo_por_defecto_en_los_rangos_documentados():
    neutral = build_signals()
    assert transition_for(neutral) == pytest.approx(0.8)
    assert seconds_per_shot_for(neutral) == pytest.approx(16.0)


def test_motion_offset_estable_y_acotado():
    assert motion_offset_for("") == 0
    assert motion_offset_for("clave") == motion_offset_for("clave")
    assert 0 <= motion_offset_for("clave") < len(DEFAULT_MOTION_CYCLE)


# ---------------------------------------------------------------------------
# Integración con el plan y el render
# ---------------------------------------------------------------------------


def test_plan_shots_count_usa_los_segundos_por_plano():
    assert plan_shots_count(120.0) == 8
    assert plan_shots_count(120.0, seconds_per_shot=24.0) == 5
    assert plan_shots_count(120.0, seconds_per_shot=10.0) == 12
    assert plan_shots_count(120.0, shots=3, seconds_per_shot=24.0) == 3


def test_build_shot_plan_aplica_el_desplazamiento_de_movimientos():
    plan = build_shot_plan("tema", _scenes(), duration=40.0, motion_offset=3)
    assert plan.motion_offset == 3
    assert [shot.motion for shot in plan.shots] == [
        DEFAULT_MOTION_CYCLE[(index + 3) % len(DEFAULT_MOTION_CYCLE)]
        for index in range(len(plan.shots))
    ]
    assert build_shot_plan("tema", _scenes(), duration=40.0, motion_offset=0).shots[
        0
    ].motion is DEFAULT_MOTION_CYCLE[0]


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_render_visuals_resuelve_estilo_y_lo_deja_en_el_plan(tmp_path):
    import asyncio

    from youber.audio._ffmpeg import run_command
    from youber.visuals.generator import StubGenerator
    from youber.visuals.render import render_visuals

    song = tmp_path / "cancion.wav"
    asyncio.run(
        run_command(
            [
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=6",
                "-ac", "2", "-ar", "44100", str(song),
            ]
        )
    )
    signals = build_signals(
        profile=_profile(energy=0.9, valence=0.85, tempo=145.0, dance=0.85, acoustic=0.05)
    )
    result = asyncio.run(
        render_visuals(
            topic="prueba",
            output=tmp_path / "out.mp4",
            song=song,
            style=AUTO_STYLE,
            signals=signals,
            shots=3,
            generator=StubGenerator(),
        )
    )
    assert result.plan.style is VisualStyle.VIBRANT
    assert result.plan.style_reason.startswith("estilo automático")
    assert result.plan.style_scores["vibrant"] == max(result.plan.style_scores.values())
    assert result.plan.seed == 1234  # semilla resuelta, el render es repetible
    assert set(result.plan.style_signals) == {
        "energy", "valence", "tempo", "dance", "tension", "intimacy",
    }
    assert result.style_choice is not None
    assert result.style_choice.style is result.plan.style
    assert result.plan.aspect is Aspect.LANDSCAPE


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg no está instalado")
def test_render_visuals_acepta_estilo_forzado(tmp_path):
    import asyncio

    from youber.audio._ffmpeg import run_command
    from youber.visuals.generator import StubGenerator
    from youber.visuals.render import render_visuals

    song = tmp_path / "cancion.wav"
    asyncio.run(
        run_command(
            [
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=6",
                "-ac", "2", "-ar", "44100", str(song),
            ]
        )
    )
    result = asyncio.run(
        render_visuals(
            topic="prueba",
            output=tmp_path / "out.mp4",
            song=song,
            style="dreamy",
            shots=3,
            generator=StubGenerator(),
        )
    )
    assert result.plan.style is VisualStyle.DREAMY
    assert result.style_choice is not None
    assert result.style_choice.explicit is True
