"""Alineación de letras con el audio (Whisper opcional + heurística local).

Dos caminos para obtener timestamps precisos:

1. **Whisper** (``faster-whisper`` o ``openai-whisper``, opcional): transcribe
   el audio y mapea las líneas de letra a los segmentos transcritos
   (:func:`align_lines_to_segments`). Si no hay letra previa, la propia
   transcripción segmentada es el documento.
2. **Heurística rough** (:func:`rough_align`): reparto determinista de las
   líneas a lo largo de la duración del audio, proporcional a su longitud.
   Sin red ni modelos; útil como base o cuando no hay Whisper instalado.

Whisper no es dependencia obligatoria: ``youber-sync`` funciona sin él y
avisa con instrucciones claras si se pide transcripción y no está instalado.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from youber.audio._ffmpeg import probe_duration
from youber.sync.timestamps import (
    LyricsDocument,
    SyncError,
    SyncLine,
    parse_lyrics_file,
)


class Segment(BaseModel):
    """Segmento transcrito por Whisper (ventana temporal + texto)."""

    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str = ""


# ---------------------------------------------------------------------------
# Alineación rough (sin Whisper)
# ---------------------------------------------------------------------------


def rough_align(
    lines: list[str],
    duration: float,
    *,
    gap: float = 0.25,
    lead_in: float = 0.5,
    tail: float = 0.5,
) -> list[SyncLine]:
    """Reparte las líneas a lo largo de la duración, sin red ni modelos.

    Determinista: cada línea recibe un tiempo proporcional a su longitud
    (mínimo 6 caracteres), con ``gap`` entre líneas y márgenes de entrada y
    salida. Si la duración es demasiado corta para los márgenes, se hace un
    reparto equitativo simple.
    """
    non_empty = [line for line in lines if line.strip()]
    if not non_empty or duration <= 0:
        return []

    n = len(non_empty)
    available = duration - lead_in - tail - gap * (n - 1)
    if available <= 0:
        share = duration / n
        return [
            SyncLine(start=index * share, end=(index + 1) * share, text=line)
            for index, line in enumerate(non_empty)
        ]

    weights = [max(len(line), 6) for line in non_empty]
    total_weight = sum(weights)
    cursor = lead_in
    result: list[SyncLine] = []
    for index, line in enumerate(non_empty):
        share = available * weights[index] / total_weight
        result.append(SyncLine(start=cursor, end=cursor + share, text=line))
        cursor += share + gap
    return result


# ---------------------------------------------------------------------------
# Mapeo de líneas a segmentos Whisper
# ---------------------------------------------------------------------------


def align_lines_to_segments(lines: list[str], segments: list[Segment]) -> list[SyncLine]:
    """Asigna tiempos a las líneas de letra usando segmentos transcritos.

    Estrategia proporcional: se calcula la posición (en caracteres) de cada
    frontera de línea dentro del texto transcrito y se interpola su tiempo
    dentro del segmento correspondiente.

    Limitación conocida: si la letra tiene repeticiones (estribillos) que el
    transcriptor colapsa, las líneas finales se saturan al final del audio.
    """
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return []
    if not segments:
        raise SyncError(
            "No hay segmentos transcritos para alinear; usa rough_align o "
            "instala faster-whisper."
        )

    seg_texts = [seg.text for seg in segments]
    total_chars = sum(len(text) for text in seg_texts)
    if total_chars == 0:
        raise SyncError("La transcripción no contiene texto utilizable.")

    seg_starts: list[int] = []
    running = 0
    for text in seg_texts:
        seg_starts.append(running)
        running += len(text)

    total_line_chars = sum(len(line) for line in non_empty)

    def boundary_time(boundary_char: float) -> float:
        """Interpola el tiempo de una posición de carácter en la transcripción."""
        pos = min(max(boundary_char, 0), total_chars)
        if pos >= total_chars:
            return segments[-1].end
        # Segmento donde cae la posición
        index = len(seg_starts) - 1
        for i, start in enumerate(seg_starts):
            if pos < start + len(seg_texts[i]):
                index = i
                break
        offset = pos - seg_starts[index]
        seg = segments[index]
        length = max(len(seg_texts[index]), 1)
        return seg.start + (offset / length) * (seg.end - seg.start)

    result: list[SyncLine] = []
    cumulative = 0
    boundaries: list[float] = [0.0]
    for line in non_empty:
        cumulative += len(line)
        boundaries.append(total_chars * cumulative / max(total_line_chars, 1))

    for index, line in enumerate(non_empty):
        start = boundary_time(boundaries[index])
        end = boundary_time(boundaries[index + 1])
        if end <= start:
            end = min(start + 1.0, segments[-1].end)
        result.append(SyncLine(start=start, end=max(end, start + 0.1), text=line))
    return result


# ---------------------------------------------------------------------------
# Transcripción Whisper (backend opcional)
# ---------------------------------------------------------------------------


def _transcribe_blocking(
    audio_path: Path, model_size: str, language: str | None
) -> list[Segment]:
    """Transcribe con faster-whisper o openai-whisper (bloqueante; va en thread)."""
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments_iter, _info = model.transcribe(
            str(audio_path), language=language, vad_filter=False
        )
        return [
            Segment(start=seg.start, end=seg.end, text=seg.text.strip())
            for seg in segments_iter
            if seg.text.strip()
        ]
    except ImportError:
        pass

    try:
        import whisper

        model = whisper.load_model(model_size)
        result = model.transcribe(str(audio_path), language=language)
        return [
            Segment(
                start=float(seg["start"]),
                end=float(seg["end"]),
                text=str(seg["text"]).strip(),
            )
            for seg in result.get("segments", [])
            if str(seg.get("text", "")).strip()
        ]
    except ImportError:
        raise SyncError(
            "Whisper no está instalado. Instálalo para transcribir audio:\n"
            "  pip install 'youber[sync]'   # o: pip install faster-whisper\n"
            "Sin Whisper puedes alinear texto plano con la heurística rough "
            "(youber-sync align sin --whisper)."
        ) from None


async def transcribe_segments(
    audio_path: str | Path,
    model_size: str = "small",
    language: str | None = None,
) -> list[Segment]:
    """Transcribe un audio y devuelve segmentos con timestamps.

    El modelo se descarga en el primer uso (varias decenas de MB según
    tamaño). ``model_size``: tiny|base|small|medium|large-v3.
    """
    if model_size not in {"tiny", "base", "small", "medium", "large", "large-v3"}:
        raise SyncError(f"Modelo Whisper desconocido: {model_size!r}")
    path = Path(audio_path)
    if not path.is_file():
        raise SyncError(f"Audio no encontrado: {path}")
    return await asyncio.to_thread(_transcribe_blocking, path, model_size, language)


# ---------------------------------------------------------------------------
# Alineador de alto nivel
# ---------------------------------------------------------------------------


class LyricsAligner:
    """Alinea una letra (fichero o transcripción) contra un audio."""

    async def align(
        self,
        audio_path: str | Path,
        lyrics_file: str | Path | None = None,
        *,
        model_size: str | None = None,
        language: str | None = None,
    ) -> LyricsDocument:
        """Devuelve un :class:`LyricsDocument` temporizado.

        - Con ``lyrics_file`` temporizado (LRC/SRT) y sin ``model_size``: se
          usa tal cual (sus marcas mandan).
        - Con letra de texto plano y sin ``model_size``: alineación rough.
        - Con ``model_size`` (o sin ``lyrics_file``): transcribe con Whisper
          y alinea las líneas a los segmentos (preciso).
        """
        audio = Path(audio_path)
        if not audio.is_file():
            raise SyncError(f"Audio no encontrado: {audio}")
        duration = await probe_duration(audio)

        # Transcripción pura: sin letra previa.
        if lyrics_file is None:
            segments = await transcribe_segments(audio, model_size or "small", language)
            return LyricsDocument(
                lines=[
                    SyncLine(start=seg.start, end=seg.end, text=seg.text)
                    for seg in segments
                ],
                duration=duration,
                timed=True,
                source="whisper",
            )

        lyrics = parse_lyrics_file(lyrics_file)
        plain = lyrics.as_plain_lines()
        if not plain:
            raise SyncError(f"La letra {lyrics_file} no contiene líneas de texto.")

        # Letra ya temporizada: usar sus marcas (a menos que se pida realinear).
        if lyrics.timed and model_size is None:
            lyrics.duration = duration
            return lyrics

        if model_size is not None:
            segments = await transcribe_segments(audio, model_size, language)
            timed_lines = align_lines_to_segments(plain, segments)
            source = "whisper"
        else:
            timed_lines = rough_align(plain, duration)
            source = "rough"

        return LyricsDocument(
            lines=timed_lines,
            title=lyrics.title,
            artist=lyrics.artist,
            duration=duration,
            timed=True,
            source=source,
        )
