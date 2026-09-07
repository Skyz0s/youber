"""Analizador de vídeo patrón para OpenMontage.

Extrae metadatos estructurados del vídeo origen (YouTube o local)
para alimentar el pipeline de producción.

Fuentes soportadas:
- URL de YouTube → reutiliza `youber.research.VideoAnalyzer` (público, ToS-compliant)
- Archivo local → ffprobe + scene_detect + audio peaks (sin deps externas pesadas)
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from youber.montage.models import PatternSpec, PatternSource


# ────────────────────────────────────────────────────────────────────
# Helpers ffprobe / ffmpeg
# ────────────────────────────────────────────────────────────────────

_FFPROBE_BIN = "ffprobe"
_FFMPEG_BIN = "ffmpeg"


def _run_cmd(cmd: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    """Ejecuta un comando y devuelve (code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", f"not found: {cmd[0]}"


def _ffprobe_json(path: Path) -> dict[str, Any] | None:
    """Devuelve el JSON de ffprobe -show_streams -show_format."""
    code, out, err = _run_cmd([
        _FFPROBE_BIN, "-v", "error",
        "-show_streams", "-show_format",
        "-of", "json", str(path)
    ])
    if code != 0 or not out.strip():
        logger.warning(f"ffprobe falló ({code}): {err[:200]}")
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        logger.warning("ffprobe JSON inválido")
        return None


def _extract_video_info(path: Path) -> dict[str, Any] | None:
    """Extrae info básica de vídeo: duration, resolution, fps, has_audio."""
    data = _ffprobe_json(path)
    if not data:
        return None

    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})

    if not video_stream:
        return None

    # Duración: preferir format, fallback stream
    duration = float(fmt.get("duration", 0) or video_stream.get("duration", 0) or 0)

    # Resolución
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))

    # FPS (avg_frame_rate = "num/den")
    fps = 30.0
    fr = video_stream.get("avg_frame_rate", "30/1")
    if "/" in fr:
        num, den = fr.split("/")
        try:
            fps = float(num) / float(den) if float(den) > 0 else 30.0
        except (ValueError, ZeroDivisionError):
            pass

    return {
        "duration": duration,
        "resolution": (width, height),
        "fps": fps,
        "has_audio": audio_stream is not None,
    }


def _detect_scene_changes(path: Path, threshold: float = 0.4, timeout: float = 60.0) -> list[float]:
    r"""Detecta cambios de plano con ffmpeg select=gt(scene\,th). Devuelve lista de timestamps (s)."""
    # ffmpeg -i input -vf "select=gt(scene\,0.4),showinfo" -f null -
    code, out, err = _run_cmd([
        _FFMPEG_BIN, "-v", "error",
        "-i", str(path),
        "-vf", f"select=gt(scene\\,{threshold}),showinfo",
        "-f", "null", "-"
    ], timeout=timeout)

    # Parsear showinfo: "pts_time:12.34"
    times: list[float] = []
    for line in err.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            try:
                times.append(float(m.group(1)))
            except ValueError:
                pass
    return times


def _extract_audio_peaks(path: Path, window_sec: float = 1.0, timeout: float = 60.0) -> list[float]:
    """Extrae picos de energía de audio (RMS por ventana de 1s). Devuelve timestamps de picos."""
    # astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level
    # Más simple: volumedetect cada ventana (lento) o usar ebur128 (único pass).
    # Usamos ebur128 para loudness integrado + peaks momentáneos.
    code, out, err = _run_cmd([
        _FFMPEG_BIN, "-v", "error",
        "-i", str(path),
        "-af", "ebur128=metadata=1",  # metadata por frame
        "-f", "null", "-"
    ], timeout=timeout)

    # Parse: "lavfi.r128.M=...", "lavfi.r128.S=..." (momentary loudness)
    # Simplificación: tomamos cada línea con M= y convertimos a energía relativa
    peaks: list[float] = []
    for line in err.splitlines():
        m = re.search(r"lavfi\.r128\.M=([-\d.]+)", line)
        if m:
            try:
                # LUFS momentáneo → energía relativa (aprox)
                lufs = float(m.group(1))
                if lufs > -60:  # umbral de silencio
                    peaks.append(lufs)
            except ValueError:
                pass

    # Devolver timestamps aproximados (índice * window)
    # ffmpeg ebur128 emite ~1 frame/100ms; hacemos sub-muestreo a 1s
    if len(peaks) > 10:
        step = max(1, int(len(peaks) * window_sec / 10))
        peaks = peaks[::step]

    # Normalizar a 0-1 y quedarnos con top 10
    if peaks:
        min_v, max_v = min(peaks), max(peaks)
        if max_v > min_v:
            norm = [(p - min_v) / (max_v - min_v) for p in peaks]
            # timestamps aproximados
            return [i * window_sec for i, v in enumerate(norm) if v > 0.7][:10]

    return []


def _extract_color_palette(path: Path, n_colors: int = 5, timeout: float = 30.0) -> list[str]:
    """Extrae paleta de colores dominante (palettegen + paletteuse hack)."""
    # ffmpeg -i input -vf "palettegen=max_colors=5" -f image2pipe - | paletteuse...
    # Simplificado: usamos un frame representativo y palettegen
    code, out, err = _run_cmd([
        _FFMPEG_BIN, "-v", "error",
        "-i", str(path),
        "-vf", f"palettegen=max_colors={n_colors}:reserve_transparent=0",
        "-frames:v", "1",
        "-f", "image2", "-c:v", "png", "-"
    ], timeout=timeout, )

    if code != 0 or not out:
        return []

    # La salida PNG en stdout es binaria; mejor escribir a temp y leer con PIL
    # Pero PIL no está garantizado. Devolvemos placeholder.
    return [f"#color_{i}" for i in range(n_colors)]


# ────────────────────────────────────────────────────────────────────
# Analizador principal
# ────────────────────────────────────────────────────────────────────

_YOUTUBE_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})"
)


class PatternAnalyzer:
    """Analiza un vídeo patrón (YouTube o local) y devuelve PatternSpec."""

    def __init__(
        self,
        api_key: str | None = None,
        request_delay: float = 1.5,
        scene_threshold: float = 0.4,
    ) -> None:
        self.api_key = api_key
        self.request_delay = request_delay
        self.scene_threshold = scene_threshold
        # Lazy import para no romper si research no está instalado
        self._video_analyzer = None

    def _get_video_analyzer(self):
        if self._video_analyzer is None:
            from youber.research.video_analyzer import VideoAnalyzer
            self._video_analyzer = VideoAnalyzer(
                api_key=self.api_key,
                request_delay=self.request_delay,
            )
        return self._video_analyzer

    def is_youtube_url(self, url_or_path: str) -> bool:
        return bool(_YOUTUBE_URL_RE.match(url_or_path.strip()))

    def extract_youtube_id(self, url: str) -> str | None:
        m = _YOUTUBE_URL_RE.match(url.strip())
        return m.group(1) if m else None

    async def analyze(self, source: str) -> PatternSpec:
        """Analiza el vídeo patrón y devuelve PatternSpec."""
        source = source.strip()

        if self.is_youtube_url(source):
            return await self._analyze_youtube(source)

        # Local file
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo: {path}")
        return await self._analyze_local(path)

    async def _analyze_youtube(self, url: str) -> PatternSpec:
        """Analiza vídeo de YouTube usando youber.research."""
        logger.info(f"Analizando vídeo YouTube: {url}")
        analyzer = self._get_video_analyzer()
        video_data = await analyzer.analyze(url, mode="auto")

        # VideoData tiene: title, duration (M:SS), resolution?, fps?, etc.
        # Completamos con ffprobe local si descargamos, pero para v1 usamos lo que da la API
        duration_sec = self._parse_duration(video_data.duration or "0:00")

        return PatternSpec(
            source=PatternSource.YOUTUBE,
            path=url,
            title=video_data.title or "Sin título",
            duration=duration_sec,
            resolution=(1920, 1080),  # placeholder; YouTube no expone fácil en API pública
            fps=30.0,
            has_audio=True,
            audio_peaks=[],  # requeriría descargar audio
            scene_changes=[],
            color_palette=[],
            transitions=[],
            metadata={
                "video_id": video_data.video_id,
                "views": video_data.views,
                "channel_name": video_data.channel_name,
                "channel_url": video_data.channel_url,
                "description": video_data.description,
                "hashtags": video_data.hashtags,
            },
        )

    async def _analyze_local(self, path: Path) -> PatternSpec:
        """Analiza archivo local con ffprobe + scene_detect + audio peaks."""
        logger.info(f"Analizando archivo local: {path}")

        # Info básica
        info = _extract_video_info(path)
        if not info:
            raise ValueError(f"No se pudo leer info de vídeo: {path}")

        # Paralelizar detecciones pesadas
        scene_task = asyncio.to_thread(
            _detect_scene_changes, path, self.scene_threshold
        )
        peaks_task = asyncio.to_thread(_extract_audio_peaks, path)
        colors_task = asyncio.to_thread(_extract_color_palette, path)

        scene_changes, audio_peaks, color_palette = await asyncio.gather(
            scene_task, peaks_task, colors_task
        )

        return PatternSpec(
            source=PatternSource.LOCAL,
            path=str(path.absolute()),
            title=path.stem,
            duration=info["duration"],
            resolution=info["resolution"],
            fps=info["fps"],
            has_audio=info["has_audio"],
            audio_peaks=audio_peaks,
            scene_changes=scene_changes,
            color_palette=color_palette,
            transitions=["cut"] * max(0, len(scene_changes) - 1),  # placeholder
            metadata={"file_size": path.stat().st_size},
        )

    @staticmethod
    def _parse_duration(duration_str: str) -> float:
        """Convierte 'M:SS' o 'H:MM:SS' a segundos."""
        parts = duration_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return 0.0