"""Helper interno de FFmpeg para el módulo de audio.

Centraliza la comprobación de disponibilidad, la ejecución de comandos
(``ffmpeg``) y la lectura de duraciones (``ffprobe``). Los módulos públicos
(``editor``, ``effects``, ``sync``) ejecutan FFmpeg a través de aquí para
poder testearse con mocks sin necesitar FFmpeg instalado.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path


def ensure_ffmpeg() -> None:
    """Comprueba que ``ffmpeg`` y ``ffprobe`` están disponibles en el sistema.

    Raises:
        RuntimeError: si falta alguno de los dos binarios, con instrucciones
            de instalación.
    """
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise RuntimeError(
            "FFmpeg no está instalado (faltan: " + ", ".join(missing) + "). "
            "Instálalo para usar el módulo de audio:\n"
            "  - Windows: winget install Gyan.FFmpeg  (o choco install ffmpeg)\n"
            "  - macOS:   brew install ffmpeg\n"
            "  - Linux:   sudo apt install ffmpeg"
        )


async def run_command(cmd: list[str]) -> subprocess.CompletedProcess:
    """Ejecuta un comando FFmpeg/ffprobe de forma asíncrona.

    Args:
        cmd: Lista de argumentos del comando.

    Returns:
        El resultado de :class:`subprocess.CompletedProcess`.

    Raises:
        RuntimeError: si FFmpeg no está instalado o el comando falla.
    """
    ensure_ffmpeg()
    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[-2000:]
        raise RuntimeError(f"FFmpeg falló ({result.returncode}): {stderr}")
    return result


async def probe_duration(path: str | Path) -> float:
    """Devuelve la duración (en segundos) de un fichero de audio/vídeo."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = await run_command(cmd)
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"No se pudo leer la duración de {path}") from exc
