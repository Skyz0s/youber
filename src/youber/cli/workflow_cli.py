"""CLI del flujo completo de BARF: investigación de YouTube + edición de audio.

Ejecuta el pipeline de principio a fin, mostrando cada paso con ``rich``:

1. Investiga un canal público de YouTube (datos y vídeos recientes).
2. Extrae datos de los últimos vídeos (título, vistas, duración).
3. Genera insights de patrones de éxito (hashtags, títulos, duración).
4. Prepara un vídeo de ejemplo (local o generado con FFmpeg).
5. Añade música de fondo (local o generada con FFmpeg).
6. Exporta el resultado final (JSON/CSV/Markdown + vídeo MP4).

Con ``--lyrics-video`` se ejecuta el flujo **metadatos → letras → vídeo**:

1. Investiga el canal (metadatos de sus vídeos).
2. Extrae los vídeos recientes.
3. Insights de patrones de éxito.
4. Busca en las **letras** del catálogo la canción que hace falta para ese
   contenido (:mod:`youber.music.selector`).
5. Compone el **prompt** de producción y el guion (:mod:`youber.script.prompt`).
6. Genera el vídeo en local: clips de **Pexels/Pixabay** (B-roll) + render
   FFmpeg, y añade la canción seleccionada como banda sonora.

Uso:

.. code-block:: bash

    youber-workflow --channel @python -n 10 -o reports
    youber-workflow --demo -o reports            # sin red (canal sintético)
    youber-workflow --video mi_video.mp4 --music mi_musica.mp3 -o reports
    youber-workflow --lyrics-video --demo --topic "Mi vídeo" \
        --library music --lyrics-dir letras -o reports

Nota ética: usa solo **tu propia música** o contenido con licencia, y solo
vídeos propios o con permiso. El modo ``--demo`` genera vídeo y música
sintéticos con FFmpeg (sin dependencias externas ni derechos de autor).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from youber.audio._ffmpeg import run_command
from youber.audio.editor import add_background_music
from youber.console import ensure_utf8_console
from youber.music.library import MusicLibrary, find_track
from youber.music.selector import TrackMatch, select_best_track, theme_profile
from youber.research.channel_analyzer import ChannelAnalyzer
from youber.research.data_models import ChannelData, VideoData
from youber.research.exporters import (
    export_channel,
    export_videos,
    generate_channel_markdown,
)
from youber.research.patterns import channel_overview
from youber.script.builder import build_project
from youber.script.prompt import brief_to_script, build_video_brief
from youber.sync.pipeline import sync_video_with_track
from youber.sync.renderer import subtitle_style_preset
from youber.video.editor import VideoEditor

console = Console()

DEFAULT_CHANNEL = "@python"
DEFAULT_DURATION = 30


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de ``youber-workflow``."""
    parser = argparse.ArgumentParser(
        prog="youber-workflow",
        description="BARF: flujo completo de investigación de YouTube + edición de audio",
    )
    parser.add_argument(
        "--channel",
        default=DEFAULT_CHANNEL,
        help=f"Canal a investigar (por defecto: {DEFAULT_CHANNEL})",
    )
    parser.add_argument(
        "-n", "--max-videos", type=int, default=10, help="Vídeos a extraer"
    )
    parser.add_argument(
        "-o", "--output-dir", default="reports", help="Directorio de salida"
    )
    parser.add_argument("--video", default=None, help="Vídeo local (si no, se genera uno)")
    parser.add_argument("--music", default=None, help="Música local (si no, se genera una)")
    parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION,
        help=f"Duración del vídeo/música generados (por defecto: {DEFAULT_DURATION}s)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--api", action="store_true", help="Usar la YouTube Data API v3 (requiere YOUTUBE_API_KEY)"
    )
    mode.add_argument(
        "--html", action="store_true", help="Usar el parser de la página pública (por defecto)"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Canal sintético (sin red) + vídeo/música generados con FFmpeg",
    )
    parser.add_argument(
        "--track",
        default=None,
        help="Canción del catálogo youber.music (ID o texto): música y letra",
    )
    parser.add_argument(
        "--library",
        default="music",
        help="Directorio del catálogo de música (default: music)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Sincroniza la letra de la canción y quema subtítulos en el vídeo final",
    )
    parser.add_argument(
        "--lyrics",
        default=None,
        help="Fichero de letra .lrc/.txt/.srt (default: <canción>.lrc junto al audio)",
    )
    parser.add_argument(
        "--whisper",
        action="store_true",
        help="Transcribe con Whisper si no hay letra (requiere faster-whisper)",
    )
    parser.add_argument(
        "--model",
        default="small",
        help="Modelo Whisper para --whisper (default: small)",
    )
    parser.add_argument(
        "--style",
        default="clean",
        help="Estilo de subtítulos: clean|classic|box|minimal (default: clean)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Sube el vídeo final a YouTube (requiere auth: youber-upload auth)",
    )
    parser.add_argument(
        "--upload-title",
        default=None,
        help="Título para la subida (default: nombre del canal + resumen)",
    )
    parser.add_argument(
        "--privacy",
        choices=("private", "unlisted", "public"),
        default="private",
        help="Privacidad de la subida (default: private)",
    )
    # -- Flujo «metadatos → letras → vídeo» (--lyrics-video)
    parser.add_argument(
        "--lyrics-video",
        action="store_true",
        help="Flujo nuevo: metadatos → letras → prompt → vídeo local (clips "
        "Pexels/Pixabay) + canción elegida por su letra",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Tema del vídeo (--lyrics-video; por defecto: hashtags del canal)",
    )
    parser.add_argument(
        "--lyrics-dir",
        default=None,
        help="Directorio con las letras .txt para el análisis temático",
    )
    parser.add_argument(
        "--clips",
        nargs="+",
        default=[],
        help="Tus clips de vídeo (si no, se usan clips de stock)",
    )
    parser.add_argument(
        "--stock",
        choices=("auto", "pexels", "pixabay", "none"),
        default="auto",
        help="Banco de clips de B-roll para el vídeo local (default: auto)",
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Con --lyrics-video: solo brief + guion (sin renderizar el vídeo)",
    )
    return parser


# ---------------------------------------------------------------------------
# Canal sintético (modo demo, sin red)
# ---------------------------------------------------------------------------


def demo_channel() -> ChannelData:
    """Construye un canal sintético para demostrar el flujo sin red."""
    base_url = "https://www.youtube.com/@canaldemo"
    videos = [
        VideoData(
            title="Python 3.13: TOP 10 novedades que debes conocer",
            url=f"{base_url}/watch?id=1",
            video_id="demo1",
            views="1,2 M",
            likes="45 K",
            comments="1.023",
            duration="12:34",
            publish_date="2026-08-20",
            thumbnail_url=None,
            description="Repaso de las novedades de Python 3.13. #python #programacion",
            hashtags=["python", "programacion"],
            channel_name="Canal Demo (sintético)",
            channel_url=base_url,
        ),
        VideoData(
            title="¿Cómo funciona asyncio por dentro?",
            url=f"{base_url}/watch?id=2",
            video_id="demo2",
            views="890 K",
            likes="32 K",
            comments="540",
            duration="18:20",
            publish_date="2026-08-10",
            description="Guía visual de asyncio. #python #async #tutorial",
            hashtags=["python", "async", "tutorial"],
            channel_name="Canal Demo (sintético)",
            channel_url=base_url,
        ),
        VideoData(
            title="GUÍA COMPLETA de FastAPI para principiantes",
            url=f"{base_url}/watch?id=3",
            video_id="demo3",
            views="2,3 M",
            likes="98 K",
            comments="2.451",
            duration="45:10",
            publish_date="2026-07-28",
            description="Todo lo que necesitas para empezar con FastAPI. #fastapi #python",
            hashtags=["fastapi", "python"],
            channel_name="Canal Demo (sintético)",
            channel_url=base_url,
        ),
        VideoData(
            title="Streamlit vs Gradio: ¿cuál elegir?",
            url=f"{base_url}/watch?id=4",
            video_id="demo4",
            views="410 K",
            likes="15 K",
            comments="312",
            duration="9:45",
            publish_date="2026-07-15",
            description="Comparativa práctica. #python #streamlit #gradio",
            hashtags=["python", "streamlit", "gradio"],
            channel_name="Canal Demo (sintético)",
            channel_url=base_url,
        ),
    ]
    return ChannelData(
        name="Canal Demo (sintético)",
        url=base_url,
        handle="canaldemo",
        subscribers="12,3 K",
        total_views="1,5 M",
        videos=videos,
    )


# ---------------------------------------------------------------------------
# Generación de medios de prueba con FFmpeg (sin dependencias externas)
# ---------------------------------------------------------------------------


async def generate_test_video(path: str, duration: int = DEFAULT_DURATION) -> str:
    """Genera un vídeo de prueba (testsrc + tono) con FFmpeg.

    Incluye una pista de audio sintética para que la mezcla de música de
    fondo (``amix`` sobre ``[0:a]``) funcione sin ficheros externos.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        path,
    ]
    await run_command(cmd)
    return path


async def generate_test_music(path: str, duration: int = DEFAULT_DURATION) -> str:
    """Genera una pista de música de prueba (tono senoidal) con FFmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=523:duration={duration}",
        "-c:a",
        "libmp3lame",
        path,
    ]
    await run_command(cmd)
    return path


# ---------------------------------------------------------------------------
# Flujo completo
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    """Convierte un texto en un nombre de fichero seguro (ASCII)."""
    return (
        "".join(c if c.isalnum() and ord(c) < 128 else "-" for c in text)
        .strip("-")
        .lower()
        or "canal"
    )


def _print_videos_table(channel: ChannelData, max_videos: int) -> None:
    table = Table(title=f"Últimos {min(len(channel.videos), max_videos)} vídeos")
    table.add_column("Título", style="cyan")
    table.add_column("Vistas", justify="right")
    table.add_column("Duración", justify="right")
    for video in channel.videos[:max_videos]:
        table.add_row(video.title, video.views, video.duration or "-")
    console.print(table)


def _print_insights(insights: dict[str, Any]) -> None:
    top = insights["top_hashtags"][:5]
    if top:
        hashtags = ", ".join(f"#{entry['hashtag']} ({entry['count']})" for entry in top)
        console.print(f"🏷️  Hashtags más usados: [bold]{hashtags}[/]")
    patterns = insights["title_patterns"]
    console.print(
        "📈 Patrones de títulos: "
        f"[bold]{patterns['with_numbers']}[/] con números, "
        f"[bold]{patterns['with_uppercase_words']}[/] en MAYÚSCULAS, "
        f"[bold]{patterns['with_question']}[/] con pregunta, "
        f"[bold]{patterns['with_vs']}[/] con 'vs'"
    )
    duration = insights["duration_stats"]
    if duration["count"]:
        console.print(
            f"⏱️  Duración media: [bold]{duration['avg_seconds']}[/] s "
            f"(mín {duration['min_seconds']}, máx {duration['max_seconds']})"
        )
    views = insights["views_summary"]
    if views["avg"]:
        console.print(f"👁️  Vistas medias: [bold]{views['avg']:,.0f}[/] | máx: {views['max']:,.0f}")


async def run_workflow(
    channel_ref: str = DEFAULT_CHANNEL,
    max_videos: int = 10,
    output_dir: str = "reports",
    video_path: str | None = None,
    music_path: str | None = None,
    duration: int = DEFAULT_DURATION,
    mode: str = "html",
    demo: bool = False,
    track: str | None = None,
    library_dir: str = "music",
    sync_lyrics: bool = False,
    lyrics_file: str | None = None,
    whisper: bool = False,
    model: str = "small",
    style: str = "clean",
    upload: bool = False,
    upload_title: str | None = None,
    privacy: str = "private",
) -> dict[str, Any]:
    """Ejecuta el flujo completo de investigación + edición.

    Args:
        channel_ref: URL/handle del canal (ignorado si ``demo=True``).
        max_videos: Número máximo de vídeos a extraer.
        output_dir: Directorio donde guardar los resultados.
        video_path: Vídeo local; si es ``None`` se genera uno con FFmpeg.
        music_path: Música local; si es ``None`` se genera una con FFmpeg.
        duration: Duración (s) de los medios generados.
        mode: ``"html"`` o ``"api"`` para la investigación.
        demo: Usar canal sintético (sin red).

    Returns:
        Diccionario con las rutas de todos los artefactos generados.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Paso 1: investigación del canal
    console.print(Panel.fit("[bold cyan]Paso 1/6 · Investigación del canal[/]", border_style="cyan"))
    if demo:
        channel = demo_channel()
        console.print(f"📺 Canal sintético: [bold]{channel.name}[/] (sin red)")
    else:
        analyzer = ChannelAnalyzer()
        channel = await analyzer.analyze(channel_ref, max_videos=max_videos, mode=mode)
        console.print(f"📺 Canal: [bold]{channel.name}[/] · {channel.subscribers or '?'} suscriptores")

    # Paso 2: vídeos recientes
    console.print(Panel.fit("[bold cyan]Paso 2/6 · Vídeos recientes[/]", border_style="cyan"))
    _print_videos_table(channel, max_videos)

    # Paso 3: insights de patrones
    console.print(Panel.fit("[bold cyan]Paso 3/6 · Insights de patrones[/]", border_style="cyan"))
    insights = channel_overview(channel)
    _print_insights(insights)

    # Paso 4: vídeo de ejemplo
    console.print(Panel.fit("[bold cyan]Paso 4/6 · Vídeo de ejemplo[/]", border_style="cyan"))
    if video_path:
        video = Path(video_path)
        console.print(f"🎬 Vídeo local: [bold]{video}[/]")
    else:
        video = out / "test_video.mp4"
        console.print(f"🎬 Generando vídeo de prueba (FFmpeg): [bold]{video}[/]")
        await generate_test_video(str(video), duration)
    console.print(f"   Vídeo: [green]{video}[/]")

    # Paso 5: música de fondo (local > catálogo > generada)
    console.print(Panel.fit("[bold cyan]Paso 5/6 · Música de fondo[/]", border_style="cyan"))
    track_obj: Any = None
    if music_path:
        music = Path(music_path)
        console.print(f"🎵 Música local: [bold]{music}[/]")
    elif track:
        console.print(f"🔎 Buscando en el catálogo: [bold]{track}[/]")
        library = MusicLibrary(library_dir)
        try:
            track_obj = find_track(library, track)
        finally:
            library.close()
        if track_obj is None:
            raise RuntimeError(
                f"Pista no encontrada en el catálogo {library_dir!r}: {track!r}. "
                "Escanea antes con: youber-music --library <dir> scan"
            )
        music = Path(track_obj.file_path)
        artist = f" — {track_obj.artist}" if track_obj.artist else ""
        console.print(f"🎵 Del catálogo: [bold]{track_obj.title}{artist}[/]")
    else:
        music = out / "test_music.mp3"
        console.print(f"🎵 Generando música de prueba (FFmpeg): [bold]{music}[/]")
        await generate_test_music(str(music), duration)
    console.print(f"   Música: [green]{music}[/]")

    # Paso 6: edición y exportación
    console.print(Panel.fit("[bold cyan]Paso 6/6 · Edición y exportación[/]", border_style="cyan"))
    final_video = out / f"{_slug(channel.name)}_final.mp4"
    console.print(f"🎛️  Añadiendo música de fondo → [bold]{final_video}[/]")
    mix_kwargs: dict[str, Any] = {"volume": 0.3, "fade_in": 2, "fade_out": 2}
    if sync_lyrics and (track_obj is not None or music_path):
        # La canción es la banda sonora principal: la letra debe oírse.
        mix_kwargs = {
            "volume": 1.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
            "original_audio_volume": 0.0,
        }
    await add_background_music(str(video), str(music), str(final_video), **mix_kwargs)

    stem = _slug(channel.name)
    json_path = export_channel(channel, out / f"{stem}.json", fmt="json")
    csv_path = export_videos(channel.videos, out / f"{stem}_videos.csv", fmt="csv")
    md_path = out / f"{stem}.md"
    md_path.write_text(generate_channel_markdown(channel), encoding="utf-8")

    console.print(f"✅ Vídeo final: [bold green]{final_video}[/]")

    # Paso 7 (opcional): letras sincronizadas sobre el vídeo final
    upload_url: str | None = None
    if sync_lyrics:
        audio_source = (
            Path(track_obj.file_path)
            if track_obj is not None
            else (Path(music_path) if music_path else None)
        )
        if audio_source is None:
            raise RuntimeError(
                "--sync requiere --track (canción del catálogo) o --music"
            )
        console.print(
            Panel.fit(
                f"[bold cyan]Paso 7/7 · Letras sincronizadas (estilo '{style}')[/]",
                border_style="cyan",
            )
        )
        console.print(f"🎤 Sincronizando letra contra: [bold]{audio_source}[/]")
        sync_result = await sync_video_with_track(
            final_video,
            audio_source,
            output=final_video,
            lyrics_file=Path(lyrics_file) if lyrics_file else None,
            whisper=whisper,
            model=model,
            style=subtitle_style_preset(style),
            add_audio=False,  # la canción ya está mezclada en el vídeo
        )
        final_video = Path(sync_result.output_path)
        console.print(
            f"🎤 Subtítulos quemados (estilo {style}) → [bold green]{final_video}[/]"
        )

    # Paso 8 (opcional): subida a YouTube
    if upload:
        console.print(
            Panel.fit("[bold cyan]Paso 8/8 · Subida a YouTube[/]", border_style="cyan")
        )
        hashtags = [
            entry["hashtag"] for entry in (insights.get("top_hashtags") or [])
        ][:5]
        title = upload_title or f"{channel.name} · resumen automático (youber)"
        description = (
            f"Resumen del canal {channel.name} generado con youber-workflow.\n"
            f"{channel.url or ''}\n"
            + (("# " + " #".join(hashtags)) if hashtags else "")
        )
        upload_url = await _upload_video(
            final_video,
            title=title,
            description=description,
            tags=hashtags,
            privacy=privacy,
        )
        console.print(f"🚀 Subido: [bold]{upload_url}[/] (privacidad: {privacy})")

    console.print(f"📄 Exportados: {json_path.name}, {csv_path.name}, {md_path.name}")
    result: dict[str, Any] = {
        "channel": channel.name,
        "videos": len(channel.videos),
        "video": str(video),
        "music": str(music),
        "final_video": str(final_video),
        "json": str(json_path),
        "csv": str(csv_path),
        "markdown": str(md_path),
    }
    if sync_lyrics:
        result["synced"] = True
        result["subtitles_style"] = style
    if upload_url:
        result["upload_url"] = upload_url
    return result


# ---------------------------------------------------------------------------
# Flujo «metadatos → letras → prompt → vídeo local + canción» (--lyrics-video)
# ---------------------------------------------------------------------------


def _metadata_text(channel: ChannelData) -> str:
    """Texto con todos los metadatos del canal (títulos, descripciones, tags)."""
    parts: list[str] = [channel.name or ""]
    for video in channel.videos:
        parts.append(video.title or "")
        if video.description:
            parts.append(video.description)
        parts.extend(video.hashtags or [])
    return " ".join(part for part in parts if part)


def _default_topic(insights: dict[str, Any], channel: ChannelData) -> str:
    """Tema por defecto: los hashtags más usados del canal (o su nombre)."""
    hashtags = [
        str(entry["hashtag"])
        for entry in (insights.get("top_hashtags") or [])
        if entry.get("hashtag")
    ][:3]
    return ", ".join(hashtags) if hashtags else channel.name


async def run_lyrics_video(
    channel_ref: str = DEFAULT_CHANNEL,
    max_videos: int = 10,
    output_dir: str = "reports",
    topic: str | None = None,
    duration: int | None = None,
    mode: str = "html",
    demo: bool = False,
    library_dir: str = "music",
    lyrics_dir: str | None = None,
    clips: list[str] | None = None,
    stock: str = "auto",
    track: str | None = None,
    render: bool = True,
) -> dict[str, Any]:
    """Metadatos del canal → letras → prompt → vídeo local (Pexels) + canción.

    Args:
        channel_ref: URL/handle del canal (ignorado si ``demo=True``).
        max_videos: Número máximo de vídeos a extraer.
        output_dir: Directorio donde guardar los resultados.
        topic: Tema del vídeo (por defecto: hashtags del canal).
        duration: Duración objetivo en segundos (por defecto: media del canal).
        mode: ``"html"`` o ``"api"`` para la investigación.
        demo: Usar canal sintético (sin red).
        library_dir: Catálogo de música local (``youber.music``).
        lyrics_dir: Directorio con las letras ``.txt`` (opcional): si se da,
            el catálogo se escanea con ellas para poder elegir por letra.
        clips: Tus propios clips de vídeo (si no, se descargan de stock).
        stock: Banco de B-roll: ``auto``, ``pexels``, ``pixabay`` o ``none``.
        track: Fuerza una canción del catálogo (ID o texto) en vez de elegirla.
        render: Si ``False``, solo se generan brief + guion (sin vídeo).

    Returns:
        Diccionario con el prompt, el guion, la canción elegida y las rutas
        de los artefactos generados.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Paso 1: metadatos del canal
    console.print(Panel.fit("[bold cyan]Paso 1/6 · Metadatos del canal[/]", border_style="cyan"))
    if demo:
        channel = demo_channel()
        console.print(f"📺 Canal sintético: [bold]{channel.name}[/] (sin red)")
    else:
        channel = await ChannelAnalyzer().analyze(channel_ref, max_videos=max_videos, mode=mode)
        console.print(f"📺 Canal: [bold]{channel.name}[/] · {channel.subscribers or '?'} suscriptores")

    # Paso 2: vídeos recientes (metadatos)
    console.print(Panel.fit("[bold cyan]Paso 2/6 · Vídeos recientes[/]", border_style="cyan"))
    _print_videos_table(channel, max_videos)

    # Paso 3: insights de patrones
    console.print(Panel.fit("[bold cyan]Paso 3/6 · Insights de patrones[/]", border_style="cyan"))
    insights = channel_overview(channel)
    _print_insights(insights)
    clean_topic = topic or _default_topic(insights, channel)

    # Paso 4: la canción que hace falta, buscada en las letras
    console.print(
        Panel.fit("[bold cyan]Paso 4/6 · Canción (búsqueda en las letras)[/]", border_style="cyan")
    )
    metadata_text = _metadata_text(channel)
    profile = theme_profile(metadata_text)
    if profile.themes:
        themes = ", ".join(
            f"{theme} {weight:.2f}" for theme, weight in profile.themes.items()
        )
        console.print(f"🧠 Perfil del contenido: [bold]{themes}[/] · {profile.sentiment}")
    else:
        console.print("🧠 Perfil del contenido: sin temas claros en los metadatos")

    library = MusicLibrary(library_dir)
    try:
        if lyrics_dir:
            summary = await library.scan(lyrics_dir=lyrics_dir)
            console.print(
                f"📚 Catálogo {library_dir}: {summary.get('added', 0)} nuevas, "
                f"{summary.get('updated', 0)} actualizadas ({library.count()} pistas)"
            )
        if track:
            forced = find_track(library, track)
            if forced is None:
                raise RuntimeError(
                    f"Canción no encontrada en el catálogo {library_dir!r}: {track!r}. "
                    "Escanea antes con: youber-music --library <dir> scan --lyrics-dir <letras>"
                )
            match: TrackMatch | None = TrackMatch(
                track_id=forced.id,
                title=forced.title,
                artist=forced.artist,
                score=0.0,
                matched_themes=list(forced.lyrical_themes),
                reason="elegida a mano (--track)",
            )
        else:
            match = select_best_track(
                library.all(), profile, keywords=profile.top_words
            )
        if match is not None:
            artist = f" — {match.artist}" if match.artist else ""
            console.print(
                f"🎵 Canción elegida: [bold]{match.title}{artist}[/] (score {match.score:g})"
            )
            console.print(f"   Motivo: {match.reason}")
        else:
            console.print(
                "🎵 Sin catálogo de música: el vídeo se renderiza sin banda sonora "
                "(escanea con: youber-music scan --lyrics-dir <letras>)"
            )

        # Paso 5: prompt de producción + guion
        console.print(
            Panel.fit("[bold cyan]Paso 5/6 · Prompt y guion[/]", border_style="cyan")
        )
        brief = build_video_brief(
            insights,
            topic=clean_topic,
            duration=float(duration) if duration else None,
            profile=profile,
            metadata_text=metadata_text,
            track_match=match,
        )
        script = brief_to_script(brief, insights)
        console.print(brief.prompt)
        console.print(
            f"🎬 Guion: {len(script.scenes)} escenas · {script.total_duration:g} s · "
            f"mood [bold]{script.music_mood.value if script.music_mood else '-'}[/]"
        )

        # Paso 6: vídeo local (clips de stock) + canción
        console.print(
            Panel.fit("[bold cyan]Paso 6/6 · Vídeo local + audio[/]", border_style="cyan")
        )
        clip_paths = [Path(clip) for clip in (clips or [])]
        if not clip_paths:
            from youber.video.stock import available as stock_available
            from youber.video.stock import fetch_clips_for_scenes

            banks = stock_available()
            if stock != "none" and any(banks.values()):
                scenes = [scene.model_dump() for scene in script.scenes]
                avg_scene = script.total_duration / max(1, len(scenes))
                per_scene = max(1, min(4, max(1, round(avg_scene / 6))))
                console.print(
                    f"⬇️  Buscando clips de B-roll ({stock}) por escena..."
                )
                fetched = await fetch_clips_for_scenes(
                    scenes,
                    out / "clips",
                    bank=stock,
                    per_scene=per_scene,
                )
                clip_paths = [path for paths in fetched.values() for path in paths]
            if not clip_paths:
                console.print(
                    "⚠️  Sin clips ni key de stock: se genera un clip sintético "
                    "(FFmpeg) para que el render funcione offline"
                )
                fallback = out / "clip_base.mp4"
                await generate_test_video(str(fallback), duration or DEFAULT_DURATION)
                clip_paths = [fallback]
        console.print(f"🎞️  Clips: [bold]{len(clip_paths)}[/]")

        final_video: Path | None = None
        if render:
            editor = VideoEditor(library=library)
            project = build_project(
                script,
                clips=clip_paths,
                library=library,
                editor=editor,
                title=brief.topic,
                music_track_id=match.track_id if match else None,
            )
            final_video = out / f"{_slug(brief.topic)}_final.mp4"
            console.print(f"🎛️  Renderizando (FFmpeg) → [bold]{final_video}[/]")
            await editor.render(project, final_video)
            console.print(f"✅ Vídeo final + canción: [bold green]{final_video}[/]")
        else:
            console.print("⏭️  Render omitido (--no-render)")

        # Exportación
        brief_json = export_channel(channel, out / f"{_slug(channel.name)}.json", fmt="json")
        script_path = out / f"{_slug(brief.topic)}_guion.json"
        script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
        brief_path = out / f"{_slug(brief.topic)}_brief.json"
        brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
        md_path = out / f"{_slug(channel.name)}.md"
        md_path.write_text(generate_channel_markdown(channel), encoding="utf-8")
        console.print(
            f"📄 Exportados: {brief_path.name}, {script_path.name}, {md_path.name}"
        )
    finally:
        library.close()

    return {
        "channel": channel.name,
        "videos": len(channel.videos),
        "topic": brief.topic,
        "themes": profile.themes,
        "sentiment": profile.sentiment,
        "track": (
            {
                "id": match.track_id,
                "title": match.title,
                "artist": match.artist,
                "score": match.score,
                "reason": match.reason,
            }
            if match is not None
            else None
        ),
        "prompt": brief.prompt,
        "script": str(script_path),
        "brief": str(brief_path),
        "json": str(brief_json),
        "markdown": str(md_path),
        "clips": [str(clip) for clip in clip_paths],
        "final_video": str(final_video) if final_video else None,
    }


async def _upload_video(
    video_path: str | Path,
    *,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "private",
) -> str:
    """Sube un vídeo a YouTube con la API oficial (requiere auth previa).

    Raises:
        RuntimeError: si no hay credenciales (ejecuta ``youber-upload auth``).
    """
    from youber.upload.auth import YouTubeAuth
    from youber.upload.metadata import PrivacyStatus, VideoMetadata
    from youber.upload.youtube import YouTubeUploader

    auth = YouTubeAuth()
    if not auth.has_token():
        raise RuntimeError(
            "No hay credenciales de YouTube. Ejecuta primero: youber-upload auth"
        )
    metadata = VideoMetadata(
        title=title,
        description=description,
        tags=tags or [],
        privacy_status=PrivacyStatus(privacy),
    )
    resource = await YouTubeUploader(auth).upload_video(video_path, metadata)
    video_id = (resource or {}).get("id")
    return YouTubeUploader.get_video_url(video_id) if video_id else "(sin id)"


def main() -> None:
    """Entry point de ``youber-workflow``."""
    ensure_utf8_console()
    args = build_parser().parse_args()
    try:
        if args.lyrics_video:
            result = asyncio.run(
                run_lyrics_video(
                    channel_ref=args.channel,
                    max_videos=args.max_videos,
                    output_dir=args.output_dir,
                    topic=args.topic,
                    duration=args.duration if args.duration != DEFAULT_DURATION else None,
                    mode="api" if args.api else "html",
                    demo=args.demo,
                    library_dir=args.library,
                    lyrics_dir=args.lyrics_dir,
                    clips=args.clips,
                    stock=args.stock,
                    track=args.track,
                    render=not args.no_render,
                )
            )
            console.print(
                f"[bold green]✔ Flujo completado: {result['topic']}[/]"
            )
            return
        asyncio.run(
            run_workflow(
                channel_ref=args.channel,
                max_videos=args.max_videos,
                output_dir=args.output_dir,
                video_path=args.video,
                music_path=args.music,
                duration=args.duration,
                mode="api" if args.api else "html",
                demo=args.demo,
                track=args.track,
                library_dir=args.library,
                sync_lyrics=args.sync,
                lyrics_file=args.lyrics,
                whisper=args.whisper,
                model=args.model,
                style=args.style,
                upload=args.upload,
                upload_title=args.upload_title,
                privacy=args.privacy,
            )
        )
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
