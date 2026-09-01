"""Generador de guiones para edición de vídeo (BARF).

Analiza la estructura de los vídeos de un canal de YouTube (insights de
:mod:`youber.research.patterns`) y produce un guion (hook → intro →
contenido → clímax → CTA) que se materializa en un
:class:`~youber.video.models.Project` con :mod:`youber.script.builder`,
usando tu música local del catálogo.

Flujo típico::

    insights = channel_overview(channel)   # youber.research
    script = generate_script(insights, topic="Mi vídeo")
    project = build_project(script, clips=["a.mp4"], library=MusicLibrary("music"))
    await VideoEditor(library=library).render(project, "final.mp4")

Ética: el guion es una plantilla para **tu propio vídeo**; los clips deben
ser tuyos o con licencia, y la música de tu biblioteca local.
"""

from youber.script.builder import build_project, default_font_file
from youber.script.generator import generate_script
from youber.script.models import Scene, SceneType, Script
from youber.script.transcripts import (
    TranscriptAnalysis,
    TranscriptSnippet,
    analyze_channel,
    analyze_video,
    fetch_transcript,
    hook_template,
)

__all__ = [
    "Scene",
    "SceneType",
    "Script",
    "TranscriptAnalysis",
    "TranscriptSnippet",
    "analyze_channel",
    "analyze_video",
    "build_project",
    "default_font_file",
    "fetch_transcript",
    "generate_script",
    "hook_template",
]
