"""Generación visual local: planos creados por IA + animación (ruta C de BARF).

El vídeo nace del guion, no de clips ajenos:

1. :mod:`youber.visuals.prompts` convierte escenas + mood en un **plan de
   planos** (prompt, encuadre y movimiento por plano),
2. :mod:`youber.visuals.generator` dibuja cada still (SDXL-Turbo local en la
   GPU, o un generador de prueba determinista sin GPU),
3. :mod:`youber.visuals.animate` los anima con Ken Burns (paneo/zoom) y
4. :mod:`youber.visuals.render` los monta con la canción usando el motor de
   vídeo del framework (transiciones, textos, audio a 192 kbps).

:mod:`youber.visuals.short` elige y corta el trozo con más energía de una
canción: el corte vertical (Shorts) sale de ahí.

:mod:`youber.visuals.selector` decide el **estilo y el ritmo del montaje** a
partir del audio y de los metadatos (un estilo fijo quema el concepto).

Ética: los planos son **contenido original generado en local**; el modelo por
defecto (SDXL-Turbo) es libre y no se envía nada a servicios externos.
"""

from youber.visuals.animate import animate_shot
from youber.visuals.generator import (
    DEFAULT_MODEL,
    DiffusersGenerator,
    ImageGenerator,
    StubGenerator,
    create_generator,
    diffusers_available,
)
from youber.visuals.models import (
    DEFAULT_SECONDS_PER_SHOT,
    Aspect,
    Motion,
    Shot,
    ShotPlan,
    VisualStyle,
)
from youber.visuals.prompts import build_shot_plan, fit_durations, shot_prompt
from youber.visuals.render import (
    VisualResult,
    animate_clips,
    build_visual_project,
    generate_images,
    render_visuals,
)
from youber.visuals.selector import (
    AUTO_STYLE,
    StyleChoice,
    StyleSignals,
    build_signals,
    choose_style,
    score_styles,
)
from youber.visuals.short import (
    DEFAULT_SHORT_DURATION,
    best_window_start,
    extract_window,
    loudness_profile,
    pick_window,
)

__all__ = [
    "AUTO_STYLE",
    "DEFAULT_MODEL",
    "DEFAULT_SECONDS_PER_SHOT",
    "DEFAULT_SHORT_DURATION",
    "Aspect",
    "DiffusersGenerator",
    "ImageGenerator",
    "Motion",
    "Shot",
    "ShotPlan",
    "StubGenerator",
    "StyleChoice",
    "StyleSignals",
    "VisualResult",
    "VisualStyle",
    "animate_clips",
    "animate_shot",
    "best_window_start",
    "build_shot_plan",
    "build_signals",
    "build_visual_project",
    "choose_style",
    "create_generator",
    "diffusers_available",
    "extract_window",
    "fit_durations",
    "generate_images",
    "loudness_profile",
    "pick_window",
    "render_visuals",
    "score_styles",
    "shot_prompt",
]
