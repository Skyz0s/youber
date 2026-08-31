"""CLI ``youber-upload``: sube vídeos a YouTube (contenido propio).

Comandos: ``auth``, ``upload``, ``schedule`` y ``status``.

Ejemplos:

.. code-block:: bash

    youber-upload auth
    youber-upload video.mp4 --title "Mi Video" --description "..." --tags "python,tutorial" --privacy public
    youber-upload schedule video.mp4 --title "..." --publish-at "2026-09-15 10:00:00"
    youber-upload status <video_id>
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from youber.console import ensure_utf8_console
from youber.upload.auth import YouTubeAuth
from youber.upload.metadata import PrivacyStatus, VideoMetadata
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
