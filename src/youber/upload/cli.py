"""CLI ``youber-upload``: sube vídeos a YouTube (contenido propio).

Comandos: ``auth``, ``upload``, ``schedule``, ``status``, ``thumbnail`` y
``captions``.

Ejemplos:

.. code-block:: bash

    youber-upload auth
    youber-upload video.mp4 --title "Mi Video" --description "..." --tags "python,tutorial" --privacy public
    youber-upload schedule video.mp4 --title "..." --publish-at "2026-09-15 10:00:00"
    youber-upload status <video_id>
    youber-upload thumbnail <video_id> --video video.mp4 --text "Mi título"
    youber-upload captions <video_id> letra.srt --language es
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.upload.auth import YouTubeAuth
from youber.upload.metadata import PrivacyStatus, VideoMetadata
from youber.upload.thumbnail import make_thumbnail
from youber.upload.youtube import YouTubeUploader

console = Console()


def _privacy(value: str) -> PrivacyStatus:
    """Convierte el texto del usuario en un :class:`PrivacyStatus`."""
    try:
        return PrivacyStatus(value.strip().lower())
    except ValueError as exc:
        valid = ", ".join(p.value for p in PrivacyStatus)
        raise argparse.ArgumentTypeError(
            f"Privacidad desconocida: {value!r}. Válidas: {valid}"
        ) from exc


def _publish_at(value: str) -> datetime:
    """Convierte ``"2026-09-15 10:00:00"`` en un datetime local."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace(" ", "T"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Fecha inválida: {value!r}. Usa formato 'YYYY-MM-DD HH:MM:SS'"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-upload``."""
    parser = argparse.ArgumentParser(
        prog="youber-upload",
        description="BARF: sube tus vídeos a YouTube (contenido propio, OAuth 2.0)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="Autentica con Google (OAuth 2.0)")
    auth.add_argument("--client-id", default=None, help="OAuth Client ID (o GOOGLE_CLIENT_ID)")
    auth.add_argument("--client-secret", default=None, help="OAuth Client Secret (o GOOGLE_CLIENT_SECRET)")

    upload = sub.add_parser("upload", help="Sube un vídeo a YouTube")
    upload.add_argument("video", help="Ruta del vídeo (MP4/MKV)")
    upload.add_argument("--title", required=True, help="Título del vídeo")
    upload.add_argument("--description", default="", help="Descripción")
    upload.add_argument("--tags", default="", help="Etiquetas separadas por comas")
    upload.add_argument("--category", default="22", help="Categoría de YouTube (id)")
    upload.add_argument("--privacy", type=_privacy, default=PrivacyStatus.PRIVATE, help="public/unlisted/private")

    schedule = sub.add_parser("schedule", help="Sube y programa la publicación")
    schedule.add_argument("video", help="Ruta del vídeo (MP4/MKV)")
    schedule.add_argument("--title", required=True, help="Título del vídeo")
    schedule.add_argument("--description", default="", help="Descripción")
    schedule.add_argument("--tags", default="", help="Etiquetas separadas por comas")
    schedule.add_argument("--category", default="22", help="Categoría de YouTube (id)")
    schedule.add_argument(
        "--publish-at", type=_publish_at, required=True,
        help="Fecha de publicación 'YYYY-MM-DD HH:MM:SS' (se fuerza privado)",
    )

    status = sub.add_parser("status", help="Consulta el estado de un vídeo")
    status.add_argument("video_id", help="Id del vídeo en YouTube")

    thumbnail = sub.add_parser(
        "thumbnail", help="Genera y sube la miniatura de un vídeo"
    )
    thumbnail.add_argument("video_id", help="Id del vídeo en YouTube")
    source = thumbnail.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="Imagen ya hecha (JPEG/PNG)")
    source.add_argument(
        "--video",
        help="Vídeo del que extraer el fotograma (el instante con más energía)",
    )
    thumbnail.add_argument(
        "--text", default=None, help="Título a rotular sobre el fotograma"
    )
    thumbnail.add_argument(
        "--time", type=float, default=None, help="Segundo concreto del fotograma"
    )
    thumbnail.add_argument("-o", "--output", default=None, help="Ruta del JPEG generado")

    captions = sub.add_parser("captions", help="Sube o lista pistas de subtítulos")
    captions.add_argument("video_id", help="Id del vídeo en YouTube")
    captions.add_argument(
        "caption", nargs="?", help="Fichero de subtítulos (.srt) a subir"
    )
    captions.add_argument(
        "--language", default="es", help="Idioma ISO 639-1 de la pista (default: es)"
    )
    captions.add_argument("--name", default=None, help="Nombre visible de la pista")
    captions.add_argument(
        "--draft", action="store_true", help="Subir la pista como borrador"
    )
    captions.add_argument(
        "--list", action="store_true", dest="list_captions",
        help="Lista las pistas existentes en vez de subir una",
    )
    captions.add_argument(
        "--delete", default=None, metavar="CAPTION_ID", help="Borra una pista por id"
    )

    return parser


def _uploader(auth: YouTubeAuth) -> YouTubeUploader:
    return YouTubeUploader(auth)


async def _run_upload(
    video_path: str,
    metadata: VideoMetadata,
    auth: YouTubeAuth,
) -> None:
    uploader = _uploader(auth)
    resource = await uploader.upload_video(video_path, metadata)
    video_id = str(resource.get("id") or "")
    console.print(
        Panel.fit(
            f"[bold green]Vídeo subido[/]\n"
            f"id: {video_id}\n"
            f"URL: {YouTubeUploader.get_video_url(video_id)}\n"
            f"privacidad: {metadata.privacy_status.value}"
            + (f"\npublicación programada: {metadata.publish_at}" if metadata.publish_at else ""),
            border_style="green",
        )
    )


async def _run_status(video_id: str, auth: YouTubeAuth) -> None:
    item = await _uploader(auth).check_status(video_id)
    status = item.get("status", {})
    snippet = item.get("snippet", {})
    console.print(
        Panel.fit(
            f"[bold]{snippet.get('title', video_id)}[/]\n"
            f"privacidad: {status.get('privacyStatus', '?')}\n"
            f"estado: {status.get('uploadStatus', '?')}\n"
            f"URL: {YouTubeUploader.get_video_url(video_id)}",
            border_style="cyan",
        )
    )


async def _run_thumbnail(
    video_id: str,
    *,
    image: str | None,
    video: str | None,
    text: str | None,
    timestamp: float | None,
    output: str | None,
    auth: YouTubeAuth,
) -> None:
    """Genera (si hace falta) la miniatura y la fija en el vídeo."""
    if image is not None:
        image_path = Path(image)
        origin = "imagen propia"
    else:
        assert video is not None  # lo garantiza el grupo mutuamente excluyente
        result = await make_thumbnail(
            video, output=output, timestamp=timestamp, text=text
        )
        image_path = result.path
        origin = f"fotograma de {Path(video).name} a {result.timestamp:.2f} s"

    await _uploader(auth).set_thumbnail(video_id, image_path)
    console.print(
        Panel.fit(
            f"[bold green]Miniatura fijada[/]\n"
            f"vídeo: {video_id}\n"
            f"imagen: {image_path} ({origin})"
            + (f"\ntítulo: {text}" if text else ""),
            border_style="green",
        )
    )


async def _run_captions(
    video_id: str,
    *,
    caption: str | None,
    language: str,
    name: str | None,
    is_draft: bool,
    list_captions: bool,
    delete: str | None,
    auth: YouTubeAuth,
) -> None:
    """Sube, lista o borra pistas de subtítulos."""
    uploader = _uploader(auth)
    if delete:
        await uploader.delete_caption(delete)
        console.print(f"[green]Pista borrada: {delete}[/]")
        return
    if list_captions or not caption:
        tracks = await uploader.list_captions(video_id)
        if not tracks:
            console.print(f"[yellow]Sin pistas de subtítulos en {video_id}[/]")
            return
        table = Table(title=f"Pistas de {video_id}")
        table.add_column("id")
        table.add_column("idioma")
        table.add_column("nombre")
        table.add_column("borrador")
        for track in tracks:
            snippet = track.get("snippet", {})
            table.add_row(
                str(track.get("id", "?")),
                str(snippet.get("language", "?")),
                str(snippet.get("name", "")),
                "sí" if snippet.get("isDraft") else "no",
            )
        console.print(table)
        return

    resource = await uploader.upload_caption(
        video_id,
        caption,
        language=language,
        name=name,
        is_draft=is_draft,
    )
    console.print(
        Panel.fit(
            f"[bold green]Pista de subtítulos subida[/]\n"
            f"vídeo: {video_id}\n"
            f"id: {resource.get('id', '?')} · idioma: {language}"
            + (" · borrador" if is_draft else ""),
            border_style="green",
        )
    )


def run(args: argparse.Namespace) -> None:
    """Ejecuta el subcomando indicado."""
    if args.command == "auth":
        auth = YouTubeAuth(client_id=args.client_id, client_secret=args.client_secret)
        url = auth.get_authorization_url()
        console.print(
            Panel.fit(
                "[bold]Paso 1[/] Abre esta URL en el navegador y autoriza:\n"
                f"[cyan]{url}[/]\n\n"
                "[bold]Paso 2[/] Pega aquí el código de autorización:",
                border_style="magenta",
            )
        )
        code = input("Código: ").strip()
        tokens = asyncio.run(auth.exchange_code(code))
        console.print(
            f"[green]Autenticado. Token guardado en {auth.token_file}[/] "
            f"(expira: {tokens['expires_at']})"
        )
        return

    auth = YouTubeAuth()
    if args.command == "upload":
        metadata = VideoMetadata(
            title=args.title,
            description=args.description,
            tags=args.tags,
            category_id=args.category,
            privacy_status=args.privacy,
        )
        asyncio.run(_run_upload(args.video, metadata, auth))
    elif args.command == "schedule":
        metadata = VideoMetadata(
            title=args.title,
            description=args.description,
            tags=args.tags,
            category_id=args.category,
            publish_at=args.publish_at,
        )
        asyncio.run(_run_upload(args.video, metadata, auth))
    elif args.command == "status":
        asyncio.run(_run_status(args.video_id, auth))
    elif args.command == "thumbnail":
        asyncio.run(
            _run_thumbnail(
                args.video_id,
                image=args.image,
                video=args.video,
                text=args.text,
                timestamp=args.time,
                output=args.output,
                auth=auth,
            )
        )
    elif args.command == "captions":
        asyncio.run(
            _run_captions(
                args.video_id,
                caption=args.caption,
                language=args.language,
                name=args.name,
                is_draft=args.draft,
                list_captions=args.list_captions,
                delete=args.delete,
                auth=auth,
            )
        )
    else:
        raise SystemExit(f"Comando desconocido: {args.command}")


def main() -> None:
    """Entry point de ``youber-upload``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    try:
        run(args)
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
