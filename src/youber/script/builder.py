"""Construye un proyecto de edición de vídeo a partir de un guion.

Toma un :class:`~youber.script.models.Script` (generado desde los insights
del canal) y lo materializa en un :class:`~youber.video.models.Project`
con :class:`VideoEditor`:

- Un clip por escena (los ficheros de vídeo propios se reparten en ciclo).
- Textos superpuestos con ``start_time``/``duration`` alineados a cada
  escena.
- Transiciones entre escenas (fade/crossfade según el tipo de escena).
- Música de fondo desde la biblioteca local (solo pistas ``local``:
  el editor no puede usar pistas cloud sin fichero).

Ética: el guion es una plantilla para **tu propio vídeo**; los clips deben
ser tuyos o con licencia, y la música de tu biblioteca local.
"""

from __future__ import annotations

from pathlib import Path

from youber.music.library import MusicLibrary
from youber.music.models import Track, TrackSource
from youber.script.models import Script
from youber.video.editor import VideoEditor
from youber.video.models import Project

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)


def default_font_file() -> str | None:
    """Devuelve una fuente TTF disponible (para drawtext sin fontconfig)."""
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _pick_local_track(
    library: MusicLibrary, script: Script
) -> Track | None:
    """Elige una pista local del catálogo para el mood del guion."""
    candidates = library.suggest(mood=script.music_mood, limit=20)
    for track in candidates:
        if track.source == TrackSource.LOCAL:
            return track
    # Sin mood: cualquiera local
    for track in library.all():
        if track.source == TrackSource.LOCAL:
            return track
    return None


def build_project(
    script: Script,
    clips: list[str | Path],
    library: MusicLibrary | None = None,
    editor: VideoEditor | None = None,
    title: str | None = None,
    resolution: tuple[int, int] = (1920, 1080),
    fps: int = 30,
) -> Project:
    """Construye el :class:`Project` de edición a partir del guion.

    Args:
        script: Guion generado (``youber.script.generator.generate_script``).
        clips: Ficheros de vídeo propios (se reparten por escena en ciclo).
        library: Catálogo de música (opcional; si falta, sin música).
        editor: Editor a usar (opcional; se crea uno con ``library``).
        title: Título del proyecto (por defecto: el tema del guion).
        resolution: Resolución del proyecto (WxH).
        fps: Fotogramas por segundo.

    Returns:
        Proyecto listo para ``editor.render(project, out, ...)``.

    Raises:
        ValueError: si no hay clips para las escenas.
    """
    if not clips:
        raise ValueError("Necesitas al menos un clip de vídeo propio")
    if editor is None:
        editor = VideoEditor(library=library)

    project = editor.new_project(title=title or script.topic, resolution=resolution, fps=fps)

    clip_paths = [Path(clip) for clip in clips]
    start = 0.0
    for index, scene in enumerate(script.scenes):
        clip = clip_paths[index % len(clip_paths)]
        editor.add_clip(project, clip, duration=scene.duration)
        if index > 0:
            editor.add_transition(
                project,
                clip_index=index,
                type=scene.transition,
                duration=min(scene.transition_duration, scene.duration / 2),
            )
        if scene.text:
            editor.add_text(
                project,
                scene.text,
                position=scene.position,
                font_size=56 if scene.type.value == "hook" else 44,
                font_file=default_font_file(),
                start_time=start,
                duration=scene.duration,
            )
        start += scene.duration

    if library is not None:
        track = _pick_local_track(library, script)
        if track is not None:
            editor.set_music(project, track.id, volume=0.25)
    return project
