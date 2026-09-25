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

from youber.audio._ffmpeg import probe_duration, run_command
from youber.audio.editor import add_background_music
from youber.console import ensure_utf8_console
from youber.journal import (
    DecisionJournal,
    DecisionRecord,
    record_from_lyrics_run,
    record_from_workflow_run,
)
from youber.music.library import MusicLibrary, find_track
from youber.music.models import Track
from youber.music.selector import TrackMatch, select_tracks, theme_profile
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
        default=None,
        help=(
            "Duración del vídeo en segundos. Con --lyrics-video, si no se indica, el "
            "vídeo dura lo que la canción elegida (así no hay desajustes de audio); el "
            f"flujo clásico usa {DEFAULT_DURATION}s para los medios de prueba."
        ),
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
    parser.add_argument(
        "--music-volume",
        type=float,
        default=1.0,
        help="Con --lyrics-video: volumen de la canción en el vídeo (0..1, default: 1.0)",
    )
    parser.add_argument(
        "--clip-audio",
        action="store_true",
        help=(
            "Con --lyrics-video: conservar el audio original de los clips "
            "(por defecto se silencia: la canción es la banda sonora)"
        ),
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Con --lyrics-video: generar además una versión ligera del vídeo "
            "(480p, audio estéreo 128 kbps) lista para compartir"
        ),
    )
    parser.add_argument(
        "--visuals",
        choices=("off", "ai"),
        default="off",
        help=(
            "Con --lyrics-video: 'ai' crea los planos de cero (IA local) en vez de "
            "montar clips propios o de stock"
        ),
    )
    parser.add_argument(
        "--ai-model",
        default=None,
        help=(
            "Modelo de imagen para --visuals ai (default: stabilityai/sdxl-turbo; "
            "'stub' genera degradados sin GPU)"
        ),
    )
    parser.add_argument(
        "--ai-steps", type=int, default=2, help="Pasos de inferencia del modelo (default: 2)"
    )
    parser.add_argument(
        "--ai-shots", type=int, default=None, help="Número de planos (default: según duración)"
    )
    parser.add_argument(
        "--ai-seed", type=int, default=1234, help="Semilla base de los planos (default: 1234)"
    )
    parser.add_argument(
        "--ai-aspect",
        choices=("16:9", "9:16", "1:1"),
        default="16:9",
        help="Formato del vídeo con IA (default: 16:9)",
    )
    parser.add_argument(
        "--ai-style",
        choices=("auto", "cinematic", "dreamy", "dark", "vibrant", "minimal"),
        default="auto",
        help=(
            "Estilo visual de los planos (default: auto → lo eligen el audio de la "
            "canción y los metadatos; fíjalo solo si quieres forzar uno)"
        ),
    )
    parser.add_argument(
        "--ai-texts",
        action="store_true",
        help="Con --visuals ai: superponer los textos del guion sobre los planos",
    )
    parser.add_argument(
        "--no-texts",
        action="store_true",
        help=(
            "Con --lyrics-video: no superponer los textos del guion sobre el "
            "vídeo (clips limpios + música: los textos de escena son "
            "instrucciones de montaje, no copy para el espectador)"
        ),
    )
    parser.add_argument(
        "--short",
        nargs="?",
        type=float,
        const=75.0,
        default=None,
        metavar="SEGUNDOS",
        help=(
            "Con --visuals ai: generar además el corte vertical (9:16) del trozo con "
            "más energía de la canción (default: 75 s)"
        ),
    )
    parser.add_argument(
        "--journal-db",
        default=None,
        help="Base de datos del registro de decisiones (default: ~/.youber/journal.db)",
    )
    parser.add_argument(
        "--no-journal",
        action="store_true",
        help="No registrar la decisión en el decision journal",
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


async def _video_duration(path: str | Path | None) -> float | None:
    """Duración del vídeo final (best effort: ``None`` si no se puede medir).

    Se usa para el registro de decisiones; un fallo al medir nunca debe
    tumbar un flujo que ya ha renderizado el vídeo.
    """
    if not path:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    try:
        return await probe_duration(target)
    except Exception:  # la journalización es best-effort
        return None


def _journal_record(record: DecisionRecord, journal_db: str | None) -> str:
    """Guarda una decisión en el journal y lo anuncia por consola."""
    store = DecisionJournal(journal_db)
    try:
        store.record(record)
    finally:
        store.close()
    console.print(f"🗂️  Decisión registrada: [bold]{record.id}[/]")
    return record.id


def _project_duration(project: Any) -> float | None:
    """Duración del montaje según el proyecto (sin renderizar).

    Las transiciones se solapan (``xfade``), así que acortan el total: el
    montaje dura la suma de los clips menos la suma de las transiciones. Si
    algún clip no tiene duración explícita, devuelve ``None`` (habría que
    sondear el fichero).
    """
    if any(clip.duration is None for clip in project.clips):
        return None
    clips = sum(float(clip.duration or 0.0) for clip in project.clips)
    transitions = sum(float(transition.duration) for transition in project.transitions)
    return round(clips - transitions, 3)


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
    journal: bool = True,
    journal_db: str | None = None,
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

    decision_id: str | None = None
    if journal:
        journal_profile = theme_profile(_metadata_text(channel))
        decision_id = _journal_record(
            record_from_workflow_run(
                channel=channel,
                insights=insights,
                profile=journal_profile,
                track=track_obj,
                target_duration=float(duration),
                artifacts={
                    "json": str(json_path),
                    "csv": str(csv_path),
                    "markdown": str(md_path),
                },
                video_path=final_video,
                video_duration=await _video_duration(final_video),
                clip_source="local" if video_path else "synthetic",
                mode="demo" if demo else mode,
                upload_url=upload_url,
                upload_title=upload_title,
                privacy=privacy if upload else None,
                metadata_text=_metadata_text(channel),
            ),
            journal_db,
        )

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
        "decision_id": decision_id,
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


async def _beat_grid(song: str | Path) -> Any:
    """Rejilla de pulsos de la canción, si el pulso es lo bastante firme.

    Si la medición falla o el pulso es flojo devuelve ``None``: en ese caso el
    montaje se reparte de forma uniforme (mejor que cortar a un pulso inventado).
    """
    from youber.visuals.tempo import detect_grid

    try:
        grid = await detect_grid(song)
    except (RuntimeError, FileNotFoundError, OSError):  # pragma: no cover - FFmpeg
        return None
    return grid if grid.reliable() else None


async def _visual_signals(
    *,
    track_id: str | None = None,
    song: str | Path | None = None,
    themes: dict[str, float] | None = None,
    sentiment: str | None = None,
    metadata_text: str = "",
    mood: str | None = None,
) -> Any:
    """Señales de audio + metadatos para elegir el estilo y el ritmo de los planos.

    El perfil de audio sale del almacén de *audio features* del catálogo (si
    la pista está enriquecida); si hay fichero local, el **tempo** se mide por
    onsets y la sonoridad con FFmpeg; los temas y el sentimiento, de los
    metadatos del canal. Todo offline: si falta algo, se usan señales neutras.
    """
    from youber.visuals.selector import build_signals
    from youber.visuals.short import loudness_profile
    from youber.visuals.tempo import detect_tempo

    audio_profile = None
    if track_id:
        from youber.music.audio_features import AudioFeatureStore

        try:
            audio_profile = AudioFeatureStore().get(track_id)
        except (OSError, ValueError):  # pragma: no cover - almacén ilegible
            audio_profile = None

    energies: list[float] | None = None
    tempo_bpm: float | None = None
    if song:
        try:
            energies = await loudness_profile(song)
        except (RuntimeError, FileNotFoundError, OSError):  # pragma: no cover - FFmpeg
            energies = None
        try:
            estimate = await detect_tempo(song)
            tempo_bpm = estimate.bpm if estimate.detected else None
        except (RuntimeError, FileNotFoundError, OSError):  # pragma: no cover - FFmpeg
            tempo_bpm = None

    return build_signals(
        profile=audio_profile,
        energies=energies,
        tempo_bpm=tempo_bpm,
        themes=themes or {},
        sentiment=sentiment,
        metadata_text=metadata_text,
        mood=mood,
    )


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
    music_volume: float = 1.0,
    duration_from_audio: bool = True,
    clip_audio: bool = False,
    preview: bool = False,
    channel_data: ChannelData | None = None,
    journal: bool = True,
    journal_db: str | None = None,
    run_id: str | None = None,
    visuals: str = "off",
    ai_model: str | None = None,
    ai_steps: int = 2,
    ai_shots: int | None = None,
    ai_seed: int = 1234,
    aspect: str = "16:9",
    ai_style: str = "auto",
    ai_texts: bool = False,
    no_texts: bool = False,
    short: float | None = None,
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
        music_volume: Volumen de la canción en el vídeo final (0..1). Aquí la
            canción *es* la banda sonora (no música de fondo), así que por
            defecto va a 1.0.
        duration_from_audio: Si no se indica ``duration`` y hay canción elegida,
            el vídeo dura lo que la canción (evita desajustes entre audio y
            vídeo).
        clip_audio: Si ``True``, se conserva el audio original de los clips.
            Por defecto se silencia: la canción es la banda sonora y mezclar
            el audio de los clips con ella ensucia la mezcla (además de que
            una canción masterizada a tope + audio encima recorta).
        preview: Si ``True``, genera además una versión ligera del vídeo
            (``<nombre>_preview.mp4``) con audio estéreo a 128 kbps, lista
            para compartir por mensajería.
        channel_data: Canal ya construido que usar en lugar de investigar
            (útil para pruebas y flujos offline deterministas).
        journal: Registrar la decisión completa en el decision journal.
        journal_db: Base de datos del journal (por defecto
            ``YOUBER_JOURNAL_DB`` o ``~/.youber/journal.db``).
        run_id: Identificador de la ejecución (para agrupar decisiones).
        visuals: ``"off"`` monta clips (propios o de stock); ``"ai"`` **crea**
            los planos con un modelo local (ruta C de :mod:`youber.visuals`).
        ai_model: Modelo de imagen (por defecto ``stabilityai/sdxl-turbo``;
            ``"stub"`` genera degradados sin GPU).
        ai_steps: Pasos de inferencia del modelo.
        ai_shots: Número de planos (por defecto, según la duración).
        ai_seed: Semilla base de los planos.
        aspect: Formato del vídeo generado (``16:9``, ``9:16`` o ``1:1``).
        ai_style: Estilo visual de los planos (``auto`` por defecto: lo eligen
            el audio de la canción y los metadatos del canal; también vale
            ``cinematic``, ``dreamy``, ``dark``, ``vibrant`` o ``minimal``).
        ai_texts: Superponer los textos del guion sobre los planos.
        short: Si es un número, además del máster se genera el **corte
            vertical** (9:16) de esos segundos, elegido en el trozo con más
            energía de la canción (el estribillo).

    Returns:
        Diccionario con el prompt, el guion, la canción elegida y las rutas
        de los artefactos generados.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Paso 1: metadatos del canal
    console.print(Panel.fit("[bold cyan]Paso 1/6 · Metadatos del canal[/]", border_style="cyan"))
    if channel_data is not None:
        channel = channel_data
        console.print(f"📺 Canal proporcionado (offline): [bold]{channel.name}[/]")
    elif demo:
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
    candidates: list[TrackMatch] = []
    try:
        if lyrics_dir:
            summary = await library.scan(lyrics_dir=lyrics_dir)
            console.print(
                f"📚 Catálogo {library_dir}: {summary.get('added', 0)} nuevas, "
                f"{summary.get('updated', 0)} actualizadas ({library.count()} pistas)"
            )
        match: TrackMatch | None = None
        chosen_track: Track | None = None
        if track:
            forced = find_track(library, track)
            if forced is None:
                raise RuntimeError(
                    f"Canción no encontrada en el catálogo {library_dir!r}: {track!r}. "
                    "Escanea antes con: youber-music --library <dir> scan --lyrics-dir <letras>"
                )
            forced_match = TrackMatch(
                track_id=forced.id,
                title=forced.title,
                artist=forced.artist,
                score=0.0,
                matched_themes=list(forced.lyrical_themes),
                reason="elegida a mano (--track)",
            )
            match = forced_match
            chosen_track = forced
            candidates = [forced_match]
        else:
            # `require_local`: la banda sonora se mezcla con FFmpeg, así que
            # solo sirven pistas con fichero de audio real. Las importadas de
            # plataformas (source != local) tienen ruta sintética `cloud:*`.
            candidates = select_tracks(
                library.all(),
                profile,
                keywords=profile.top_words,
                limit=5,
                require_local=True,
            )
            match = candidates[0] if candidates else None
            chosen_track = library.get(match.track_id) if match is not None else None
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

        # Duración del vídeo: la de la canción elegida (el audio manda) salvo
        # que se indique una explícita, en cuyo caso manda esa.
        audio_duration: float | None = None
        if chosen_track is not None and duration_from_audio and chosen_track.duration > 0:
            audio_duration = float(chosen_track.duration)
        target_duration = float(duration) if duration else audio_duration
        if audio_duration is not None and not duration:
            console.print(
                f"⏱️  Duración del vídeo = la de la canción ([bold]{audio_duration:g} s[/])"
            )

        # Paso 5: prompt de producción + guion
        console.print(
            Panel.fit("[bold cyan]Paso 5/6 · Prompt y guion[/]", border_style="cyan")
        )
        brief = build_video_brief(
            insights,
            topic=clean_topic,
            duration=target_duration,
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
        clip_source = "local" if clip_paths else "none"
        final_video: Path | None = None
        preview_video: Path | None = None
        short_video: Path | None = None
        short_start: float | None = None
        visual_plan: Any = None
        plan_path: Path | None = None
        if visuals == "ai":
            from youber.audio._ffmpeg import probe_duration
            from youber.visuals.generator import create_generator
            from youber.visuals.render import render_visuals
            from youber.visuals.short import extract_window, pick_window

            if chosen_track is None or chosen_track.file_path is None:
                raise RuntimeError(
                    "La ruta visual con IA necesita una canción local del catálogo. "
                    "Escanea con: youber-music scan --library <dir> [--lyrics-dir <letras>]"
                )
            if not render:
                console.print("⏭️  Render omitido (--no-render): no se generan planos")
            else:
                ai_song = Path(chosen_track.file_path)
                generator = create_generator(ai_model, steps=ai_steps)
                clip_source = f"ai:{generator.name}"
                aspect_slug = aspect.replace(":", "x")
                mood_value = brief.music_mood.value if brief.music_mood else None
                beat_grid = await _beat_grid(ai_song)
                if beat_grid is not None:
                    console.print(
                        f"🥁 Pulso {beat_grid.bpm:.0f} BPM · primer beat "
                        f"{beat_grid.offset:.2f} s · los planos se cortarán al beat"
                    )
                visual_signals = await _visual_signals(
                    track_id=chosen_track.id,
                    song=ai_song,
                    themes=profile.themes,
                    sentiment=profile.sentiment,
                    metadata_text=metadata_text,
                    mood=mood_value,
                )
                console.print(
                    f"🎨 Planos creados de cero con [bold]{generator.name}[/] · {aspect} "
                    f"({ai_shots or 'auto'} planos) · estilo {ai_style}"
                )
                console.print(
                    f"🔎 Señales: energía {visual_signals.energy:.2f} · valencia "
                    f"{visual_signals.valence:.2f} · tension {visual_signals.tension:.2f} · "
                    f"tempo {visual_signals.tempo:.2f}"
                    + (
                        f" ({visual_signals.tempo_bpm:.0f} BPM medidos)"
                        if visual_signals.tempo_bpm
                        else ""
                    )
                    + f" ({', '.join(visual_signals.sources) or 'sin datos'})"
                )
                master = await render_visuals(
                    topic=clean_topic,
                    output=out / f"{_slug(clean_topic)}_{aspect_slug}.mp4",
                    song=ai_song,
                    scenes=script.scenes,
                    duration=target_duration,
                    aspect=aspect,
                    style=ai_style,
                    signals=visual_signals,
                    beat_grid=beat_grid,
                    mood=mood_value,
                    tone=brief.tone,
                    keywords=brief.keywords,
                    shots=ai_shots,
                    texts=ai_texts,
                    generator=generator,
                    seed=ai_seed,
                    preview=preview,
                    on_progress=lambda message: console.print(message),
                )
                final_video = master.video
                preview_video = master.preview
                clip_paths = list(master.clips)
                visual_plan = master.plan
                plan_path = out / f"{_slug(clean_topic)}_{aspect_slug}_plan.json"
                plan_path.write_text(visual_plan.model_dump_json(indent=2), encoding="utf-8")
                console.print(
                    f"✅ Vídeo creado de cero: [bold green]{final_video}[/] "
                    f"({master.duration:.1f} s · {len(visual_plan.shots)} planos)"
                )
                if short:
                    song_seconds = await probe_duration(ai_song)
                    short_seconds = min(float(short), song_seconds)
                    short_start, _ = await pick_window(ai_song, short_seconds)
                    console.print(
                        f"✂️  Estribillo: desde [bold]{short_start:.1f} s[/] "
                        f"({short_seconds:.0f} s de más energía de {song_seconds:.1f} s)"
                    )
                    cut = await extract_window(
                        ai_song,
                        out / f"{_slug(clean_topic)}_short_audio.m4a",
                        start=short_start,
                        duration=short_seconds,
                    )
                    short_result = await render_visuals(
                        topic=clean_topic,
                        output=out / f"{_slug(clean_topic)}_short_9x16.mp4",
                        song=cut,
                        scenes=script.scenes,
                        aspect="9:16",
                        style=ai_style,
                        signals=visual_signals,
                        beat_grid=(
                            beat_grid.shifted(short_start) if beat_grid is not None else None
                        ),
                        mood=mood_value,
                        tone=brief.tone,
                        keywords=brief.keywords,
                        shots=ai_shots,
                        texts=ai_texts,
                        generator=generator,
                        seed=ai_seed + 500,
                        preview=preview,
                        on_progress=lambda message: console.print(message),
                    )
                    short_video = short_result.video
                    short_plan_path = out / f"{_slug(clean_topic)}_short_9x16_plan.json"
                    short_plan_path.write_text(
                        short_result.plan.model_dump_json(indent=2), encoding="utf-8"
                    )
                    console.print(
                        f"✅ Short vertical: [bold green]{short_video}[/] "
                        f"({short_result.duration:.1f} s)"
                    )
        elif not clip_paths:
            from youber.video.stock import available as stock_available
            from youber.video.stock import fetch_clips_for_scenes

            banks = stock_available()
            if stock != "none" and any(banks.values()):
                clip_source = (
                    next(
                        (name for name, available_bank in banks.items() if available_bank),
                        stock,
                    )
                    if stock == "auto"
                    else stock
                )
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
                clip_source = "synthetic"
        console.print(f"🎞️  Clips: [bold]{len(clip_paths)}[/]")

        if render and visuals != "ai":
            editor = VideoEditor(library=library)
            project = build_project(
                script,
                clips=clip_paths,
                library=library,
                editor=editor,
                title=brief.topic,
                with_texts=not no_texts,
                music_track_id=match.track_id if match else None,
                music_volume=music_volume,
                clip_audio=clip_audio,
            )
            # Las transiciones solapadas acortan el montaje: se compensan para
            # que el vídeo dure exactamente lo mismo que la canción.
            if audio_duration is not None and not duration:
                current = _project_duration(project)
                gap = round(audio_duration - current, 3) if current is not None else 0.0
                if abs(gap) > 0.2:
                    brief = build_video_brief(
                        insights,
                        topic=clean_topic,
                        duration=audio_duration + gap,
                        profile=profile,
                        metadata_text=metadata_text,
                        track_match=match,
                    )
                    script = brief_to_script(brief, insights)
                    project = build_project(
                        script,
                        clips=clip_paths,
                        library=library,
                        editor=editor,
                        title=brief.topic,
                        with_texts=not no_texts,
                        music_track_id=match.track_id if match else None,
                        music_volume=music_volume,
                        clip_audio=clip_audio,
                    )
                    console.print(
                        f"⏱️  Transiciones compensadas ({gap:+.1f} s) para cuadrar con "
                        f"la canción ({audio_duration:g} s)"
                    )
            final_video = out / f"{_slug(brief.topic)}_final.mp4"
            console.print(f"🎛️  Renderizando (FFmpeg) → [bold]{final_video}[/]")
            await editor.render(project, final_video)
            console.print(f"✅ Vídeo final + canción: [bold green]{final_video}[/]")
            if preview:
                from youber.video.preview import make_preview

                console.print("📱 Generando preview ligero (480p · audio estéreo 128 kbps)...")
                preview_video = Path(await make_preview(final_video))
                console.print(f"✅ Preview para compartir: [bold green]{preview_video}[/]")
        elif visuals != "ai":
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

        # Registro de la decisión completa (metadatos → canción → vídeo)
        decision_id: str | None = None
        if journal:
            decision_id = _journal_record(
                record_from_lyrics_run(
                    topic=brief.topic,
                    channel=channel,
                    insights=insights,
                    profile=profile,
                    match=match,
                    candidates=candidates,
                    chosen_track=chosen_track,
                    forced=bool(track),
                    catalog_size=library.count(),
                    prompt=brief.prompt,
                    keywords=brief.keywords,
                    target_duration=brief.target_duration,
                    scenes=len(script.scenes),
                    music_mood=brief.music_mood,
                    artifacts={
                        "brief": str(brief_path),
                        "script": str(script_path),
                        "json": str(brief_json),
                        "markdown": str(md_path),
                    },
                    video_path=final_video,
                    video_duration=await _video_duration(final_video),
                    clip_count=len(clip_paths),
                    clip_source=clip_source,
                    mode="demo" if demo else mode,
                    run_id=run_id,
                    metadata_text=metadata_text,
                ),
                journal_db,
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
        "clip_source": clip_source,
        "final_video": str(final_video) if final_video else None,
        "preview_video": str(preview_video) if preview_video else None,
        "visuals": visuals,
        "aspect": aspect if visuals == "ai" else None,
        "plan": str(plan_path) if plan_path else None,
        "short_video": str(short_video) if short_video else None,
        "short_start": short_start,
        "decision_id": decision_id,
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
                    duration=args.duration,
                    mode="api" if args.api else "html",
                    demo=args.demo,
                    library_dir=args.library,
                    lyrics_dir=args.lyrics_dir,
                    clips=args.clips,
                    stock=args.stock,
                    track=args.track,
                    render=not args.no_render,
                    music_volume=args.music_volume,
                    clip_audio=args.clip_audio,
                    preview=args.preview,
                    journal=not args.no_journal,
                    journal_db=args.journal_db,
                    visuals=args.visuals,
                    ai_model=args.ai_model,
                    ai_steps=args.ai_steps,
                    ai_shots=args.ai_shots,
                    ai_seed=args.ai_seed,
                    aspect=args.ai_aspect,
                    ai_style=args.ai_style,
                    ai_texts=args.ai_texts,
                    no_texts=args.no_texts,
                    short=args.short,
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
                duration=args.duration or DEFAULT_DURATION,
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
                journal=not args.no_journal,
                journal_db=args.journal_db,
            )
        )
    except Exception as exc:
        console.print(f"[red]✗ Error: {exc}[/]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
