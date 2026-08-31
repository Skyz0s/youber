"""Motor de edición de vídeo de BARF.

:class:`VideoEditor` es la fachada del motor: crea proyectos, añade clips,
transiciones, textos e imágenes superpuestas, asocia música del catálogo y
renderiza el resultado final con FFmpeg.

Uso típico:

.. code-block:: python

    editor = VideoEditor()
    project = editor.new_project("Mi vídeo", resolution=(1280, 720))
    editor.add_clip(project, "intro.mp4")
    editor.add_clip(project, "main.mp4", speed=1.5)
    editor.add_transition(project, clip_index=1, type=TransitionType.FADE)
    editor.add_text(project, "Hola mundo")
    editor.set_music(project, track_id="abc123")
    await editor.render(project, "final.mp4")
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from youber.music.library import MusicLibrary
from youber.video.models import (
    Clip,
    ImageOverlay,
    Project,
    TextOverlay,
    Transition,
    TransitionType,
)
from youber.video.renderer import render_project


class VideoEditor:
    """Motor de edición de vídeo: proyectos, clips, overlays y renderizado."""

    def __init__(self, library: MusicLibrary | None = None) -> None:
        """Crea el editor.

        Args:
            library: Catálogo de música opcional para resolver
                ``Project.music_track_id`` a una ruta de fichero.
        """
        self.library = library

    # -- Proyectos ----------------------------------------------------------

    def new_project(
        self,
        title: str,
        resolution: tuple[int, int] = (1920, 1080),
        fps: int = 30,
    ) -> Project:
        """Crea un proyecto nuevo vacío."""
        now = datetime.now().isoformat(timespec="seconds")
        return Project(
            title=title,
            resolution=resolution,
            fps=fps,
            created_at=now,
            updated_at=now,
        )

    def save(self, project: Project, path: str | Path) -> Path:
        """Guarda el proyecto como JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        return target

    @staticmethod
    def load(path: str | Path) -> Project:
        """Carga un proyecto desde JSON."""
        return Project.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def _touch(self, project: Project) -> Project:
        project.updated_at = datetime.now().isoformat(timespec="seconds")
        return project

    # -- Construcción del proyecto ------------------------------------------

    def add_clip(
        self,
        project: Project,
        file_path: str | Path,
        **kwargs: Any,
    ) -> Project:
        """Añade un clip al proyecto (``start``, ``duration``, ``volume``, ``speed``, ``crop``)."""
        project.clips.append(Clip(file_path=Path(file_path), **kwargs))
        return self._touch(project)

    def add_transition(
        self,
        project: Project,
        clip_index: int,
        type: TransitionType | str = TransitionType.FADE,
        duration: float = 1.0,
    ) -> Project:
        """Añade una transición que termina en el clip ``clip_index``.

        El tipo se acepta como :class:`TransitionType` o como cadena
        (``"fade"``, ``"crossfade"``, ``"wipe"``, ``"slide"``, ``"none"``).
        """
        if isinstance(type, str):
            type = TransitionType(type)
        project.transitions.append(
            Transition(clip_index=clip_index, type=type, duration=duration)
        )
        return self._touch(project)

    def add_text(
        self,
        project: Project,
        text: str,
        **kwargs: Any,
    ) -> Project:
        """Añade un texto superpuesto (``position``, ``font_size``, ``color``...)."""
        project.text_overlays.append(TextOverlay(text=text, **kwargs))
        return self._touch(project)

    def add_image(
        self,
        project: Project,
        image_path: str | Path,
        **kwargs: Any,
    ) -> Project:
        """Añade una imagen superpuesta (marca de agua)."""
        project.image_overlays.append(
            ImageOverlay(image_path=Path(image_path), **kwargs)
        )
        return self._touch(project)

    def set_music(
        self,
        project: Project,
        track_id: str,
        volume: float = 0.3,
    ) -> Project:
        """Asocia una pista del catálogo de música como fondo musical."""
        project.music_track_id = track_id
        project.music_volume = volume
        return self._touch(project)

    # -- Renderizado --------------------------------------------------------

    def _resolve_music(self, project: Project) -> str | None:
        """Resuelve ``music_track_id`` a una ruta de fichero (si es posible)."""
        if not project.music_track_id:
            return None
        if self.library is None:
            raise ValueError(
                "El proyecto tiene music_track_id pero el editor no tiene "
                "catálogo (pasa library=MusicLibrary(...))"
            )
        track = self.library.get(project.music_track_id)
        if track is None:
            raise ValueError(f"Pista de música no encontrada: {project.music_track_id}")
        return str(track.file_path)

    async def render(
        self,
        project: Project,
        output_path: str | Path,
        music_path: str | None = None,
    ) -> str:
        """Renderiza el proyecto a un fichero de vídeo.

        Args:
            project: Proyecto a renderizar.
            output_path: Ruta del vídeo de salida (``.mp4`` o ``.mkv``).
            music_path: Ruta de música explícita (opcional; si no se da y el
                proyecto tiene ``music_track_id``, se resuelve vía catálogo).

        Returns:
            La ruta del vídeo renderizado.
        """
        resolved = music_path or self._resolve_music(project)
        return await render_project(project, str(output_path), music_path=resolved)
