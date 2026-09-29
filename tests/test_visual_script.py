"""Tests del guion visual: de la escena al prompt del modelo.

Cubre los tres fallos del criterio anterior, medidos sobre la salida real:

1. los tres bloques de contenido daban **el mismo prompt** (variedad falsa);
2. no había **acción** ni movimiento de **cámara** (el modelo de vídeo sabe
   moverse y no se le pedía);
3. el **tema iba en español** dentro de un prompt en inglés.

Y comprueba que las keywords de stock genéricas ya no entran en el prompt del
modelo, que el estilo no impone luz y que los clips de vídeo duran lo que su
plano en el montaje.
"""

from __future__ import annotations

from youber.genvideo.models import GenConfig, Resolution
from youber.genvideo.runner import requests_from_script
from youber.script.generator import generate_script
from youber.script.models import Scene, SceneType
from youber.visuals.beats import (
    BEATS_BY_SCENE,
    TOPIC_GLOSSARY,
    VisualBeat,
    beat_for,
    beat_from_template,
    compose_prompt,
    describe_topic,
    topic_theme,
)
from youber.visuals.models import STYLE_SUFFIXES, VisualStyle
from youber.visuals.prompts import build_shot_plan, shot_prompt


def _scenes(*kinds: SceneType) -> list[Scene]:
    """Escenas sencillas de 10 s, una por tipo indicado."""
    return [
        Scene(type=kind, title=f"Escena {index}", duration=10.0, text="Texto")
        for index, kind in enumerate(kinds)
    ]


# -- léxico del tema -------------------------------------------------------


def test_describe_topic_traduce_lo_que_sabe():
    """Traduce frases y palabras conocidas y se come artículos y preposiciones."""
    assert describe_topic("el paso del tiempo") == "the passing of time"
    assert describe_topic("la lluvia") == "rain"
    assert describe_topic("la ciudad de noche") == "a city night"
    assert describe_topic("el mar") == "the sea"


def test_describe_topic_deja_lo_que_no_sabe():
    """Mejor una palabra sin traducir que una invención."""
    assert describe_topic("kubernetes escalando") == "kubernetes escalando"
    assert describe_topic("el mar de kubernetes") == "the sea kubernetes"


def test_describe_topic_sin_palabras():
    """Sin contenido útil devuelve el tema original (no cadena vacía)."""
    assert describe_topic("") == ""
    assert describe_topic("el la") == "el la"


def test_topic_theme_conserva_el_original():
    """El inglés manda y el original queda detrás, entre paréntesis."""
    assert topic_theme("el paso del tiempo") == 'the passing of time ("el paso del tiempo")'
    # Sin nada que traducir no se duplica el tema.
    assert topic_theme("kubernetes") == "kubernetes"


def test_glosario_coherente():
    """El glosario está en minúsculas y sin traducciones vacías."""
    assert TOPIC_GLOSSARY
    assert all(key == key.lower().strip() for key in TOPIC_GLOSSARY)
    assert all(value.strip() for value in TOPIC_GLOSSARY.values())


# -- encuadres -------------------------------------------------------------


def test_beats_completos_y_variados():
    """Cada papel de escena tiene encuadres suficientes y con los cinco campos."""
    for kind in SceneType:
        beats = BEATS_BY_SCENE[kind]
        assert len(beats) >= 3, kind
        for beat in beats:
            assert beat.camera and beat.subject and beat.action
            assert beat.setting and beat.light


def test_beat_describe_omite_campos_vacios():
    """La frase del plano no arrastra comas ni espacios de más."""
    assert VisualBeat(camera="", subject="a tree").describe() == "a tree"
    completo = VisualBeat(
        camera="macro shot",
        subject="hands",
        action="working",
        setting="a desk",
        light="lamp light",
    )
    assert completo.describe() == "macro shot: hands working, a desk, lamp light"


def test_beat_for_varia_dentro_del_bloque():
    """El fallo original: los tres bloques de contenido daban el mismo plano."""
    descripciones = {beat_for(SceneType.CONTENT, index).describe() for index in range(3)}
    assert len(descripciones) == 3
    # Determinista, y los tipos desconocidos caen en los encuadres genéricos.
    assert beat_for(SceneType.CONTENT, 7).describe() == beat_for(SceneType.CONTENT, 7).describe()
    assert beat_for(None, 0).describe()
    assert beat_for(None, 11).describe()


def test_beat_from_template_compatible():
    """Una plantilla antigua con ``{topic}`` sigue funcionando."""
    beat = beat_from_template("wide shot of {topic}", "la lluvia")
    assert beat.subject == "wide shot of la lluvia"
    assert beat.describe() == "wide shot of la lluvia"


# -- composición del prompt ------------------------------------------------


def test_compose_prompt_orden_y_piezas():
    """El prompt: plano → atmósfera → contenido → tema → tono → estilo."""
    beat = VisualBeat(
        camera="slow push in",
        subject="a lone figure",
        action="walking",
        setting="an empty street",
        light="cold dawn light",
    )
    prompt = compose_prompt(
        beat,
        topic="el paso del tiempo",
        keywords=["niebla", "noche"],
        atmosphere="cold blue tones",
        tone="melancólico",
        style_suffix=STYLE_SUFFIXES[VisualStyle.CINEMATIC],
    )
    assert prompt.startswith("slow push in: a lone figure walking, an empty street, cold dawn light")
    assert "cold blue tones" in prompt
    assert "featuring niebla, noche" in prompt
    assert 'theme: the passing of time ("el paso del tiempo")' in prompt
    assert "tone: melancólico" in prompt
    assert prompt.endswith(STYLE_SUFFIXES[VisualStyle.CINEMATIC])


def test_compose_prompt_sin_extras():
    """Sin tema, tono ni estilo no se añaden separadores sueltos."""
    beat = VisualBeat(camera="", subject="a tree")
    assert compose_prompt(beat) == "a tree"
    assert compose_prompt(beat, style_suffix="no text") == "a tree; no text"


def test_shot_prompt_acepta_beat_y_plantilla():
    """``shot_prompt`` mantiene la firma antigua con la composición nueva."""
    desde_beat = shot_prompt(
        VisualBeat(camera="", subject="a tree"), topic="el bosque", style=VisualStyle.MINIMAL
    )
    assert "a tree" in desde_beat
    assert 'theme: a forest ("el bosque")' in desde_beat
    desde_plantilla = shot_prompt("wide shot of {topic}", topic="la lluvia", style=VisualStyle.MINIMAL)
    assert "la lluvia" in desde_plantilla


def test_el_estilo_ya_no_impone_luz():
    """La luz la dicta el plano y el mood, no el sufijo de estilo."""
    cinematic = STYLE_SUFFIXES[VisualStyle.CINEMATIC]
    assert "dramatic lighting" not in cinematic
    assert "moody atmosphere" not in cinematic
    assert "no text" in cinematic


# -- plan de planos --------------------------------------------------------


def test_plan_de_planos_prompts_distintos_por_bloque():
    """El bug que motivó el cambio: tres bloques de contenido, tres prompts."""
    script = generate_script({}, topic="el paso del tiempo", duration=60)
    plan = build_shot_plan(
        script.topic, script.scenes, duration=script.total_duration, style=VisualStyle.CINEMATIC
    )
    contenido = [
        shot.prompt
        for shot in plan.shots
        if shot.scene_index is not None
        and script.scenes[shot.scene_index].type == SceneType.CONTENT
    ]
    assert len(contenido) == 3
    assert len(set(contenido)) == 3
    for shot in plan.shots:
        assert "theme: the passing of time" in shot.prompt
        assert shot.beat  # trazabilidad del encuadre


def test_plan_de_planos_no_mete_keywords_genericas():
    """Las keywords de stock genéricas son para buscar B-roll, no para el prompt."""
    script = generate_script({}, topic="el paso del tiempo", duration=60)
    plan = build_shot_plan(script.topic, script.scenes, duration=script.total_duration)
    assert all("featuring" not in shot.prompt for shot in plan.shots)


def test_plan_de_planos_usa_keywords_del_contenido():
    """Si las keywords vienen del contenido real, sí entran (dan coherencia)."""
    script = generate_script(
        {}, topic="el paso del tiempo", duration=60, content_keywords=["reloj", "arena"]
    )
    assert all(scene.keywords_from_content for scene in script.scenes)
    plan = build_shot_plan(script.topic, script.scenes, duration=script.total_duration)
    assert all("featuring reloj, arena" in shot.prompt for shot in plan.shots)


def test_plan_de_planos_sin_escenas_usa_encuadres_genericos():
    """Sin guion, los planes siguen teniendo prompts distintos entre sí."""
    plan = build_shot_plan("el paso del tiempo", duration=32.0, shots=4)
    assert len(plan.shots) == 4
    assert len({shot.prompt for shot in plan.shots}) == 4


def test_titulo_del_gancho_ya_no_es_la_palabra_hook():
    """El título de la escena del gancho no sale como el nombre del tipo."""
    script = generate_script({}, topic="prueba", duration=60)
    hook = next(scene for scene in script.scenes if scene.type == SceneType.HOOK)
    assert hook.title == "Gancho"


# -- integración con la generación de vídeo --------------------------------


def test_los_clips_duran_lo_que_su_plano():
    """El clip se pide con la duración del plano (frames ``4k+1``), no 5 s fijos."""
    script = generate_script({}, topic="el paso del tiempo", duration=60)
    clips = requests_from_script(script, config=GenConfig.for_resolution(Resolution.SD))
    assert clips
    for clip in clips:
        assert clip.config.frames % 4 == 1
        assert clip.duration_hint is not None
        assert abs(clip.config.clip_seconds - clip.duration_hint) <= 0.25
    # Y distintos planos usan encuadres distintos: prompts distintos.
    assert len({clip.prompt for clip in clips}) == len(clips)
