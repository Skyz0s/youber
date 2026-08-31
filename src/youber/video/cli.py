"""CLI ``youber-edit``: motor de edición de vídeo de BARF.

Comandos: ``new``, ``add-clip``, ``add-transition``, ``add-text``,
``add-image``, ``set-music`` y ``render``.

Ejemplos:

.. code-block:: bash

    youber-edit new proyecto.json --title "Mi vídeo" --resolution 1280x720
    youber-edit add-clip proyecto.json intro.mp4
    youber-edit add-clip proyecto.json main.mp4 --speed 1.5
    youber-edit add-transition proyecto.json --clip-index 1 --type fade --duration 1
    youber-edit add-text proyecto.json "Hola mundo" --position bottom_center
    youber-edit set-music proyecto.json <track-id> --volume 0.3
    youber-edit render proyecto.json -o final.mp4 --library ~/musica
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.music.library import MusicLibrary
from youber.video.editor import VideoEditor
from youber.video.models import Project, TransitionType

console = Console()


def _transition_type(value: str) -> TransitionType:
    """Convierte el texto del usuario en un :class:`TransitionType`."""
    try:
        return TransitionType(value.strip().lower())
    except ValueError as exc:
        valid = ", ".join(t.value for t in TransitionType)
        raise argparse.ArgumentTypeError(f"Transición desconocida: {value!r}. Válidas: {valid}") from exc


def _resolution(value: str) -> tuple[int, int]:
    """Convierte ``1920x1080`` en ``(1920, 1080)``."""
    try:
        width, height = value.lower().split("x")
        return (int(width), int(height))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(f"Resolución inválida: {value!r} (usa WxH, p. ej. 1920x1080)") from exc


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-edit``."""
    parser = argparse.ArgumentParser(
        prog="youber-edit",
        description="BARF: motor de edición de vídeo (uso educativo)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="Crea un proyecto nuevo (JSON)")
    new.add_argument("project", help="Ruta del fichero de proyecto (.json)")
    new.add_argument("--title", required=True, help="Título del proyecto")
    new.add_argument("--resolution", type=_resolution, default="1920x1080", help="Resolución (WxH)")
    new.add_argument("--fps", type=int, default=30, help="Fotogramas por segundo")

    add_clip = sub.add_parser("add-clip", help="Añade un clip al proyecto")
    add_clip.add_argument("project", help="Ruta del proyecto (.json)")
    add_clip.add_argument("video", help="Ruta del fichero de vídeo")
    add_clip.add_argument("--start", type=float, default=0.0, help="Inicio dentro del fichero (s)")
    add_clip.add_argument("--duration", type=float, default=None, help="Duración del clip (s)")
    add_clip.add_argument("--volume", type=float, default=1.0, help="Volumen 0.0-2.0")
    add_clip.add_argument("--speed", type=float, default=1.0, help="Velocidad (1.0 = normal)")

    add_transition = sub.add_parser("add-transition", help="Añade una transición")
    add_transition.add_argument("project", help="Ruta del proyecto (.json)")
    add_transition.add_argument("--clip-index", type=int, required=True, help="Clip donde termina")
    add_transition.add_argument("--type", type=_transition_type, default=TransitionType.FADE)
    add_transition.add_argument("--duration", type=float, default=1.0, help="Duración (s)")

    add_text = sub.add_parser("add-text", help="Añade un texto superpuesto")
    add_text.add_argument("project", help="Ruta del proyecto (.json)")
    add_text.add_argument("text", help="Texto a dibujar")
    add_text.add_argument("--position", default="bottom_center", help="Posición (top_left, center, ...)")
    add_text.add_argument("--font-size", type=int, default=48, help="Tamaño de fuente")
    add_text.add_argument("--color", default="white", help="Color del texto")
    add_text.add_argument("--start-time", type=float, default=0.0, help="Inicio (s)")

    add_image = sub.add_parser("add-image", help="Añade una imagen superpuesta")
    add_image.add_argument("project", help="Ruta del proyecto (.json)")
    add_image.add_argument("image", help="Ruta de la imagen")
    add_image.add_argument("--position", default="bottom_right", help="Posición")
    add_image.add_argument("--opacity", type=float, default=0.8, help="Opacidad 0.0-1.0")
    add_image.add_argument("--scale", type=float, default=0.15, help="Escala respecto al vídeo")

    set_music = sub.add_parser("set-music", help="Asocia música del catálogo")
    set_music.add_argument("project", help="Ruta del proyecto (.json)")
    set_music.add_argument("track_id", help="Id de la pista en el catálogo")
    set_music.add_argument("--volume", type=float, default=0.3, help="Volumen 0.0-1.0")

    render = sub.add_parser("render", help="Renderiza el proyecto a vídeo")
    render.add_argument("project", help="Ruta del proyecto (.json)")
    render.add_argument("-o", "--output", required=True, help="Vídeo de salida (.mp4/.mkv)")
    render.add_argument("--library", default=None, help="Directorio del catálogo de música")
    render.add_argument("--music", default=None, help="Ruta de música explícita")

    return parser


def _print_project(project: Project, path: str) -> None:
    console.print(f"[bold]{project.title}[/] ({path})")
    console.print(
        f"  {project.resolution[0]}x{project.resolution[1]} @ {project.fps} fps · "
        f"{len(project.clips)} clip(s) · {len(project.transitions)} transición(es) · "
        f"{len(project.text_overlays)} texto(s)"
    )
    table = Table(title="Clips")
    table.add_column("#", style="dim")
    table.add_column("Fichero")
    table.add_column("Inicio", justify="right")
    table.add_column("Duración", justify="right")
    table.add_column("Velocidad", justify="right")
    for index, clip in enumerate(project.clips):
        table.add_row(
            str(index),
            str(clip.file_path),
            f"{clip.start:.1f}s",
            f"{clip.duration or 'auto'}s",
            f"{clip.speed:.2f}",
        )
    console.print(table)


def run(args: argparse.Namespace) -> None:
    """Ejecuta el subcomando indicado."""
    editor = VideoEditor()

    if args.command == "new":
        project = editor.new_project(args.title, resolution=args.resolution, fps=args.fps)
        editor.save(project, args.project)
        console.print(f"[green]Proyecto creado:[/] {args.project}")
        _print_project(project, args.project)
        return

    project = VideoEditor.load(args.project)
    if args.command == "add-clip":
        editor.add_clip(
            project,
            args.video,
            start=args.start,
            duration=args.duration,
            volume=args.volume,
            speed=args.speed,
        )
    elif args.command == "add-transition":
        editor.add_transition(
            project, args.clip_index, type=args.type, duration=args.duration
        )
    elif args.command == "add-text":
        editor.add_text(
            project,
            args.text,
            position=args.position,
            font_size=args.font_size,
            color=args.color,
            start_time=args.start_time,
        )
    elif args.command == "add-image":
        editor.add_image(
            project,
            args.image,
            position=args.position,
            opacity=args.opacity,
            scale=args.scale,
        )
    elif args.command == "set-music":
        editor.set_music(project, args.track_id, volume=args.volume)
    elif args.command == "render":
        library = MusicLibrary(args.library) if args.library else None
        editor = VideoEditor(library=library)
        output = editor.render(project, args.output, music_path=args.music)
        console.print(f"[green]Vídeo renderizado:[/] {output}")
        return
    else:
        raise SystemExit(f"Comando desconocido: {args.command}")

    editor.save(project, args.project)
    console.print(f"[green]Proyecto actualizado:[/] {args.project}")
    _print_project(project, args.project)


def main() -> None:
    """Entry point de ``youber-edit``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    try:
        run(args)
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
