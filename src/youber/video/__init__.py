"""Motor de edición de vídeo de BARF.

Edición de vídeo educativa con FFmpeg: proyectos con múltiples clips,
transiciones (fade, crossfade, wipe, slide), textos e imágenes superpuestas
y música de fondo del catálogo.

Límites éticos (igual que el resto del framework):

- Solo contenido propio o con licencia; sin piratear.
- Sin manipulación de métricas: es edición, no inflado.
- Uso educativo y de investigación.
"""

from youber.video.editor import VideoEditor
from youber.video.models import (
    Clip,
    ImageOverlay,
    Project,
    TextOverlay,
    TextPosition,
    Transition,
    TransitionType,
)
from youber.video.renderer import render_project
from youber.video.timeline import Timeline, TimelineSegment

__all__ = [
    "Clip",
    "ImageOverlay",
    "Project",
    "TextOverlay",
    "TextPosition",
    "Timeline",
    "TimelineSegment",
    "Transition",
    "TransitionType",
    "VideoEditor",
    "render_project",
]
