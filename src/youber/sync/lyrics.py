"""Extracción de letras para sincronización.

Fuentes soportadas:

1. **Ficheros locales** (``.lrc``, ``.txt``, ``.srt``, ``.json``): la vía
   recomendada — letra que el usuario posee o tiene licencia para usar.
2. **Transcripción Whisper** del propio audio (backend opcional, ver
   ``youber.sync.aligner``): útil cuando no hay fichero de letra.
3. **Letras online**: deshabilitadas por defecto. Servir letras de terceros
   (Genius, etc.) requiere licencia y viola sus ToS si se scrapea; este
   módulo no scrapea. Si en el futuro se quiere un provider con API key y
   licencia, se añade tras ``get_lyrics()`` sin tocar el resto del flujo.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from youber.sync.aligner import transcribe_segments
from youber.sync.timestamps import parse_lyrics_file

# Variable de entorno reservada para un futuro provider con licencia.
_LYRICS_PROVIDER_ENV = "YOUBER_LYRICS_PROVIDER"


class LyricsExtractor:
    """Extrae letras desde ficheros, transcripción o (futuro) providers."""

    async def extract_from_file(self, file_path: Path) -> str | None:
        """Extrae la letra (texto plano) de un fichero .lrc/.txt/.srt/.json.

        Returns:
            El texto plano de la letra, o ``None`` si no se pudo leer/parsear.
        """
        path = Path(file_path)
        try:
            document = parse_lyrics_file(path)
        except Exception as exc:  # SyncError / OSError
            logger.error("No se pudo extraer letra de {}: {}", path, exc)
            return None
        plain = document.plain_text
        return plain or None

    async def extract_lines(self, file_path: Path) -> list[str] | None:
        """Extrae las líneas de letra (sin marcas) de un fichero."""
        path = Path(file_path)
        try:
            document = parse_lyrics_file(path)
        except Exception as exc:  # SyncError / OSError
            logger.error("No se pudo extraer letra de {}: {}", path, exc)
            return None
        lines = document.as_plain_lines()
        return lines or None

    async def extract_from_audio(
        self,
        audio_path: Path,
        model_size: str = "small",
        language: str | None = None,
    ) -> str:
        """Transcribe el audio con Whisper y devuelve la letra como texto.

        Raises:
            SyncError: si Whisper no está instalado o el audio no existe.
        """
        segments = await transcribe_segments(
            Path(audio_path), model_size=model_size, language=language
        )
        return "\n".join(segment.text for segment in segments)

    async def get_lyrics(self, song_title: str, artist: str) -> str | None:
        """Busca la letra online (solo si hay un provider con licencia).

        Por defecto devuelve ``None``: las letras de terceros requieren
        licencia y scrapear viola ToS. Usa un fichero ``.lrc``/``.txt`` local
        o la transcripción Whisper (:meth:`extract_from_audio`).
        """
        provider = os.environ.get(_LYRICS_PROVIDER_ENV, "").strip().lower()
        if provider:
            logger.warning(
                "Provider de letras '{}' no está implementado: solo se "
                "soportan providers con licencia explícita (sin scraping).",
                provider,
            )
        logger.info(
            "Letras online deshabilitadas (copyright/ToS): usa un fichero "
            "local .lrc/.txt o transcripción Whisper. (título={!r}, artista={!r})",
            song_title,
            artist,
        )
        return None
