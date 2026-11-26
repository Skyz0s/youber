"""CLI ``youber-tiktok``: publica vídeos propios con la Content Posting API.

Comandos: ``auth``, ``whoami``, ``upload`` y ``status``.

Ejemplos:

.. code-block:: bash

    youber-tiktok auth --redirect-uri https://localhost:8765/callback
    youber-tiktok auth --exchange <code o URL de vuelta>
    youber-tiktok whoami
    youber-tiktok upload short.mp4 --title "Da un paso hacia mi #Shorts"
    youber-tiktok upload video.mp4 --mode direct --title "..." --privacy PUBLIC_TO_EVERYONE
    youber-tiktok status v_pub_file~v2-1.1234
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from youber.console import ensure_utf8_console
from youber.upload.tiktok import (
    PrivacyLevel,
    TikTokAuth,
    TikTokError,
    TikTokPostInfo,
    TikTokUploader,
)

console = Console()


def _privacy(value: str) -> PrivacyLevel:
    """Convierte el texto del usuario en un :class:`PrivacyLevel`."""
    raw = value.strip().upper()
    aliases = {
        "PUBLIC": "PUBLIC_TO_EVERYONE",
        "PUBLIC_TO_EVERYONE": "PUBLIC_TO_EVERYONE",
        "FRIENDS": "MUTUAL_FOLLOW_FRIENDS",
        "MUTUAL_FOLLOW_FRIENDS": "MUTUAL_FOLLOW_FRIENDS",
        "PRIVATE": "SELF_ONLY",
        "SELF_ONLY": "SELF_ONLY",
    }
    target = aliases.get(raw)
    if target is None:
        valid = ", ".join(p.value for p in PrivacyLevel)
        raise argparse.ArgumentTypeError(f"Privacidad desconocida: {value!r}. Válidas: {valid}")
    return PrivacyLevel(target)


def extract_code(value: str) -> str:
    """Acepta un ``code`` suelto o la URL completa de redirección."""
    text = value.strip()
    if text.startswith("http://") or text.startswith("https://"):
        params = parse_qs(urlparse(text).query)
        if "error" in params:
            raise ValueError(f"TikTok devolvió un error: {params['error'][0]}")
        codes = params.get("code")
        if not codes:
            raise ValueError("La URL no trae el parámetro 'code'")
        return codes[0]
    return text


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-tiktok``."""
    parser = argparse.ArgumentParser(
        prog="youber-tiktok",
        description="BARF: publica tus vídeos en TikTok con la API oficial",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="Autoriza la app (OAuth 2.0)")
    auth.add_argument("--client-key", default=None, help="Client key (o TIKTOK_CLIENT_KEY)")
    auth.add_argument(
        "--client-secret", default=None, help="Client secret (o TIKTOK_CLIENT_SECRET)"
    )
    auth.add_argument(
        "--redirect-uri",
        default=None,
        help="URI de redirección registrada en la app",
    )
    auth.add_argument(
        "--exchange",
        default=None,
        help="Código (o URL de vuelta) para canjear por tokens",
    )

    sub.add_parser("whoami", help="Muestra el creador autorizado y sus límites")

    upload = sub.add_parser("upload", help="Sube un vídeo")
    upload.add_argument("video", help="Ruta del vídeo (MP4/MOV)")
    upload.add_argument(
        "--mode",
        choices=("inbox", "direct"),
        default="inbox",
        help="inbox = borrador en la app (sin auditoría); direct = publicación",
    )
    upload.add_argument("--title", default="", help="Título/caption (solo modo direct)")
    upload.add_argument(
        "--privacy",
        type=_privacy,
        default=PrivacyLevel.SELF_ONLY,
        help="Privacidad (solo modo direct): public/friends/private",
    )
    upload.add_argument("--no-comments", action="store_true", help="Desactiva comentarios")
    upload.add_argument("--no-duet", action="store_true", help="Desactiva duetos")
    upload.add_argument("--no-stitch", action="store_true", help="Desactiva stitch")
    upload.add_argument("--cover-ms", type=int, default=None, help="Fotograma de portada (ms)")
    upload.add_argument("--chunk-size", type=int, default=None, help="Tamaño de chunk en bytes")
    upload.add_argument("--no-wait", action="store_true", help="No esperar al estado final")

    status = sub.add_parser("status", help="Consulta el estado de una publicación")
    status.add_argument("publish_id", help="publish_id devuelto por upload")

    return parser


def run(args: argparse.Namespace) -> None:
    """Ejecuta el subcomando pedido."""
    auth = TikTokAuth(
        client_key=getattr(args, "client_key", None),
        client_secret=getattr(args, "client_secret", None),
        redirect_uri=getattr(args, "redirect_uri", None),
    )

    if args.command == "auth":
        _run_auth(auth, args)
        return

    if not auth.has_token():
        raise TikTokError("No hay token. Ejecuta primero: youber-tiktok auth")

    if args.command == "whoami":
        info = asyncio.run(TikTokUploader(auth).query_creator_info())
        _print_creator(info)
        return

    if args.command == "status":
        data = asyncio.run(TikTokUploader(auth).get_status(args.publish_id))
        table = Table(title=f"Estado de {args.publish_id}")
        table.add_column("campo")
        table.add_column("valor")
        for key, value in data.items():
            table.add_row(str(key), str(value))
        console.print(table)
        return

    if args.command == "upload":
        post_info = None
        if args.mode == "direct":
            post_info = TikTokPostInfo(
                title=args.title,
                privacy_level=args.privacy,
                disable_comment=args.no_comments,
                disable_duet=args.no_duet,
                disable_stitch=args.no_stitch,
                video_cover_timestamp_ms=args.cover_ms,
            )
        result = asyncio.run(
            TikTokUploader(auth).publish(
                Path(args.video),
                post_info,
                direct=args.mode == "direct",
                wait=not args.no_wait,
                chunk_size=args.chunk_size,
            )
        )
        console.print(
            Panel.fit(
                f"publish_id: {result['publish_id']}\n"
                f"estado: {result['status']}\n"
                f"bytes subidos: {result['uploaded_bytes']}\n"
                + (
                    "Termina la publicación en la app de TikTok (bandeja de entrada)."
                    if args.mode == "inbox"
                    else "Publicación enviada a TikTok."
                ),
                title="TikTok",
            )
        )
        return

    raise TikTokError(f"Comando no soportado: {args.command}")


def _run_auth(auth: TikTokAuth, args: argparse.Namespace) -> None:
    """Flujo manual: imprime la URL, canjea el código y guarda el token."""
    if args.exchange:
        code = extract_code(args.exchange)
        tokens = asyncio.run(auth.exchange_code(code))
        console.print(
            Panel.fit(
                f"open_id: {tokens.get('open_id')}\nscope: {tokens.get('scope')}",
                title="TikTok autorizado",
            )
        )
        return

    url = auth.get_authorization_url(args.redirect_uri)
    console.print(
        Panel.fit(
            "1. Abre esta URL y autoriza la app:\n\n"
            f"{url}\n\n"
            "2. Copia la URL de vuelta (o solo el parámetro 'code') y ejecuta:\n"
            "   youber-tiktok auth --exchange '<URL o code>'",
            title="Autorización de TikTok",
        )
    )


def _print_creator(info: dict) -> None:
    """Muestra la información del creador en una tabla."""
    table = Table(title="Creador de TikTok")
    table.add_column("campo")
    table.add_column("valor")
    for key in (
        "creator_username",
        "creator_nickname",
        "privacy_level_options",
        "comment_disabled",
        "duet_disabled",
        "stitch_disabled",
        "max_video_post_duration_sec",
    ):
        if key in info:
            table.add_row(key, str(info[key]))
    console.print(table)


def main() -> None:
    """Punto de entrada de ``youber-tiktok``."""
    ensure_utf8_console()
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
    except (TikTokError, ValueError, FileNotFoundError) as exc:
        console.print(Panel.fit(str(exc), title="[red]Error[/red]"))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
