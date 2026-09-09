"""Renderizado de subtítulos sincronizados sobre vídeo (FFmpeg + libass).

Convierte un :class:`LyricsDocument` temporizado (o un fichero .lrc/.srt/
.json) en subtítulos quemados sobre el vídeo usando el filtro ``subtitles``
de FFmpeg (libass), que maneja el ajuste de línea y la tipografía.

En Windows se pasa ``fontsdir=C:/Windows/Fonts`` para que libass encuentre
fuentes sin depender de fontconfig, y por defecto se usa ``Arial``.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from youber.audio._ffmpeg import ensure_ffmpeg, probe_duration
from youber.sync.timestamps import (
    LyricsDocument,
    SyncError,
    parse_lyrics_file,
    to_srt,
)


class SubtitleStyle(BaseModel):
    """Estilo de los subtítulos (ASS via ``force_style`` de libass)."""

    font_name: str | None = None  # None → Arial en Windows, default en el resto
    font_size: int | None = Field(default=None, gt=0)  # None → auto según altura
    margin_v: int | None = Field(default=None, ge=0)  # None → auto según altura
    primary_color: str = "&H00FFFFFF"  # blanco (AABBGGRR)
    outline_color: str = "&H00000000"  # negro
    outline: int = Field(default=2, ge=0)
    shadow: int = Field(default=0, ge=0)
    bold: bool = False


class RenderResult(BaseModel):
    """Resultado del renderizado de subtítulos."""

    output_path: Path
    duration: float
    resolution: tuple[int, int]


# ---------------------------------------------------------------------------
# Helpers de filtro (puros, testeables sin FFmpeg)
# ---------------------------------------------------------------------------


def _escape_filter_value(value: str) -> str:
    """Escapa un valor para usarlo entre comillas simples en un filtro FFmpeg."""
    return (
        value.replace("\\", "/")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("'", "\\'")
    )


def default_fonts_dir() -> str | None:
    """Directorio de fuentes del sistema, o None si libass usa fontconfig."""
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        return str(fonts) if fonts.is_dir() else None
    if sys.platform == "darwin":
        fonts = Path("/System/Library/Fonts")
        return str(fonts) if fonts.is_dir() else None
    return None  # Linux: fontconfig


def _default_font_name() -> str | None:
    return "Arial" if sys.platform == "win32" else None


def resolve_style(style: SubtitleStyle, video_height: int) -> SubtitleStyle:
    """Rellena los valores auto (font_size/margin_v/font_name por plataforma)."""
    size = style.font_size or max(12, round(video_height * 0.05))
    margin = style.margin_v if style.margin_v is not None else max(
        16, round(video_height * 0.05)
    )
    font = style.font_name or _default_font_name()
    return style.model_copy(
        update={"font_size": size, "margin_v": margin, "font_name": font}
    )


def build_subtitles_filter(
    srt_filename: str,
    style: SubtitleStyle | None = None,
    video_height: int = 1080,
    fonts_dir: str | None = None,
) -> str:
    """Construye la cadena del filtro ``subtitles`` de FFmpeg.

    Args:
        srt_filename: nombre del .srt (relativo: el comando se ejecuta con
            cwd en el directorio temporal que lo contiene).
        style: estilo a aplicar (valores auto resueltos contra video_height).
        video_height: alto del vídeo (para tamaño/margen automáticos).
        fonts_dir: directorio de fuentes (Windows/macOS) o None.
    """
    resolved = resolve_style(style or SubtitleStyle(), video_height)
    force_parts = [
        f"FontName={resolved.font_name}",
        f"FontSize={resolved.font_size}",
        f"MarginV={resolved.margin_v}",
        f"PrimaryColour={resolved.primary_color}",
        f"OutlineColour={resolved.outline_color}",
        f"Outline={resolved.outline}",
        f"Shadow={resolved.shadow}",
        f"Bold={1 if resolved.bold else 0}",
    ]
    if resolved.font_name is None:
        # Sin fuente explícita: libass usará su default (fontconfig).
        force_parts = [p for p in force_parts if not p.startswith("FontName=")]

    parts = [
        f"subtitles=filename='{_escape_filter_value(srt_filename)}'",
        f"force_style='{','.join(force_parts)}'",
    ]
    if fonts_dir:
        parts.append(f"fontsdir='{_escape_filter_value(fonts_dir)}'")
    return ":".join(parts)


# ---------------------------------------------------------------------------
# Ejecución FFmpeg
# ---------------------------------------------------------------------------


async def _run_ffmpeg(cmd: list[str], cwd: Path) -> None:
    """Ejecuta FFmpeg (con cwd) y lanza SyncError si falla."""
    ensure_ffmpeg()
    proc = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, cwd=str(cwd)
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[-2000:]
        raise SyncError(f"FFmpeg falló ({proc.returncode}): {stderr}")


async def _probe_resolution(path: Path) -> tuple[int, int]:
    """Resolución (width, height) del primer stream de vídeo."""
    ensure_ffmpeg()
    proc = await asyncio.to_thread(
        subprocess.run,
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SyncError(f"No se pudo leer la resolución de {path}")
    try:
        width, height = proc.stdout.strip().split("x")
        return int(width), int(height)
    except ValueError:
        raise SyncError(f"Resolución no válida en {path}") from None


_subtitles_cache: bool | None = None


async def _check_subtitles_filter() -> None:
    """Verifica que el FFmpeg del sistema tiene el filtro subtitles (libass)."""
    global _subtitles_cache
    if _subtitles_cache is not None:
        if not _subtitles_cache:
            raise SyncError(
                "El FFmpeg del sistema no tiene el filtro 'subtitles' (libass). "
                "Instala un build completo (Windows: winget install Gyan.FFmpeg)."
            )
        return
    ensure_ffmpeg()
    proc = await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
    )
    _subtitles_cache = " subtitles " in (proc.stdout or "")
    if not _subtitles_cache:
        raise SyncError(
            "El FFmpeg del sistema no tiene el filtro 'subtitles' (libass). "
            "Instala un build completo (Windows: winget install Gyan.FFmpeg)."
        )


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class SubtitleRenderer:
    """Quema subtítulos sincronizados en un vídeo (salida MP4 h264+aac)."""

    def __init__(self, style: SubtitleStyle | None = None) -> None:
        self.style = style or SubtitleStyle()

    async def render(
        self,
        video: str | Path,
        lyrics: str | Path | LyricsDocument,
        output: str | Path | None = None,
        *,
        style: SubtitleStyle | None = None,
    ) -> RenderResult:
        """Renderiza el vídeo con los subtítulos quemados.

        Args:
            video: vídeo de entrada (MP4/MOV/...).
            lyrics: documento temporizado o fichero .lrc/.srt/.json.
            output: ruta de salida (default: ``<video>_subs.mp4``).

        Raises:
            SyncError: si el documento no está temporizado, falta FFmpeg con
                libass, o el render falla.
        """
        video_path = Path(video)
        if not video_path.is_file():
            raise SyncError(f"Vídeo no encontrado: {video_path}")

        doc = (
            lyrics
            if isinstance(lyrics, LyricsDocument)
            else parse_lyrics_file(Path(lyrics))
        )
        if not doc.timed or not doc.lines:
            raise SyncError(
                "El documento de letra no tiene timestamps. Alínealo antes "
                "(youber-sync align) o pasa un fichero .lrc/.srt."
            )

        await _check_subtitles_filter()
        width, height = await _probe_resolution(video_path)

        workdir = Path(tempfile.mkdtemp(prefix="youber_sync_"))
        try:
            srt_file = workdir / "subtitles.srt"
            srt_file.write_text(to_srt(doc), encoding="utf-8")

            output_path = Path(output) if output else video_path.with_name(
                f"{video_path.stem}_subs.mp4"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)

            active_style = style or self.style
            vf = build_subtitles_filter(
                srt_file.name, active_style, height, default_fonts_dir()
            )
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(video_path),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output_path),
            ]
            await _run_ffmpeg(cmd, cwd=workdir)

            duration = await probe_duration(output_path)
            out_width, out_height = await _probe_resolution(output_path)
            return RenderResult(
                output_path=output_path,
                duration=duration,
                resolution=(out_width, out_height),
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
