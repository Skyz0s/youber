"""Videoclip **dirigido por la letra** (``youber.musicvideo``).

Invierte el flujo anterior: la canción es la protagonista y su letra dirige el
vídeo. De una misma dirección salen **dos líneas de producción**:

1. el **videoclip** completo (duración = canción), en horizontal;
2. un **corto vertical** con los *mejores momentos* (estribillo), para
   Shorts/Reels.

Flujo:

1. :mod:`youber.musicvideo.director` convierte la letra en un
   :class:`~youber.musicvideo.models.MusicVideoPlan` (una escena por línea,
   tramos y mejores momentos);
2. :func:`youber.musicvideo.director.plan_to_shot_plan` da los planos que
   genera y monta el motor visual (:mod:`youber.visuals`, :mod:`youber.genvideo`);
3. :func:`youber.musicvideo.director.plan_to_script` da el guion con el texto
   de cada línea para quemar en pantalla.

Ética: la letra es tuya (o se transcribe de tu propio audio) y los planos son
contenido original generado en local. Sin material ajeno ni manipulación de
métricas.
"""

from youber.musicvideo.director import (
    DEFAULT_SHORT_SECONDS,
    best_highlight,
    direct_song,
    plan_to_script,
    plan_to_shot_plan,
)
from youber.musicvideo.lexicon import beat_from_line, keywords_from_line, normalize
from youber.musicvideo.models import (
    Highlight,
    LyricScene,
    MusicVideoError,
    MusicVideoPlan,
    SectionSpan,
    SongSection,
)
from youber.musicvideo.sections import detect_sections, find_highlights, score_section

__all__ = [
    "Highlight",
    "LyricScene",
    "MusicVideoError",
    "MusicVideoPlan",
    "SectionSpan",
    "SongSection",
    "beat_from_line",
    "best_highlight",
    "DEFAULT_SHORT_SECONDS",
    "detect_sections",
    "direct_song",
    "find_highlights",
    "keywords_from_line",
    "normalize",
    "plan_to_script",
    "plan_to_shot_plan",
    "score_section",
]
