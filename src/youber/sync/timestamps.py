"""Modelos y serialización de letras sincronizadas (LRC/SRT/JSON/TXT).

Dominio del módulo ``youber.sync``:

- :class:`SyncLine`: una línea de letra con ventana temporal ``[start, end)``
  (``end`` puede ser ``None`` en LRC, donde solo hay marca de inicio).
- :class:`LyricsDocument`: documento completo (líneas + metadatos + si está
  temporizado de verdad).

Además contiene los parsers/serializers puros de los formatos LRC, SRT,
JSON y texto plano (sin dependencias externas, 100 % testeables offline).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------


class SyncError(RuntimeError):
    """Error del módulo sync (entrada inválida, FFmpeg/libass, Whisper...)."""


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


class SyncLine(BaseModel):
    """Una línea de letra con su ventana temporal (si se conoce)."""

    start: float = Field(default=0.0, ge=0.0)
    end: float | None = Field(default=None, ge=0.0)
    text: str = ""


class LyricsDocument(BaseModel):
    """Documento de letra, temporizada o no."""

    lines: list[SyncLine] = Field(default_factory=list)
    title: str | None = None
    artist: str | None = None
    duration: float | None = Field(default=None, ge=0.0)
    # True si las marcas son reales (LRC/SRT/Whisper); False si es texto plano.
    timed: bool = False
    # Origen: lrc | srt | json | txt | whisper | rough | segments
    source: str = "txt"

    @property
    def plain_text(self) -> str:
        """La letra como texto plano (una línea por entrada)."""
        return "\n".join(line.text for line in self.lines if line.text)

    def as_plain_lines(self) -> list[str]:
        """Líneas de texto no vacías (para realinear)."""
        return [line.text for line in self.lines if line.text.strip()]


# ---------------------------------------------------------------------------
# Tiempos
# ---------------------------------------------------------------------------


def format_lrc_time(seconds: float) -> str:
    """Formatea segundos como ``[mm:ss.cc]`` (LRC)."""
    total_cs = max(0, int(round(seconds * 100)))
    minutes, rest = divmod(total_cs, 6000)
    secs, cs = divmod(rest, 100)
    return f"[{minutes:02d}:{secs:02d}.{cs:02d}]"


def format_srt_time(seconds: float) -> str:
    """Formatea segundos como ``HH:MM:SS,mmm`` (SRT)."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_LRC_META = re.compile(r"\[(ti|ar|al|by|re|ve|au|offset):(.+)\]", re.IGNORECASE)
_SRT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _lrc_tag_to_seconds(match: re.Match) -> float:
    minutes = int(match.group(1))
    secs = int(match.group(2))
    frac = match.group(3)
    fraction = int(frac) / (1000 if len(frac) == 3 else 100) if frac else 0.0
    return minutes * 60 + secs + fraction


def _srt_stamp_to_seconds(*groups: str) -> float:
    hours, minutes, secs, ms = (int(g) for g in groups)
    return hours * 3600 + minutes * 60 + secs + ms / 1000


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_lrc(text: str) -> LyricsDocument:
    """Parsea letra LRC (con o sin metadatos ``[ti:]``/``[ar:]``/``[offset:]``).

    Una línea con varias marcas temporales genera una entrada por marca.
    """
    title: str | None = None
    artist: str | None = None
    offset_seconds = 0.0
    lines: list[SyncLine] = []

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        times = list(_LRC_TIME.finditer(stripped))
        if times:
            content = _LRC_TIME.sub("", stripped).strip()
            if not content:
                continue
            for tag in times:
                lines.append(
                    SyncLine(
                        start=max(0.0, _lrc_tag_to_seconds(tag) + offset_seconds),
                        end=None,
                        text=content,
                    )
                )
            continue
        meta = _LRC_META.match(stripped)
        if meta:
            key, value = meta.group(1).lower(), meta.group(2).strip()
            if key == "ti":
                title = value
            elif key == "ar":
                artist = value
            elif key == "offset":
                try:
                    offset_seconds = int(value) / 1000.0
                except ValueError:
                    pass

    lines.sort(key=lambda line: line.start)
    return LyricsDocument(
        lines=lines,
        title=title,
        artist=artist,
        timed=bool(lines),
        source="lrc",
    )


def parse_srt(text: str) -> LyricsDocument:
    """Parsea subtítulos SRT (índice opcional + ventana temporal)."""
    lines: list[SyncLine] = []
    current_time: tuple[float, float] | None = None
    current_text: list[str] = []

    def flush() -> None:
        nonlocal current_time, current_text
        if current_time is not None and current_text:
            start, end = current_time
            lines.append(
                SyncLine(
                    start=max(0.0, start),
                    end=max(0.0, end),
                    text=" ".join(current_text).strip(),
                )
            )
        current_time = None
        current_text = []

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            flush()
            continue
        if stripped.isdigit():
            continue  # índice de bloque
        match = _SRT_TIME.search(stripped)
        if match:
            flush()
            start = _srt_stamp_to_seconds(*match.groups()[0:4])
            end = _srt_stamp_to_seconds(*match.groups()[4:8])
            current_time = (start, end)
            continue
        if current_time is not None:
            current_text.append(stripped)
    flush()

    lines.sort(key=lambda line: line.start)
    return LyricsDocument(lines=lines, timed=bool(lines), source="srt")


def parse_txt(text: str) -> LyricsDocument:
    """Parsea letra de texto plano (sin marcas temporales)."""
    lines = [
        SyncLine(text=raw.strip())
        for raw in text.splitlines()
        if raw.strip()
    ]
    return LyricsDocument(lines=lines, timed=False, source="txt")


def parse_json(text: str) -> LyricsDocument:
    """Parsea un documento JSON exportado con :func:`to_json`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SyncError(f"JSON inválido: {exc}") from None
    try:
        return LyricsDocument.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        raise SyncError(f"JSON no es un LyricsDocument válido: {exc}") from None


def sniff_format(text: str) -> str:
    """Detecta el formato por contenido: srt / lrc / json / txt."""
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return "json"
    if _SRT_TIME.search(text):
        return "srt"
    if _LRC_TIME.search(text):
        return "lrc"
    return "txt"


def parse_document(text: str, fmt: str | None = None) -> LyricsDocument:
    """Parsea texto en el formato indicado (o auto-detectado si es ``None``)."""
    fmt = (fmt or sniff_format(text)).lower()
    if fmt == "lrc":
        return parse_lrc(text)
    if fmt == "srt":
        return parse_srt(text)
    if fmt == "json":
        return parse_json(text)
    if fmt == "txt":
        return parse_txt(text)
    raise SyncError(f"Formato desconocido: {fmt!r} (lrc|srt|json|txt)")


def parse_lyrics_file(path: str | Path) -> LyricsDocument:
    """Lee un fichero de letra (lrc/srt/json/txt) y lo parsea.

    El sufijo manda; si no se reconoce, se auto-detecta por contenido.
    """
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SyncError(f"No se pudo leer {file_path}: {exc}") from None
    suffix = file_path.suffix.lower().lstrip(".")
    fmt = suffix if suffix in {"lrc", "srt", "json", "txt"} else None
    return parse_document(text, fmt)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def to_lrc(doc: LyricsDocument) -> str:
    """Serializa a LRC (marcas de inicio; los ``end`` se ignoran)."""
    out: list[str] = []
    if doc.title:
        out.append(f"[ti:{doc.title}]")
    if doc.artist:
        out.append(f"[ar:{doc.artist}]")
    for line in doc.lines:
        if not line.text:
            continue
        out.append(f"{format_lrc_time(line.start)}{line.text}")
    return "\n".join(out) + ("\n" if out else "")


def _ends_for_srt(doc: LyricsDocument, gap: float = 0.05) -> list[float]:
    """Calcula finales de línea para SRT cuando faltan (siguiente - gap)."""
    ends: list[float] = []
    for index, line in enumerate(doc.lines):
        if line.end is not None:
            ends.append(line.end)
            continue
        if index + 1 < len(doc.lines):
            nxt = doc.lines[index + 1].start
            ends.append(max(line.start + 0.2, nxt - gap))
        else:
            last_end = doc.duration if doc.duration is not None else line.start + 3.0
            ends.append(max(line.start + 1.0, last_end))
    return ends


def to_srt(doc: LyricsDocument) -> str:
    """Serializa a SRT (subtítulos con ventana temporal)."""
    ends = _ends_for_srt(doc)
    out: list[str] = []
    for index, line in enumerate(doc.lines):
        if not line.text:
            continue
        start = line.start
        end = max(ends[index], start + 0.1)
        out.extend(
            [
                str(index + 1),
                f"{format_srt_time(start)} --> {format_srt_time(end)}",
                line.text,
                "",
            ]
        )
    return "\n".join(out)


def to_json(doc: LyricsDocument) -> str:
    """Serializa a JSON (dump de pydantic, legible)."""
    return doc.model_dump_json(indent=2)


def to_txt(doc: LyricsDocument) -> str:
    """Serializa a texto plano (solo letra)."""
    return doc.plain_text + ("\n" if doc.plain_text else "")


def serialize(doc: LyricsDocument, fmt: str) -> str:
    """Serializa un documento al formato pedido (lrc|srt|json|txt)."""
    fmt = fmt.lower()
    if fmt == "lrc":
        return to_lrc(doc)
    if fmt == "srt":
        return to_srt(doc)
    if fmt == "json":
        return to_json(doc)
    if fmt == "txt":
        return to_txt(doc)
    raise SyncError(f"Formato desconocido: {fmt!r} (lrc|srt|json|txt)")
