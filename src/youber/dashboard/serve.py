"""Servidor web del dashboard de BARF.

Permite **trabajar directamente en el dashboard** desde el navegador, sin
tocar comandos: ``youber-dashboard serve`` abre una página local que se
auto-refresca, muestra los widgets seleccionados y permite cambiar la
selección con checkboxes (se guarda en ``~/.youber/dashboard.json``).

Solo usa la librería estándar (``http.server``), escucha en 127.0.0.1 y no
expone datos fuera de la máquina.
"""

from __future__ import annotations

import asyncio
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from loguru import logger

from youber.dashboard.models import WidgetData, WidgetType
from youber.dashboard.renderer import render_widget_html
from youber.dashboard.widgets import WidgetManager
from youber.music.models import TrackSource
from youber.music.providers import import_cloud

DEFAULT_CONFIG_PATH = Path.home() / ".youber" / "dashboard.json"
DEFAULT_WIDGETS = ["catalog-stats", "scheduled-tasks", "upload-status"]
# Libre en esta máquina: 8765 lo usa Lumenoia y 18789 el gateway de OpenClaw.
DEFAULT_PORT = 8787
DEFAULT_REFRESH = 60  # segundos


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Carga la configuración del dashboard (widgets, refresco, puerto).

    Si el fichero no existe, devuelve los valores por defecto (los tres
    widgets de trabajo diario: catálogo, tareas programadas y subidas).
    """
    file = Path(path)
    if not file.exists():
        return {
            "widgets": list(DEFAULT_WIDGETS),
            "refresh_seconds": DEFAULT_REFRESH,
            "port": DEFAULT_PORT,
        }
    raw = json.loads(file.read_text(encoding="utf-8"))
    config = {
        "widgets": list(DEFAULT_WIDGETS),
        "refresh_seconds": DEFAULT_REFRESH,
        "port": DEFAULT_PORT,
    }
    config.update(raw)
    return config


def save_config(config: dict[str, Any], path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    """Guarda la configuración del dashboard en el fichero indicado."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class DashboardApp:
    """Aplicación del dashboard: configuración + recolección de datos."""

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        widgets: list[str] | None = None,
        refresh_seconds: int | None = None,
        port: int | None = None,
        library_dir: str | Path = "music",
    ) -> None:
        config = load_config(config_path)
        self.config_path = Path(config_path)
        self.widgets: list[str] = widgets or config["widgets"]
        self.refresh_seconds: int = refresh_seconds or config["refresh_seconds"]
        self.port: int = port or config["port"]
        self.library_dir = Path(library_dir)
        self._library: Any = None
        self.manager = WidgetManager()

    def collect(self) -> list[WidgetData]:
        """Recolecta los datos de los widgets seleccionados."""
        return self.manager.collect_types(self.widgets)

    async def import_cloud(
        self,
        query: str,
        source: TrackSource | str = TrackSource.APPLE,
        limit: int = 10,
        external_ids: list[str] | None = None,
    ) -> dict[str, int]:
        """Busca en la plataforma e importa al catálogo del dashboard.

        Usa el mismo catálogo local que muestra el widget ``catalog-stats``
        (``<library_dir>/.music.db``), así los cambios se ven al refrescar.
        """
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        return await import_cloud(
            query,
            source,
            limit=limit,
            db=self._library.db,
            external_ids=external_ids,
        )

    async def search_cloud(
        self,
        query: str,
        source: TrackSource | str = TrackSource.APPLE,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Busca en la plataforma y devuelve resultados (sin importar)."""
        from youber.music.providers import search as providers_search

        hits = await providers_search(source, query, limit)
        return {
            "source": TrackSource(source).value,
            "query": query,
            "hits": [hit.model_dump(mode="json") for hit in hits],
        }

    async def import_apple_library(self, path: str) -> dict[str, int]:
        """Importa el XML exportado de la biblioteca de Apple al catálogo."""
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        from youber.music.apple_library import import_apple_library as import_library

        return await import_library(path, db=self._library.db)

    # -- Spotify (OAuth) ----------------------------------------------------

    def _spotify_client(self):
        from youber.music.spotify_library import SpotifyLibraryClient

        return SpotifyLibraryClient(
            redirect_uri=f"http://127.0.0.1:{self.port}/callback"
        )

    def spotify_auth_url(self) -> str:
        """URL de autorización de Spotify para abrir en el navegador."""
        return self._spotify_client().authorization_url()

    async def spotify_exchange(self, code: str) -> dict[str, Any]:
        """Intercambia el código de autorización y guarda la sesión."""
        return await self._spotify_client().exchange_code(code)

    async def spotify_import(self, include_playlists: bool = False) -> dict[str, Any]:
        """Importa la biblioteca de Spotify (Liked Songs + playlists) al catálogo."""
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        from youber.music.spotify_library import import_spotify_library

        return await import_spotify_library(
            client=self._spotify_client(),
            db=self._library.db,
            include_playlists=include_playlists,
        )

    def spotify_status(self) -> dict[str, Any]:
        """Estado de la conexión con Spotify (sin secretos)."""
        client = self._spotify_client()
        return {
            "available": client.available,
            "connected": client.connected,
        }

    # -- YouTube Music (biblioteca personal) -------------------------------

    def ytmusic_status(self) -> dict[str, Any]:
        """Estado de la autenticación de YouTube Music (headers presentes)."""
        from youber.music.youtube_music import DEFAULT_HEADERS_FILE

        return {
            "headers": DEFAULT_HEADERS_FILE.exists(),
            "headers_path": str(DEFAULT_HEADERS_FILE),
        }

    async def ytmusic_import(self, include_playlists: bool = True) -> dict[str, Any]:
        """Importa la biblioteca de YouTube Music (Me gusta + guardadas + playlists)."""
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        from youber.music.youtube_music import (
            YouTubeMusicClient,
            import_ytmusic_library,
        )

        return await import_ytmusic_library(
            client=YouTubeMusicClient(),
            db=self._library.db,
            include_playlists=include_playlists,
        )

    async def channel_import(self, handle: str) -> dict[str, Any]:
        """Importa el catálogo público de un artista/canal de YouTube Music."""
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        from youber.music.youtube_music import import_channel

        return await import_channel(handle, db=self._library.db)

    # -- Research (pestaña 🔍 Research) -------------------------------------

    async def research(
        self, url: str, max_videos: int = 10
    ) -> dict[str, Any]:
        """Analiza un canal o vídeo de YouTube (datos públicos) y devuelve
        los ``max_videos`` más virales ordenados por vistas desc.

        Args:
            url: URL del canal (``@handle``, ``channel/UC...``) o vídeo.
            max_videos: Número de vídeos a recoger del canal.

        Returns:
            Dict con ``kind`` (``channel``/``video``), datos del canal o
            vídeo, lista de vídeos (ordenada por vistas desc) y resumen
            ``views_summary``. Lanza ``ValueError`` si no se puede extraer.
        """
        from youber.research.channel_analyzer import ChannelAnalyzer
        from youber.research.patterns import parse_compact_count
        from youber.research.video_analyzer import VideoAnalyzer, extract_video_id

        if extract_video_id(url):
            video = await VideoAnalyzer().analyze(url, mode="html")
            return {"kind": "video", "video": video.model_dump(mode="json")}

        channel = await ChannelAnalyzer().analyze(
            url, max_videos=max_videos, mode="html"
        )
        videos = [video.model_dump(mode="json") for video in channel.videos]
        videos.sort(
            key=lambda v: parse_compact_count(v.get("views") or "") or 0.0,
            reverse=True,
        )
        parsed = [
            parse_compact_count(video.get("views") or "") or 0.0 for video in videos
        ]
        summary: dict[str, Any] = {"count": len(parsed)}
        if parsed:
            summary["avg"] = round(sum(parsed) / len(parsed))
            summary["max"] = round(max(parsed))
        return {
            "kind": "channel",
            "channel": {
                "name": channel.name,
                "url": channel.url,
                "handle": channel.handle,
                "subscribers": channel.subscribers,
            },
            "videos": videos,
            "views_summary": summary,
        }

    async def script_proposal(
        self,
        url: str,
        topic: str = "Mi vídeo",
        duration: float | None = None,
        max_videos: int = 10,
    ) -> dict[str, Any]:
        """Analiza un canal o vídeo y propone guion + música local para tu vídeo.

        Args:
            url: URL del canal (``@handle``, ``channel/UC...``) o de un vídeo
                (``watch?v=...``, ``youtu.be/...``). Si es un vídeo, su título,
                descripción y transcripción marcan el contenido del guion
                (keywords reales para el stock y duración de referencia).
            topic: Tema de tu vídeo; si la URL es un vídeo y no se indica,
                se usa el título del vídeo.
            duration: Duración total deseada (s); si es ``None`` se usa la
                media del canal (o la del vídeo origen, con mínimo).
            max_videos: Vídeos del canal a analizar para los insights.

        Returns:
            Dict con el guion (``script``), el canal y las opciones de
            música local (``music.options``) + la sugerida
            (``music.suggested_track_id``). Lanza ``ValueError`` si el canal
            no se puede analizar.
        """
        from youber.research.channel_analyzer import ChannelAnalyzer
        from youber.research.data_models import ChannelData
        from youber.research.patterns import channel_overview
        from youber.research.video_analyzer import VideoAnalyzer, extract_video_id
        from youber.script.builder import _pick_local_track
        from youber.script.generator import generate_script
        from youber.script.transcripts import (
            analyze_channel as analyze_transcripts,
        )
        from youber.script.transcripts import (
            analyze_video as analyze_video_transcript,
        )

        video_id = extract_video_id(url)
        content_keywords: list[str] | None = None
        if video_id:
            # La URL es un vídeo concreto (p. ej. uno tuyo): su contenido manda.
            video = await VideoAnalyzer().analyze(url, mode="auto")
            channel = ChannelData(
                name=video.channel_name,
                url=video.channel_url or url,
                handle=None,
                subscribers=None,
                videos=[video],
            )
            insights = channel_overview(channel)
            if not topic or topic == "Mi vídeo":
                topic = video.title or topic
            # Transcripción del propio vídeo → hooks, CTA y keywords reales.
            analysis = analyze_video_transcript(video.video_id)
            text_source = " ".join(
                filter(None, [video.title, video.description])
            )
            from youber.script.transcripts import extract_keywords

            content_keywords = extract_keywords(text_source)
            if analysis and analysis.keywords:
                content_keywords = list(
                    dict.fromkeys(content_keywords + analysis.keywords)
                )[:8]
        else:
            channel = await ChannelAnalyzer().analyze(
                url, max_videos=max_videos, mode="html"
            )
            insights = channel_overview(channel)
            # Transcripciones públicas del canal patrón → instrucciones reales.
            analysis = analyze_transcripts(channel.videos, max_videos=3)
            if analysis.video_count and analysis.keywords:
                content_keywords = analysis.keywords

        script = generate_script(
            insights,
            topic=topic,
            duration=duration,
            transcripts=(
                analysis if analysis and analysis.video_count else None
            ),
            content_keywords=content_keywords,
        )

        library = self._get_library()
        local_tracks = [
            track for track in library.all() if track.source == TrackSource.LOCAL
        ]
        suggested = _pick_local_track(library, script) if local_tracks else None

        from youber.video.stock import available as stock_available

        stock = stock_available()
        return {
            "ok": True,
            "channel": channel.name,
            "channel_url": channel.url,
            "script": script.model_dump(mode="json"),
            "stock": stock,
            "music": {
                "suggested_track_id": suggested.id if suggested else None,
                "suggested_mood": (
                    script.music_mood.value if script.music_mood else None
                ),
                "options": [
                    {
                        "id": track.id,
                        "title": track.title,
                        "artist": track.artist,
                        "genre": track.genre,
                        "duration": round(track.duration, 1) if track.duration else None,
                        "favorite": track.favorite,
                        "usage_count": track.usage_count,
                    }
                    for track in local_tracks
                ],
            },
        }

    async def script_render(
        self,
        script_data: dict[str, Any],
        clips: list[str],
        music_track_id: str | None = None,
        output_dir: str = "reports",
        use_stock: bool = False,
        show_texts: bool = False,
    ) -> dict[str, Any]:
        """Construye y renderiza el vídeo aprobado por el usuario.

        Args:
            script_data: Guion (dict, salida de ``script_proposal``).
            clips: Rutas de tus ficheros de vídeo (se reparten por escena).
                Si viene vacío y ``use_stock`` es True, se descargan clips
                de stock (Pexels/Pixabay) automáticamente por escena.
            music_track_id: Pista local del catálogo para la música.
            output_dir: Directorio del vídeo final.
            use_stock: Si True y no hay clips, busca/descarga B-roll de
                stock según las keywords de cada escena (requiere
                ``PEXELS_API_KEY`` o ``PIXABAY_API_KEY``).
            show_texts: Si False (por defecto), NO se superponen los textos
                del guion (son instrucciones de edición, no texto para el
                espectador).

        Returns:
            Dict con ``ok``, ``output`` (ruta del MP4), número de clips y
            textos del proyecto. Lanza ``ValueError`` si faltan clips o la
            pista no es local.
        """
        from pathlib import Path as _Path

        from youber.script.builder import build_project
        from youber.script.models import Script
        from youber.video.editor import VideoEditor

        script = Script.model_validate(script_data)
        if not clips and use_stock:
            from youber.video.stock import available, fetch_clips_for_scenes

            if not any(available().values()):
                raise ValueError(
                    "Clips de stock activados pero sin key: configura "
                    "PEXELS_API_KEY o PIXABAY_API_KEY (gratis en pexels.com/api)"
                )
            scenes = [scene.model_dump() for scene in script.scenes]
            # Varios clips DISTINTOS por escena: un clip corto en bucle se
            # nota mucho, así que cada escena recibe 2-5 clips de ~6 s.
            avg_scene = script.total_duration / max(1, len(scenes))
            per_scene = max(2, min(5, max(1, round(avg_scene / 6))))
            fetched = await fetch_clips_for_scenes(
                scenes, _Path("clips"), bank="auto", per_scene=per_scene
            )
            clips = [str(p) for paths in fetched.values() for p in paths]
        if not clips:
            raise ValueError(
                "Selecciona al menos un clip de vídeo propio (o activa los "
                "clips de stock automáticos)"
            )
        library = self._get_library()
        editor = VideoEditor(library=library)
        project = build_project(
            script,
            clips=clips,
            library=library,
            editor=editor,
            title=script.topic,
            with_texts=show_texts,
        )
        if music_track_id:
            editor.set_music(project, music_track_id, volume=0.25)
        out_dir = _Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = "".join(
            c if c.isalnum() and ord(c) < 128 else "-" for c in script.topic
        ).strip("-").lower() or "video"
        output = out_dir / f"{slug}_final.mp4"
        await editor.render(project, output)
        return {
            "ok": True,
            "output": str(output),
            "clips": len(project.clips),
            "texts": len(project.text_overlays),
            "music_track_id": project.music_track_id,
        }

    def videos(self, output_dir: str = "reports") -> list[dict[str, Any]]:
        """Lista los vídeos renderizados (MP4/MKV/WebM/MOV) del directorio de salida.

        Returns:
            Lista de dicts con ``name``, ``url``, ``size``, ``modified`` y
            ``duration`` (si ffprobe está disponible). Ordenados por fecha
            de modificación descendente.
        """
        from pathlib import Path as _Path

        out = _Path(output_dir)
        if not out.exists():
            return []
        exts = (".mp4", ".mkv", ".webm", ".mov")
        videos: list[dict[str, Any]] = []
        for f in sorted(out.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not f.is_file() or f.suffix.lower() not in exts:
                continue
            duration: float | None = None
            try:
                import subprocess

                result = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "csv=p=0",
                        str(f),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                raw = result.stdout.strip()
                if raw:
                    duration = round(float(raw), 1)
            except Exception:
                duration = None
            videos.append(
                {
                    "name": f.name,
                    "url": f"/media/{f.name}",
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                    "duration": duration,
                }
            )
        return videos

    # -- Catálogo (pestaña Canciones) --------------------------------------

    def _get_library(self) -> Any:
        """Devuelve la biblioteca de música del dashboard (creándola si falta)."""
        from youber.music.library import MusicLibrary

        if self._library is None:
            self._library = MusicLibrary(self.library_dir)
        return self._library

    def tracks(self, query: str | None = None) -> list[dict[str, Any]]:
        """Lista las canciones del catálogo con sus datos principales.

        Args:
            query: Texto opcional para filtrar por título/artista/álbum/género.

        Returns:
            Lista de dicts con ``id``, ``title``, ``artist``, ``album``,
            ``duration``, ``genre``, ``source``, ``favorite``, ``usage_count``,
            ``bpm`` y propiedades de audio (``energy``, ``danceability``,
            ``valence``, ``tempo``, ``confidence``) si hay perfil.
        """
        tracks = self._get_library().all()
        profiles = {
            profile.track_id: profile
            for profile in self._audio_profiles()
        }
        needle = (query or "").strip().lower()
        result: list[dict[str, Any]] = []
        for track in sorted(tracks, key=lambda item: item.title.lower()):
            parts = [
                part
                for part in (
                    track.title,
                    track.artist,
                    track.album,
                    track.genre,
                    track.source.value,
                )
                if part
            ]
            if needle and needle not in " ".join(parts).lower():
                continue
            item: dict[str, Any] = {
                "id": track.id,
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "duration": track.duration,
                "genre": track.genre,
                "source": track.source.value,
                "favorite": track.favorite,
                "usage_count": track.usage_count,
                "bpm": track.bpm,
            }
            profile = profiles.get(track.id)
            if profile is not None:
                features = profile.features
                item.update(
                    {
                        "energy": round(features.energy, 2),
                        "danceability": round(features.danceability, 2),
                        "valence": round(features.valence, 2),
                        "tempo": round(features.tempo),
                        "confidence": features.confidence,
                    }
                )
            result.append(item)
        return result

    def _audio_profiles(self) -> list[Any]:
        """Carga los perfiles de audio guardados (vacío si no hay)."""
        from youber.music.audio_features.enricher import AudioFeatureStore

        try:
            return AudioFeatureStore().all()
        except Exception as exc:
            logger.warning(f"No se pudieron cargar los perfiles de audio: {exc}")
            return []

    def recommend(self, track_id: str, limit: int = 5) -> dict[str, Any]:
        """Recomienda canciones similares por características de audio.

        Args:
            track_id: Canción de referencia.
            limit: Máximo de recomendaciones.

        Returns:
            Dict con ``target`` y ``recommendations`` (o ``error`` si no hay
            perfil de audio para la canción).
        """
        from youber.music.audio_features.recommender import FeatureRecommender

        profiles = self._audio_profiles()
        target = next((p for p in profiles if p.track_id == track_id), None)
        if target is None:
            return {"error": f"No hay perfil de audio para la canción «{track_id}»"}
        recommendations = FeatureRecommender(limit=limit).recommend(target, profiles)
        return {
            "target": {
                "track_id": target.track_id,
                "track_title": target.track_title,
                "artist": target.artist,
            },
            "recommendations": [
                {
                    "rank": item.rank,
                    "track_id": item.track_id,
                    "track_title": item.track_title,
                    "artist": item.artist,
                    "score": item.score,
                    "energy": round(item.features.energy, 2),
                    "danceability": round(item.features.danceability, 2),
                    "valence": round(item.features.valence, 2),
                    "tempo": round(item.features.tempo),
                }
                for item in recommendations
            ],
        }

    def list_playlists(self) -> list[dict[str, Any]]:
        """Lista las playlists guardadas con sus pistas enriquecidas."""
        from youber.music.playlists import PlaylistStore

        store = PlaylistStore()
        profiles = {p.track_id: p for p in self._audio_profiles()}
        tracks_by_id = {t.id: t for t in self._get_library().all()}
        result: list[dict[str, Any]] = []
        for playlist in store.all():
            tracks: list[dict[str, Any]] = []
            for track_id in playlist.track_ids:
                track = tracks_by_id.get(track_id)
                if track is None:
                    continue
                item: dict[str, Any] = {
                    "id": track.id,
                    "title": track.title,
                    "artist": track.artist,
                    "genre": track.genre,
                }
                profile = profiles.get(track_id)
                if profile is not None:
                    item.update(
                        {
                            "energy": round(profile.features.energy, 2),
                            "danceability": round(profile.features.danceability, 2),
                            "valence": round(profile.features.valence, 2),
                            "tempo": round(profile.features.tempo),
                        }
                    )
                tracks.append(item)
            result.append(
                {
                    "id": playlist.id,
                    "name": playlist.name,
                    "description": playlist.description,
                    "created_at": playlist.created_at,
                    "track_count": len(tracks),
                    "tracks": tracks,
                }
            )
        return result

    def create_playlist(
        self, name: str, track_ids: list[str], description: str = ""
    ) -> dict[str, Any]:
        """Crea una playlist con las pistas indicadas."""
        from youber.music.playlists import PlaylistStore

        store = PlaylistStore()
        playlist = store.create(name, track_ids, description)
        return {
            "ok": True,
            "id": playlist.id,
            "name": playlist.name,
            "track_count": len(playlist.track_ids),
        }

    def delete_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Elimina una playlist por id."""
        from youber.music.playlists import PlaylistStore

        store = PlaylistStore()
        if not store.delete(playlist_id):
            return {"ok": False, "error": "Playlist no encontrada"}
        return {"ok": True}

    def toggle_favorite(self, track_id: str) -> dict[str, Any]:
        """Marca/desmarca una canción como favorita.

        Returns:
            Dict con ``id`` y ``favorite`` (nuevo estado); o ``error`` si la
            canción no existe.
        """
        library = self._get_library()
        track = library.get(track_id)
        if track is None:
            return {"error": f"Canción no encontrada: {track_id}"}
        new_state = not track.favorite
        library.mark_favorite(track_id, new_state)
        return {"id": track_id, "favorite": new_state}

    def data_payload(self) -> dict[str, Any]:
        """Payload JSON del endpoint ``/api/data`` (para el polling)."""
        from datetime import datetime

        return {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "refresh_seconds": self.refresh_seconds,
            "widgets": [
                widget.model_dump(mode="json") for widget in self.collect()
            ],
        }

    def render_page(self) -> str:
        """Página HTML del dashboard (autocontenida, con JS de polling)."""
        checkboxes = "\n".join(
            f'<label class="chk"><input type="checkbox" name="widget" value="{widget.value}"'
            f'{" checked" if widget.value in self.widgets else ""}> {widget.value}</label>'
            for widget in WidgetType
        )
        cards = "\n".join(
            render_widget_html(data) for data in self.collect()
        )
        refresh = self.refresh_seconds
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Dashboard — Youber</title>
<style>
body{{font-family:sans-serif;margin:2rem;background:#f7f7f7;color:#222}}
h1{{margin-bottom:0.2rem}}
.sub{{color:#666;font-size:0.9rem;margin-bottom:1rem}}
#updated{{color:#777;font-size:0.8rem;margin-top:0.5rem}}
.controls{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:0.8rem 1.2rem;margin-bottom:1.2rem}}
.chk{{margin-right:0.9rem;white-space:nowrap}}
button{{margin-left:0.6rem;padding:0.25rem 1rem;cursor:pointer}}
.filter-btn{{background:#fff;border:1px solid #ccc;border-radius:16px;padding:0.2rem 0.9rem;cursor:pointer;font-size:0.85rem;margin-left:0.4rem}}
.filter-btn.active{{background:#1a73e8;border-color:#1a73e8;color:#fff}}
.status{{margin-left:0.8rem;color:#555;font-size:0.85rem}}
#cloud-results{{margin-top:0.6rem}}
.hit{{display:block;padding:0.25rem 0;cursor:pointer}}
.hit:hover{{background:#f0f4f8}}
.hit .meta{{color:#777;font-size:0.85rem}}
#grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:1rem}}
.widget{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:1rem 1.5rem}}
.widget h3{{margin-top:0}}li{{margin:0.2rem 0}}
.tabs{{margin-bottom:1rem}}
.tab-btn{{background:#fff;border:1px solid #ddd;border-radius:8px 8px 0 0;padding:0.5rem 1.2rem;cursor:pointer;margin-right:0.3rem;font-size:1rem}}
.tab-btn.active{{background:#1a73e8;color:#fff;border-color:#1a73e8}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden}}
th,td{{padding:0.5rem 0.8rem;text-align:left;border-bottom:1px solid #eee;font-size:0.9rem}}
th{{cursor:pointer;background:#f0f4f8;user-select:none;white-space:nowrap}}
tr:hover{{background:#f7fafc}}
.fav{{background:none;border:none;cursor:pointer;font-size:1.1rem}}
.badge{{display:inline-block;padding:0.1rem 0.5rem;border-radius:10px;font-size:0.75rem;color:#fff}}
.badge-local{{background:#5f6368}}.badge-youtube{{background:#c5221f}}.badge-apple{{background:#a50e2c}}.badge-spotify{{background:#1db954}}
</style>
</head>
<body>
<h1>📊 Dashboard — Youber</h1>
<p class="sub">Auto-refresco cada {refresh}s · configuración guardada en {self.config_path}</p>
<div class="tabs">
  <button class="tab-btn active" id="tab-btn-dashboard" onclick="switchTab('dashboard')">📊 Dashboard</button>
  <button class="tab-btn" id="tab-btn-tracks" onclick="switchTab('tracks')">🎵 Canciones</button>
  <button class="tab-btn" id="tab-btn-research" onclick="switchTab('research')">🔍 Research</button>
  <button class="tab-btn" id="tab-btn-script" onclick="switchTab('script')">🎬 Edición</button>
  <button class="tab-btn" id="tab-btn-videos" onclick="switchTab('videos')">📼 Vídeos</button>
</div>
<div id="tab-dashboard">
<div class="controls">
  <form id="config-form">
    {checkboxes}
    <button type="submit">Guardar selección</button>
  </form>
</div>
<div class="controls" id="cloud-box">
  <form id="cloud-form">
    <strong>🎵 Importar música desde plataforma:</strong>
    <input type="text" id="cloud-q" placeholder="p. ej. lofi beats" style="min-width:220px">
    <select id="cloud-source">
      <option value="apple">Apple (iTunes)</option>
      <option value="spotify">Spotify</option>
    </select>
    <input type="number" id="cloud-limit" value="10" min="1" max="50" style="width:70px">
    <button type="submit">Buscar</button>
    <span id="cloud-status" class="status"></span>
  </form>
  <div id="cloud-results"></div>
  <form id="apple-library-form" style="margin-top:0.8rem;border-top:1px dashed #ccc;padding-top:0.7rem">
    <strong>🍎 Importar TODA tu biblioteca de Apple:</strong>
    <input type="text" id="apple-library-path" placeholder="ruta del XML exportado (p. ej. C:/Users/tu/Music/iTunes/iTunes Music Library.xml)" style="min-width:380px">
    <button type="submit">Importar biblioteca</button>
    <span id="apple-status" class="status"></span>
  </form>
  <form id="ytmusic-form" style="margin-top:0.8rem;border-top:1px dashed #ccc;padding-top:0.7rem">
    <strong>🎧 Importar mi biblioteca de YouTube Music:</strong>
    <label><input type="checkbox" id="ytmusic-playlists" checked> incluir playlists</label>
    <button type="submit">Importar</button>
    <span id="ytmusic-status" class="status"></span>
  </form>
  <form id="channel-form" style="margin-top:0.8rem;border-top:1px dashed #ccc;padding-top:0.7rem">
    <strong>🎤 Importar catálogo del canal/artista:</strong>
    <input type="text" id="channel-handle" placeholder="p. ej. @KnightPrincessReal" style="min-width:220px">
    <button type="submit">Importar</button>
    <span id="channel-status" class="status"></span>
  </form>
</div>
<div id="grid">{cards}</div>
<p id="updated"></p>
</div>
<div id="tab-tracks" style="display:none">
  <div class="controls">
    <strong>🎵 Catálogo de canciones:</strong>
    <input type="text" id="tracks-q" placeholder="Buscar por título/artista/álbum/género…" style="min-width:280px" oninput="loadTracks()">
    <button onclick="loadTracks()">↻</button>
    <button onclick="exportTracks('csv')" title="Exportar selección actual a CSV (Excel)">💾 CSV</button>
    <button onclick="exportTracks('json')" title="Exportar selección actual a JSON">💾 JSON</button>
    <span id="tracks-count" class="status"></span>
  </div>
  <div class="controls" id="tracks-filters">
    <strong>Filtros:</strong>
    <button class="filter-btn active" data-filter="all" onclick="setTrackFilter('all')">🎵 Todas</button>
    <button class="filter-btn" data-filter="energetic" onclick="setTrackFilter('energetic')">⚡ Energética</button>
    <button class="filter-btn" data-filter="danceable" onclick="setTrackFilter('danceable')">💃 Bailable</button>
    <button class="filter-btn" data-filter="relaxed" onclick="setTrackFilter('relaxed')">😌 Relajada</button>
    <button class="filter-btn" data-filter="positive" onclick="setTrackFilter('positive')">😊 Positiva</button>
    <button class="filter-btn" data-filter="intense" onclick="setTrackFilter('intense')">🖤 Intensa</button>
    <button class="filter-btn" data-filter="favorites" onclick="setTrackFilter('favorites')">⭐ Favoritas</button>
  </div>
  <div style="overflow-x:auto;background:#fff;border:1px solid #ddd;border-radius:8px">
  <table>
    <thead>
      <tr>
        <th onclick="sortTracks('title')">Título</th>
        <th onclick="sortTracks('artist')">Artista</th>
        <th onclick="sortTracks('album')">Álbum</th>
        <th onclick="sortTracks('duration')">Duración</th>
        <th onclick="sortTracks('genre')">Género</th>
        <th onclick="sortTracks('energy')">Energía</th>
        <th onclick="sortTracks('danceability')">Baile</th>
        <th onclick="sortTracks('valence')">Ánimo</th>
        <th onclick="sortTracks('tempo')">BPM</th>
        <th onclick="sortTracks('source')">Fuente</th>
        <th onclick="sortTracks('favorite')">⭐</th>
        <th onclick="sortTracks('usage_count')">Usos</th>
      </tr>
    </thead>
    <tbody id="tracks-body"><tr><td colspan="9" style="text-align:center;color:#888">Cargando…</td></tr></tbody>
  </table>
  </div>
  <div id="recommend-results"></div>
  <div class="controls" style="margin-top:1rem" id="playlist-controls">
    <strong>📋 Guardar como playlist:</strong>
    <input type="text" id="playlist-name" placeholder="Nombre de la playlist" style="min-width:200px">
    <button onclick="savePlaylist()">💾 Guardar selección actual</button>
    <span id="playlists-count" class="status"></span>
  </div>
  <div id="playlists-list"></div>
</div>
<div id="tab-research" style="display:none">
  <div class="controls">
    <form id="research-form">
      <strong>🔍 Research de YouTube (datos públicos):</strong>
      <input type="text" id="research-url" placeholder="URL del canal o vídeo (p. ej. https://www.youtube.com/@MrBeast)" style="min-width:320px">
      <label>Top <input type="number" id="research-n" value="10" min="1" max="50" style="width:60px"></label>
      <button type="submit">Analizar</button>
      <span id="research-status" class="status"></span>
    </form>
    <p class="status" style="margin-top:0.5rem">Solo datos públicos, con rate-limit (1.5 s por petición) y sin login. Ordena los vídeos por vistas (los más virales primero).</p>
  </div>
  <div id="research-results"></div>
</div>
<div id="tab-script" style="display:none">
  <div class="controls">
    <form id="script-form">
      <strong>🎬 Edición: guion desde la estructura del canal + tu música:</strong>
      <input type="text" id="script-url" placeholder="URL del canal de referencia (p. ej. https://www.youtube.com/@MrBeast)" style="min-width:320px">
      <input type="text" id="script-topic" placeholder="Tema de tu vídeo" style="min-width:160px" value="Mi vídeo">
      <label>Duración (s, opcional) <input type="number" id="script-duration" placeholder="auto" style="width:80px"></label>
      <button type="submit">🎬 Generar propuesta</button>
      <span id="script-status" class="status"></span>
    </form>
    <p class="status" style="margin-top:0.5rem">Analiza la estructura del canal (duración media, patrones de títulos, hashtags) y propone un guion + música de tu biblioteca local. Tú das el visto bueno antes de editar.</p>
  </div>
  <div id="script-results"></div>
</div>
<div id="tab-videos" style="display:none">
  <div class="controls">
    <strong>📼 Vídeos renderizados:</strong>
    <button onclick="loadVideos()">↻</button>
    <span id="videos-status" class="status"></span>
    <p class="status" style="margin-top:0.5rem">Clips editados por la pestaña 🎬 Edición (directorio <code>reports/</code>).</p>
  </div>
  <div id="videos-list"></div>
</div>
<script>
const REFRESH_MS = {refresh} * 1000;
async function loadData() {{
  const res = await fetch('/api/data');
  const payload = await res.json();
  const grid = document.getElementById('grid');
  grid.innerHTML = payload.widgets.map(w => {{
    const items = Object.entries(w.data).map(([k, v]) =>
      `<li><strong>${{k}}:</strong> ${{JSON.stringify(v)}}</li>`).join('');
    return `<div class="widget"><h3>${{w.title}}</h3><ul>${{items}}</ul></div>`;
  }}).join('');
  document.getElementById('updated').textContent =
    'Última actualización: ' + payload.updated_at;
}}
document.getElementById('apple-library-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const path = document.getElementById('apple-library-path').value.trim();
  const status = document.getElementById('apple-status');
  if (!path) {{ status.textContent = 'Escribe la ruta del XML'; return; }}
  status.textContent = 'Importando…';
  const res = await fetch('/api/import-apple-library', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{path}}),
  }});
  const result = await res.json();
  status.textContent = result.error ? '✗ ' + result.error
    : `✅ Biblioteca importada: ${{result.added}} nuevas, ${{result.skipped}} ya existían`;
  loadData();
}});

document.getElementById('ytmusic-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const status = document.getElementById('ytmusic-status');
  status.textContent = 'Importando…';
  const includePlaylists = document.getElementById('ytmusic-playlists').checked;
  const res = await fetch('/api/import-ytmusic', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{include_playlists: includePlaylists}}),
  }});
  const result = await res.json();
  status.textContent = result.error ? '✗ ' + result.error
    : `✅ YouTube Music: ${{result.added}} nuevas, ${{result.skipped}} ya existían`;
  loadData();
}});

document.getElementById('channel-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const handle = document.getElementById('channel-handle').value.trim();
  const status = document.getElementById('channel-status');
  if (!handle) {{ status.textContent = 'Escribe el handle del canal (p. ej. @KnightPrincessReal)'; return; }}
  status.textContent = 'Importando catálogo…';
  const res = await fetch('/api/import-channel', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{handle}}),
  }});
  const result = await res.json();
  status.textContent = result.error ? '✗ ' + result.error
    : `✅ Catálogo de ${{result.artist}}: ${{result.added}} nuevas, ${{result.skipped}} ya existían`;
  loadData();
}});

(async () => {{
  const res = await fetch('/api/ytmusic-status');
  const status = await res.json();
  const el = document.getElementById('ytmusic-status');
  el.textContent = status.headers
    ? '🔓 autenticado (headers listos)'
    : '🔒 sin autenticar: genera ~/.youber/ytmusic_headers.json (ver docs/MUSIC.md)';
}})();

document.getElementById('config-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const selected = [...document.querySelectorAll('input[name=widget]:checked')]
    .map(cb => cb.value);
  await fetch('/api/config', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{widgets: selected}}),
  }});
  location.reload();
}});

// Importación desde plataforma (Apple/iTunes o Spotify)
function esc(s) {{
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
const cloudStatus = document.getElementById('cloud-status');
document.getElementById('cloud-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const q = document.getElementById('cloud-q').value.trim();
  const source = document.getElementById('cloud-source').value;
  const limit = document.getElementById('cloud-limit').value || 10;
  const box = document.getElementById('cloud-results');
  if (!q) {{ cloudStatus.textContent = 'Escribe una búsqueda'; return; }}
  cloudStatus.textContent = 'Buscando…';
  box.innerHTML = '';
  const params = new URLSearchParams({{q, source, limit}});
  const res = await fetch('/api/search-cloud?' + params.toString());
  const payload = await res.json();
  if (payload.error) {{
    cloudStatus.textContent = '✗ ' + payload.error;
    return;
  }}
  const hits = payload.hits || [];
  if (!hits.length) {{
    cloudStatus.textContent = 'Sin resultados';
    return;
  }}
  cloudStatus.textContent = hits.length + ' resultado(s) — marca y pulsa «Importar»';
  box.innerHTML = hits.map((h, i) => {{
    const meta = [h.artist, h.album, h.duration_s ? Math.round(h.duration_s) + 's' : null]
      .filter(Boolean).join(' · ');
    return '<label class="hit"><input type="checkbox" class="hit-chk" value="' + esc(h.external_id) + '"> '
      + '<strong>' + esc(h.title) + '</strong> <span class="meta">' + esc(meta) + '</span></label>';
  }}).join('') + '<button id="cloud-import">Importar seleccionadas</button>';
  document.getElementById('cloud-import').addEventListener('click', async () => {{
    const ids = [...document.querySelectorAll('.hit-chk:checked')].map(cb => cb.value);
    if (!ids.length) {{ cloudStatus.textContent = 'Marca al menos una pista'; return; }}
    const res2 = await fetch('/api/import-cloud', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{q, source, limit, external_ids: ids}}),
    }});
    const result = await res2.json();
    cloudStatus.textContent = result.error ? '✗ ' + result.error
      : `✅ Importadas: ${{result.added}} nuevas, ${{result.skipped}} ya existían`;
    loadData();
  }});
}});
setInterval(loadData, REFRESH_MS);
loadData();

// ---------------------------------------------------------------------------
// Pestañas
// ---------------------------------------------------------------------------
function switchTab(name) {{
  document.getElementById('tab-dashboard').style.display = name === 'dashboard' ? '' : 'none';
  document.getElementById('tab-tracks').style.display = name === 'tracks' ? '' : 'none';
  document.getElementById('tab-research').style.display = name === 'research' ? '' : 'none';
  document.getElementById('tab-script').style.display = name === 'script' ? '' : 'none';
  document.getElementById('tab-videos').style.display = name === 'videos' ? '' : 'none';
  document.getElementById('tab-btn-dashboard').classList.toggle('active', name === 'dashboard');
  document.getElementById('tab-btn-tracks').classList.toggle('active', name === 'tracks');
  document.getElementById('tab-btn-research').classList.toggle('active', name === 'research');
  document.getElementById('tab-btn-script').classList.toggle('active', name === 'script');
  document.getElementById('tab-btn-videos').classList.toggle('active', name === 'videos');
  if (name === 'tracks') loadTracks();
  if (name === 'videos') loadVideos();
}}

// ---------------------------------------------------------------------------
// Pestaña Canciones
// ---------------------------------------------------------------------------
let tracksAll = [];
let tracksSort = {{key: 'title', dir: 1}};
let tracksFilter = 'all';
const FILTER_LABELS = {{all: 'todas', energetic: '⚡ energéticas', danceable: '💃 bailables', relaxed: '😌 relajadas', positive: '😊 positivas', intense: '🖤 intensas', favorites: '⭐ favoritas'}};

function fmtDuration(s) {{
  if (s == null || isNaN(s)) return '-';
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return m + ':' + String(sec).padStart(2, '0');
}}

function sourceBadge(source) {{
  return '<span class="badge badge-' + esc(source) + '">' + esc(source) + '</span>';
}}

async function loadVideos() {{
  const box = document.getElementById('videos-list');
  const status = document.getElementById('videos-status');
  status.textContent = 'Cargando…';
  try {{
    const res = await fetch('/api/videos');
    const payload = await res.json();
    if (payload.error) {{
      status.textContent = '✗ ' + payload.error;
      return;
    }}
    const videos = payload.videos || [];
    status.textContent = videos.length + ' vídeo(s)';
    if (!videos.length) {{
      box.innerHTML = '<p class="status">Aún no hay vídeos renderizados. Usa la pestaña 🎬 Edición para generar el primero.</p>';
      return;
    }}
    box.innerHTML = videos.map(v => {{
      const mb = (v.size / 1048576).toFixed(1);
      const dur = v.duration ? ' · ' + Math.round(v.duration) + ' s' : '';
      return '<div style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:0.8rem 1rem;margin-bottom:1rem">'
        + '<strong>' + esc(v.name) + '</strong> <span class="status">(' + mb + ' MB' + dur + ')</span>'
        + '<video controls preload="metadata" style="width:100%;max-width:720px;display:block;margin-top:0.6rem;background:#000;border-radius:6px">'
        + '<source src="' + esc(v.url) + '">'
        + 'Tu navegador no soporta la reproducción de vídeo.'
        + '</video>'
        + '</div>';
    }}).join('');
  }} catch (err) {{
    status.textContent = '✗ Error: ' + esc(String(err));
  }}
}}
document.getElementById('research-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const url = document.getElementById('research-url').value.trim();
  const n = document.getElementById('research-n').value || 10;
  const status = document.getElementById('research-status');
  const box = document.getElementById('research-results');
  if (!url) {{ status.textContent = 'Escribe la URL del canal o vídeo'; return; }}
  status.textContent = 'Analizando… (puede tardar unos segundos)';
  box.innerHTML = '';
  try {{
    const res = await fetch('/api/research?url=' + encodeURIComponent(url) + '&n=' + n);
    const payload = await res.json();
    if (payload.error) {{
      status.textContent = '✗ ' + payload.error;
      return;
    }}
    status.textContent = '';
    if (payload.kind === 'video') {{
      renderResearchVideo(payload.video);
    }} else {{
      renderResearchChannel(payload);
    }}
  }} catch (err) {{
    status.textContent = '✗ Error: ' + esc(String(err));
  }}
}});

function renderResearchVideo(video) {{
  const box = document.getElementById('research-results');
  const link = '<a href="' + esc(video.url) + '" target="_blank">' + esc(video.title) + '</a>';
  box.innerHTML = '<div class="controls">'
    + '<strong>🎬 Vídeo:</strong> ' + link
    + '<ul style="margin:0.6rem 0 0 1.2rem">'
    + '<li>Vistas: ' + esc(video.views || '-') + '</li>'
    + '<li>Likes: ' + esc(video.likes || '-') + ' · Comentarios: ' + esc(video.comments || '-') + '</li>'
    + '<li>Duración: ' + esc(video.duration || '-') + ' · Publicado: ' + esc(video.publish_date || '-') + '</li>'
    + '<li>Canal: ' + esc(video.channel_name || '-') + '</li>'
    + (video.hashtags && video.hashtags.length ? '<li>Hashtags: ' + video.hashtags.map(h => '#' + esc(h)).join(' ') + '</li>' : '')
    + '</ul></div>';
}}

function renderResearchChannel(payload) {{
  const box = document.getElementById('research-results');
  const ch = payload.channel;
  const summary = payload.views_summary || {{}};
  const rows = (payload.videos || []).map((v, i) => {{
    const thumb = v.thumbnail_url
      ? '<img src="' + esc(v.thumbnail_url) + '" style="width:120px;height:auto;border-radius:4px" alt="">'
      : '';
    return '<tr>'
      + '<td>' + (i + 1) + '</td>'
      + '<td>' + thumb + '</td>'
      + '<td><a href="' + esc(v.url) + '" target="_blank">' + esc(v.title) + '</a></td>'
      + '<td>' + esc(v.views || '-') + '</td>'
      + '<td>' + esc(v.duration || '-') + '</td>'
      + '<td>' + esc(v.publish_date || '-') + '</td>'
      + '</tr>';
  }}).join('');
  box.innerHTML = '<div class="controls">'
    + '<strong>📺 Canal: ' + esc(ch.name || '') + '</strong>'
    + (ch.handle ? ' · @' + esc(ch.handle) : '')
    + (ch.subscribers ? ' · ' + esc(ch.subscribers) : '')
    + (summary.count ? ' · ' + summary.count + ' vídeo(s) analizados' : '')
    + (summary.avg ? ' · vistas medias ' + summary.avg.toLocaleString('es-ES') : '')
    + (summary.max ? ' · máx ' + summary.max.toLocaleString('es-ES') : '')
    + '</div>'
    + '<div style="overflow-x:auto;background:#fff;border:1px solid #ddd;border-radius:8px">'
    + '<table><thead><tr><th>#</th><th></th><th>Título</th><th>Vistas</th><th>Duración</th><th>Publicado</th></tr></thead>'
    + '<tbody>' + (rows || '<tr><td colspan="6" style="text-align:center;color:#888">Sin vídeos</td></tr>') + '</tbody></table>'
    + '</div>';
}}

// ---------------------------------------------------------------------------
// Pestaña Edición
// ---------------------------------------------------------------------------
document.getElementById('script-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const url = document.getElementById('script-url').value.trim();
  const topic = document.getElementById('script-topic').value.trim() || 'Mi vídeo';
  const duration = document.getElementById('script-duration').value.trim();
  const status = document.getElementById('script-status');
  const box = document.getElementById('script-results');
  if (!url) {{ status.textContent = 'Escribe la URL del canal de referencia'; return; }}
  status.textContent = 'Analizando estructura y generando propuesta…';
  box.innerHTML = '';
  try {{
    let q = '/api/script-proposal?url=' + encodeURIComponent(url) + '&topic=' + encodeURIComponent(topic);
    if (duration) q += '&duration=' + encodeURIComponent(duration);
    const res = await fetch(q);
    const payload = await res.json();
    if (payload.error) {{
      status.textContent = '✗ ' + payload.error;
      return;
    }}
    status.textContent = '';
    renderScriptProposal(payload);
  }} catch (err) {{
    status.textContent = '✗ Error: ' + esc(String(err));
  }}
}});

let currentScript = null;
let scriptMusicTrack = null;

function renderScriptProposal(payload) {{
  currentScript = payload.script;
  const box = document.getElementById('script-results');
  const music = payload.music || {{}};
  const options = music.options || [];
  const suggested = music.suggested_track_id;
  scriptMusicTrack = suggested || null;
  const scenes = (currentScript.scenes || []).map((s, i) =>
    '<tr>'
    + '<td>' + (i + 1) + '</td>'
    + '<td>' + esc(s.type) + '</td>'
    + '<td>' + esc(s.title) + '</td>'
    + '<td>' + s.duration + ' s</td>'
    + '<td>' + esc(s.text) + '</td>'
    + '<td>' + esc(s.transition) + '</td>'
    + '</tr>').join('');
  const musicOptions = options.map(t => {{
    const label = esc(t.title) + (t.artist ? ' — ' + esc(t.artist) : '')
      + (t.genre ? ' · ' + esc(t.genre) : '')
      + (t.duration ? ' · ' + t.duration + ' s' : '')
      + (t.id === suggested ? ' ⭐ sugerida' : '');
    return '<label style="display:block;margin:0.2rem 0">'
      + '<input type="radio" name="script-music" value="' + esc(t.id) + '"'
      + (t.id === suggested ? ' checked' : '') + '> '
      + label + '</label>';
  }}).join('');
  box.innerHTML = '<div class="controls">'
    + '<strong>🎬 Propuesta para: ' + esc(currentScript.topic) + '</strong>'
    + (payload.channel ? ' · canal de referencia: ' + esc(payload.channel) : '')
    + ' · duración total: ' + currentScript.total_duration + ' s'
    + (music.suggested_mood ? ' · música sugerida: ' + esc(music.suggested_mood) : '')
    + '</div>'
    + '<div style="overflow-x:auto;background:#fff;border:1px solid #ddd;border-radius:8px;margin-bottom:1rem">'
    + '<table><thead><tr><th>#</th><th>Tipo</th><th>Título</th><th>Duración</th><th>Texto</th><th>Transición</th></tr></thead>'
    + '<tbody>' + (scenes || '<tr><td colspan="6" style="text-align:center;color:#888">Sin escenas</td></tr>') + '</tbody></table>'
    + '</div>'
    + '<div class="controls">'
    + '<strong>🎵 Música (solo pistas locales de tu catálogo):</strong>'
    + (options.length
        ? '<div style="margin:0.4rem 0">' + musicOptions + '</div>'
        : '<p class="status">No hay pistas locales indexadas. Añade tus ficheros de audio a la carpeta music/ y vuelve a intentarlo (son metadatos cloud los que no sirven).</p>')
    + '<label style="display:block;margin-top:0.5rem"><strong>🎞️ Tus clips de vídeo</strong> (opcional — deja vacío para usar stock):</label>'
    + '<input type="text" id="script-clips" placeholder="intro.mp4, escena1.mp4, escena2.mp4 (vacío = clips de stock)" style="min-width:320px;margin-top:0.3rem">'
    + '<label style="display:block;margin-top:0.5rem"><input type="checkbox" id="script-stock"> '
    + '🆓 Descargar clips de stock automáticamente (Pexels/Pixabay)'
    + (payload.stock && (payload.stock.pexels || payload.stock.pixabay) ? '' : ' <em>(sin key: configura PEXELS_API_KEY en el entorno)</em>')
    + '</label>'
    + '<label style="display:block;margin-top:0.3rem"><input type="checkbox" id="script-texts"> '
    + '📝 Superponer textos de escena (aviso: los textos son instrucciones de edición, no texto para el espectador)'
    + '</label>'
    + '<div style="margin-top:0.8rem">'
    + '<button onclick="approveScript()">✅ Visto bueno — editar y renderizar</button>'
    + '<span id="script-render-status" class="status"></span>'
    + '</div>'
    + '</div>';
  box.querySelectorAll('input[name="script-music"]').forEach(r => {{
    r.addEventListener('change', () => {{ scriptMusicTrack = r.value; }});
  }});
}}

async function approveScript() {{
  const status = document.getElementById('script-render-status');
  const useStock = document.getElementById('script-stock') && document.getElementById('script-stock').checked;
  const showTexts = document.getElementById('script-texts') && document.getElementById('script-texts').checked;
  const clips = document.getElementById('script-clips').value
    .split(',').map(c => c.trim()).filter(Boolean);
  if (!clips.length && !useStock) {{
    status.textContent = '✗ Indica al menos un clip de vídeo propio o marca clips de stock';
    return;
  }}
  status.textContent = useStock && !clips.length
    ? '🆓 Descargando clips de stock y renderizando… (puede tardar)'
    : 'Renderizando… (puede tardar un rato)';
  try {{
    const res = await fetch('/api/script/render', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        script: currentScript,
        clips: clips,
        music_track_id: scriptMusicTrack,
        use_stock: useStock,
        show_texts: showTexts,
      }}),
    }});
    const result = await res.json();
    if (result.error) {{
      status.textContent = '✗ ' + result.error;
      return;
    }}
    status.textContent = '✅ Vídeo final: ' + esc(result.output)
      + ' (' + result.clips + ' clips, ' + result.texts + ' textos'
      + (result.music_track_id ? ', música incluida' : ', sin música local') + ')';
  }} catch (err) {{
    status.textContent = '✗ Error: ' + esc(String(err));
  }}
}}

async function loadTracks() {{
  const q = document.getElementById('tracks-q').value.trim();
  const res = await fetch('/api/tracks' + (q ? '?q=' + encodeURIComponent(q) : ''));
  const payload = await res.json();
  if (payload.error) {{
    document.getElementById('tracks-count').textContent = '✗ ' + payload.error;
    return;
  }}
  tracksAll = payload.tracks || [];
  renderTracks();
}}

function exportTracks(fmt) {{
  const list = currentTracks();
  if (fmt === 'csv') {{
    const head = ['Título','Artista','Álbum','Duración (s)','Género','Energía','Baile','Ánimo','Tempo','Fuente','Favorita'];
    const rows = list.map(t => [t.title, t.artist || '', t.album || '', t.duration ?? '', t.genre || '',
      t.energy != null ? Math.round(t.energy * 100) + '%' : '',
      t.danceability != null ? Math.round(t.danceability * 100) + '%' : '',
      t.valence != null ? Math.round(t.valence * 100) + '%' : '',
      t.tempo ?? '', t.source || '', t.favorite ? 'sí' : 'no']
      .map(c => '"' + String(c).replace(/"/g, '""') + '"'));
    const csv = '\\uFEFF' + [head, ...rows].map(r => r.join(';')).join('\\r\\n');
    downloadFile('canciones.csv', csv, 'text/csv;charset=utf-8');
  }} else {{
    const out = list.map(t => ({{
      title: t.title, artist: t.artist, album: t.album, duration_s: t.duration,
      genre: t.genre, energy: t.energy, danceability: t.danceability,
      valence: t.valence, tempo: t.tempo, source: t.source, favorite: t.favorite,
    }}));
    downloadFile('canciones.json', JSON.stringify(out, null, 2), 'application/json');
  }}
}}

function downloadFile(name, content, mime) {{
  const blob = new Blob([content], {{type: mime}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {{ URL.revokeObjectURL(a.href); a.remove(); }}, 500);
}}

function setTrackFilter(f) {{
  tracksFilter = f;
  document.querySelectorAll('#tracks-filters .filter-btn').forEach(btn => {{
    btn.classList.toggle('active', btn.dataset.filter === f);
  }});
  renderTracks();
}}

function currentTracks() {{
  let list = tracksAll;
  if (tracksFilter === 'energetic') list = list.filter(t => (t.energy || 0) >= 0.7);
  else if (tracksFilter === 'danceable') list = list.filter(t => (t.danceability || 0) >= 0.6);
  else if (tracksFilter === 'relaxed') list = list.filter(t => (t.energy || 0) < 0.5 && (t.tempo || 0) < 110);
  else if (tracksFilter === 'positive') list = list.filter(t => (t.valence || 0) >= 0.6);
  else if (tracksFilter === 'intense') list = list.filter(t => (t.valence || 0) < 0.4);
  else if (tracksFilter === 'favorites') list = list.filter(t => t.favorite);
  const key = tracksSort.key, dir = tracksSort.dir;
  return [...list].sort((a, b) => {{
    let va = a[key], vb = b[key];
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va == null) va = '';
    if (vb == null) vb = '';
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return 0;
  }});
}}

function renderTracks() {{
  const sorted = currentTracks();
  const tbody = document.getElementById('tracks-body');
  document.getElementById('tracks-count').textContent =
    sorted.length + ' canción(es)'
    + (tracksFilter !== 'all' ? ' · filtro: ' + FILTER_LABELS[tracksFilter] : '')
    + (tracksSort.key !== 'title' ? ' · orden: ' + tracksSort.key : '');
  tbody.innerHTML = sorted.map(t => {{
    const fav = t.favorite ? '⭐' : '☆';
    const bar = (v) => {{
      if (v == null) return '<span class="dim">-</span>';
      const pct = Math.round(v * 100);
      const color = pct >= 70 ? '#2e7d32' : pct >= 40 ? '#f9a825' : '#c62828';
      return '<span style="color:' + color + '">' + pct + '%</span>';
    }};
    return '<tr>'
      + '<td>' + esc(t.title) + '</td>'
      + '<td>' + esc(t.artist || '-') + '</td>'
      + '<td>' + esc(t.album || '-') + '</td>'
      + '<td>' + fmtDuration(t.duration) + '</td>'
      + '<td>' + esc(t.genre || '-') + '</td>'
      + '<td>' + bar(t.energy) + '</td>'
      + '<td>' + bar(t.danceability) + '</td>'
      + '<td>' + bar(t.valence) + '</td>'
      + '<td>' + (t.tempo || '-') + '</td>'
      + '<td>' + sourceBadge(t.source) + '</td>'
      + '<td><button class="fav" data-id="' + esc(t.id) + '" title="Marcar favorita">' + fav + '</button></td>'
      + '<td>' + t.usage_count + '</td>'
      + '<td><button class="sim" data-id="' + esc(t.id) + '" title="Recomendar similares por sonido">🎯</button></td>'
      + '</tr>';
  }}).join('') || '<tr><td colspan="13" style="text-align:center;color:#888">Sin canciones en el catálogo</td></tr>';

  tbody.querySelectorAll('.fav').forEach(btn => {{
    btn.addEventListener('click', async () => {{
      const res = await fetch('/api/tracks/favorite', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{track_id: btn.dataset.id}}),
      }});
      const result = await res.json();
      if (result.error) {{
        alert('✗ ' + result.error);
        return;
      }}
      loadTracks();
    }});
  }});
  tbody.querySelectorAll('.sim').forEach(btn => {{
    btn.addEventListener('click', () => recommendFor(btn.dataset.id));
  }});
}}

async function recommendFor(trackId) {{
  const box = document.getElementById('recommend-results');
  box.innerHTML = '<span class="dim">Buscando similares…</span>';
  try {{
    const res = await fetch('/api/recommend?track_id=' + encodeURIComponent(trackId) + '&limit=5');
    const payload = await res.json();
    if (payload.error) {{
      box.innerHTML = '<span style="color:#c62828">✗ ' + esc(payload.error) + '</span>';
      return;
    }}
    const t = payload.target;
    const rows = (payload.recommendations || []).map(r => {{
      const bar = (v) => {{
        if (v == null) return '-';
        const pct = Math.round(v * 100);
        const color = pct >= 70 ? '#2e7d32' : pct >= 40 ? '#f9a825' : '#c62828';
        return '<span style="color:' + color + '">' + pct + '%</span>';
      }};
      return '<tr>'
        + '<td>' + r.rank + '</td>'
        + '<td>' + esc(r.track_title) + '</td>'
        + '<td>' + esc(r.artist || '-') + '</td>'
        + '<td>' + Math.round(r.score * 100) + '%</td>'
        + '<td>' + bar(r.energy) + '</td>'
        + '<td>' + bar(r.danceability) + '</td>'
        + '<td>' + bar(r.valence) + '</td>'
        + '<td>' + (r.tempo || '-') + '</td>'
        + '</tr>';
    }}).join('');
    box.innerHTML = '<div class="controls" style="margin-top:1rem">'
      + '<strong>🎯 Similares a «' + esc(t.track_title) + '»' + (t.artist ? ' — ' + esc(t.artist) : '') + ':</strong>'
      + '<table><thead><tr><th>#</th><th>Título</th><th>Artista</th><th>Similitud</th><th>Energía</th><th>Baile</th><th>Ánimo</th><th>BPM</th></tr></thead>'
      + '<tbody>' + (rows || '<tr><td colspan="8" style="text-align:center;color:#888">Sin coincidencias</td></tr>') + '</tbody></table>'
      + '</div>';
  }} catch (err) {{
    box.innerHTML = '<span style="color:#c62828">✗ Error: ' + esc(String(err)) + '</span>';
  }}
}}

async function savePlaylist() {{
  const input = document.getElementById('playlist-name');
  const name = input.value.trim();
  if (!name) {{
    alert('Escribe un nombre para la playlist');
    return;
  }}
  const ids = currentTracks().map(t => t.id);
  if (!ids.length) {{
    alert('La selección actual está vacía');
    return;
  }}
  const res = await fetch('/api/playlists', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{name: name, track_ids: ids}}),
  }});
  const result = await res.json();
  if (result.error) {{
    alert('✗ ' + result.error);
    return;
  }}
  input.value = '';
  loadPlaylists();
}}

async function loadPlaylists() {{
  const box = document.getElementById('playlists-list');
  const res = await fetch('/api/playlists');
  const payload = await res.json();
  if (payload.error) {{
    box.innerHTML = '<span style="color:#c62828">✗ ' + esc(payload.error) + '</span>';
    return;
  }}
  const playlists = payload.playlists || [];
  document.getElementById('playlists-count').textContent =
    playlists.length + ' playlist(s)';
  box.innerHTML = playlists.map(p => {{
    const tracks = (p.tracks || []).map(t =>
      '<li>' + esc(t.title) + (t.artist ? ' — ' + esc(t.artist) : '')
      + (t.genre ? ' <span class="dim">(' + esc(t.genre) + ')</span>' : '')
      + (t.energy != null ? ' · ⚡' + Math.round(t.energy * 100) + '%' : '')
      + (t.tempo ? ' · ' + t.tempo + ' BPM' : '') + '</li>').join('');
    return '<div style="border:1px solid #ddd;border-radius:8px;padding:0.6rem 1rem;margin-top:0.6rem">'
      + '<strong>' + esc(p.name) + '</strong> <span class="dim">(' + p.track_count + ' canciones)</span>'
      + '<button class="fav" onclick="deletePlaylist(\\'' + esc(p.id) + '\\')" title="Eliminar playlist">🗑</button>'
      + (tracks ? '<ul style="margin:0.4rem 0 0 1.2rem">' + tracks + '</ul>' : '')
      + '</div>';
  }}).join('') || '<p class="dim" style="margin-top:0.5rem">Aún no hay playlists guardadas.</p>';
}}

async function deletePlaylist(id) {{
  if (!confirm('¿Eliminar esta playlist?')) return;
  const res = await fetch('/api/playlists/delete', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{playlist_id: id}}),
  }});
  const result = await res.json();
  if (result.error) {{
    alert('✗ ' + result.error);
    return;
  }}
  loadPlaylists();
}}

function sortTracks(key) {{
  if (tracksSort.key === key) {{
    tracksSort.dir *= -1;
  }} else {{
    tracksSort.key = key;
    tracksSort.dir = 1;
  }}
  renderTracks();
}}
</script>
</body>
</html>
"""


def make_handler(dashboard_app: DashboardApp) -> type[BaseHTTPRequestHandler]:
    """Crea la clase handler del servidor HTTP con la app inyectada."""

    class DashboardHandler(BaseHTTPRequestHandler):
        """Sirve la página del dashboard y sus endpoints JSON."""

        app = dashboard_app

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug(f"[dashboard] {self.address_string()} {format % args}")

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/data":
                self._send_json(self.app.data_payload())
                return
            if self.path.startswith("/api/search-cloud"):
                self._handle_search_cloud()
                return
            if self.path == "/api/ytmusic-status":
                self._send_json(self.app.ytmusic_status())
                return
            if self.path.startswith("/api/tracks"):
                self._handle_tracks()
                return
            if self.path.startswith("/api/recommend"):
                self._handle_recommend()
                return
            if self.path == "/api/playlists":
                self._send_json({"playlists": self.app.list_playlists()})
                return
            if self.path.startswith("/api/research"):
                self._handle_research()
                return
            if self.path.startswith("/api/script-proposal"):
                self._handle_script_proposal()
                return
            if self.path == "/api/videos":
                self._send_json({"videos": self.app.videos()})
                return
            if self.path.startswith("/media/"):
                self._handle_media(self.path)
                return
            body = self.app.render_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle_tracks(self) -> None:
            """Lista las canciones del catálogo (filtro opcional ``?q=``)."""
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(self.path).query)
            values = query.get("q")
            q = values[0] if values else None
            try:
                self._send_json({"tracks": self.app.tracks(query=q)})
            except Exception as exc:
                logger.warning(f"Error en /api/tracks: {exc}")
                self._send_json({"error": str(exc)}, status=400)

        def _handle_recommend(self) -> None:
            """Recomienda canciones similares por audio (?track_id=X&limit=N)."""
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(self.path).query)
            track_id = (query.get("track_id") or [""])[0]
            limit = int((query.get("limit") or ["5"])[0])
            try:
                self._send_json(self.app.recommend(track_id, limit=limit))
            except Exception as exc:
                logger.warning(f"Error en /api/recommend: {exc}")
                self._send_json({"error": str(exc)}, status=500)

        def _handle_research(self) -> None:
            """Analiza un canal/vídeo de YouTube (?url=...&n=...)."""
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(self.path).query)
            url = (query.get("url") or [""])[0].strip()
            n = int((query.get("n") or ["10"])[0])
            if not url:
                self._send_json({"error": "Parámetro url requerido"}, status=400)
                return
            try:
                self._send_json(asyncio.run(self.app.research(url, max_videos=n)))
            except Exception as exc:
                logger.warning(f"Error en /api/research: {exc}")
                self._send_json({"error": str(exc)}, status=500)

        def _handle_script_proposal(self) -> None:
            """Propone guion + música local (?url=...&topic=...&duration=...)."""
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(self.path).query)
            url = (query.get("url") or [""])[0].strip()
            topic = (query.get("topic") or ["Mi vídeo"])[0].strip()
            duration_raw = (query.get("duration") or [""])[0]
            n = int((query.get("n") or ["10"])[0])
            duration = float(duration_raw) if duration_raw else None
            if not url:
                self._send_json({"error": "Parámetro url requerido"}, status=400)
                return
            try:
                self._send_json(
                    asyncio.run(
                        self.app.script_proposal(
                            url, topic=topic, duration=duration, max_videos=n
                        )
                    )
                )
            except Exception as exc:
                logger.warning(f"Error en /api/script-proposal: {exc}")
                self._send_json({"error": str(exc)}, status=500)

        def _handle_script_render(self) -> None:
            """Renderiza el vídeo aprobado (body: script, clips, music_track_id, use_stock, show_texts)."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                script = body.get("script")
                clips = [str(c) for c in body.get("clips", [])]
                music_track_id = body.get("music_track_id")
                use_stock = bool(body.get("use_stock", False))
                show_texts = bool(body.get("show_texts", False))
                if not script:
                    self._send_json({"error": "Parámetro script requerido"}, status=400)
                    return
                self._send_json(
                    asyncio.run(
                        self.app.script_render(
                            script,
                            clips,
                            music_track_id,
                            use_stock=use_stock,
                            show_texts=show_texts,
                        )
                    )
                )
            except ValueError as exc:
                logger.warning(f"Error en POST /api/script/render: {exc}")
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                logger.warning(f"Error en POST /api/script/render: {exc}")
                self._send_json({"error": str(exc)}, status=500)

        def _handle_media(self, path: str) -> None:
            """Sirve un vídeo renderizado desde el directorio de salida."""
            from pathlib import Path as _Path
            from urllib.parse import unquote

            name = unquote(path.split("/media/", 1)[-1])
            base = _Path("reports").resolve()
            target = (base / name).resolve()
            # Protección: solo dentro de reports/ y solo extensiones de vídeo.
            if not str(target).startswith(str(base)) or target.suffix.lower() not in (
                ".mp4",
                ".mkv",
                ".webm",
                ".mov",
            ):
                self._send_json({"error": "no encontrado"}, status=404)
                return
            if not target.exists():
                self._send_json({"error": "no encontrado"}, status=404)
                return
            content_type = {
                ".mp4": "video/mp4",
                ".mkv": "video/x-matroska",
                ".webm": "video/webm",
                ".mov": "video/quicktime",
            }[target.suffix.lower()]
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(data)

        def _handle_create_playlist(self) -> None:
            """Crea una playlist (body: name, track_ids)."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                name = str(body.get("name", "")).strip()
                track_ids = [str(x) for x in body.get("track_ids", [])]
                if not name or not track_ids:
                    self._send_json(
                        {"error": "Parámetros name y track_ids requeridos"}, status=400
                    )
                    return
                self._send_json(self.app.create_playlist(name, track_ids))
            except Exception as exc:
                logger.warning(f"Error en POST /api/playlists: {exc}")
                self._send_json({"error": str(exc)}, status=500)

        def _handle_delete_playlist(self) -> None:
            """Elimina una playlist (body: playlist_id)."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                playlist_id = str(body.get("playlist_id", "")).strip()
                if not playlist_id:
                    self._send_json({"error": "Parámetro playlist_id requerido"}, status=400)
                    return
                self._send_json(self.app.delete_playlist(playlist_id))
            except Exception as exc:
                logger.warning(f"Error en POST /api/playlists/delete: {exc}")
                self._send_json({"error": str(exc)}, status=500)

        def _handle_search_cloud(self) -> None:
            """Busca en Apple/Spotify y devuelve resultados JSON (sin importar)."""
            from urllib.parse import parse_qs, urlparse

            try:
                query = parse_qs(urlparse(self.path).query)
                q = (query.get("q") or [""])[0].strip()
                source = (query.get("source") or ["apple"])[0]
                limit = int((query.get("limit") or ["10"])[0])
                if not q:
                    self._send_json({"error": "Parámetro q (búsqueda) requerido"}, status=400)
                    return
                payload = asyncio.run(self.app.search_cloud(q, source, limit))
                self._send_json(payload)
            except Exception as exc:
                logger.warning(f"Error en /api/search-cloud: {exc}")
                self._send_json({"error": str(exc)}, status=400)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/config":
                self._handle_config()
                return
            if self.path == "/api/import-cloud":
                self._handle_import_cloud()
                return
            if self.path == "/api/import-ytmusic":
                self._handle_import_ytmusic()
                return
            if self.path == "/api/import-channel":
                self._handle_import_channel()
                return
            if self.path == "/api/tracks/favorite":
                self._handle_toggle_favorite()
                return
            if self.path == "/api/import-apple-library":
                self._handle_import_apple_library()
                return
            if self.path == "/api/playlists":
                self._handle_create_playlist()
                return
            if self.path == "/api/script/render":
                self._handle_script_render()
                return
            if self.path == "/api/playlists/delete":
                self._handle_delete_playlist()
                return
            self._send_json({"error": "no encontrado"}, status=404)

        def _handle_import_channel(self) -> None:
            """Importa el catálogo público de un artista/canal (body: handle)."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                handle = str(body.get("handle", "")).strip()
                if not handle:
                    self._send_json({"error": "Parámetro handle requerido (p. ej. @KnightPrincessReal)"}, status=400)
                    return
                summary = asyncio.run(self.app.channel_import(handle))
                self._send_json({"ok": True, **summary})
            except Exception as exc:
                logger.warning(f"Error en POST /api/import-channel: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_toggle_favorite(self) -> None:
            """Marca/desmarca una canción como favorita (body: track_id)."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                track_id = str(body.get("track_id", "")).strip()
                if not track_id:
                    self._send_json({"error": "track_id requerido"}, status=400)
                    return
                result = self.app.toggle_favorite(track_id)
                if "error" in result:
                    self._send_json(result, status=404)
                    return
                self._send_json(result)
            except Exception as exc:
                logger.warning(f"Error en POST /api/tracks/favorite: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_import_ytmusic(self) -> None:
            """Importa la biblioteca de YouTube Music (Me gusta + guardadas + playlists)."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8")) if raw else {}
                include_playlists = bool(body.get("include_playlists", True))
                summary = asyncio.run(
                    self.app.ytmusic_import(include_playlists=include_playlists)
                )
                self._send_json({"ok": True, **summary})
            except Exception as exc:
                logger.warning(f"Error en POST /api/import-ytmusic: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_import_apple_library(self) -> None:
            """Importa un XML de biblioteca de Apple al catálogo."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                path = str(body.get("path", "")).strip()
                if not path:
                    self._send_json({"error": "Parámetro path (ruta del XML) requerido"}, status=400)
                    return
                summary = asyncio.run(self.app.import_apple_library(path))
                self._send_json({"ok": True, **summary})
            except FileNotFoundError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=404)
            except Exception as exc:
                logger.warning(f"Error en POST /api/import-apple-library: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_config(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                widgets = body.get("widgets", self.app.widgets)
                self.app.widgets = [
                    widget for widget in widgets if widget in WidgetType._value2member_map_
                ]
                save_config(
                    {
                        "widgets": self.app.widgets,
                        "refresh_seconds": self.app.refresh_seconds,
                        "port": self.app.port,
                    },
                    self.app.config_path,
                )
                self._send_json({"ok": True, "widgets": self.app.widgets})
            except Exception as exc:  # pragma: no cover - defensivo
                logger.warning(f"Error en POST /api/config: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

        def _handle_import_cloud(self) -> None:
            """Importa al catálogo las pistas seleccionadas de una plataforma."""
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                q = str(body.get("q", "")).strip()
                source = str(body.get("source", "apple"))
                limit = int(body.get("limit", 10))
                external_ids = body.get("external_ids")
                if not q:
                    self._send_json({"error": "Parámetro q (búsqueda) requerido"}, status=400)
                    return
                summary = asyncio.run(
                    self.app.import_cloud(
                        q, source, limit=limit, external_ids=external_ids
                    )
                )
                self._send_json({"ok": True, **summary})
            except Exception as exc:
                logger.warning(f"Error en POST /api/import-cloud: {exc}")
                self._send_json({"ok": False, "error": str(exc)}, status=400)

    return DashboardHandler


def serve(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    widgets: list[str] | None = None,
    refresh_seconds: int | None = None,
    port: int | None = None,
    open_browser: bool = True,
    host: str = "127.0.0.1",
    library_dir: str | Path = "music",
) -> None:
    """Arranca el servidor web del dashboard (bloqueante hasta Ctrl+C).

    Args:
        config_path: Fichero de configuración (widgets, refresco, puerto).
        widgets: Selección de widgets (sobreescribe la config).
        refresh_seconds: Segundos entre actualizaciones automáticas.
        port: Puerto local (por defecto 8787, desde la config).
        open_browser: Abre el navegador automáticamente.
        host: Interfaz donde escuchar (por defecto solo local).
        library_dir: Directorio del catálogo de música (para importar
            desde plataformas y para el widget catalog-stats).
    """
    app = DashboardApp(
        config_path=config_path,
        widgets=widgets,
        refresh_seconds=refresh_seconds,
        port=port,
        library_dir=library_dir,
    )
    save_config(
        {
            "widgets": app.widgets,
            "refresh_seconds": app.refresh_seconds,
            "port": app.port,
        },
        app.config_path,
    )
    server = ThreadingHTTPServer((host, app.port), make_handler(app))
    url = f"http://{host}:{server.server_address[1]}"
    logger.info(f"Dashboard en {url} (Ctrl+C para parar)")
    print(f"📊 Dashboard en {url}")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=[url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Servidor del dashboard parado")
    finally:
        server.server_close()
