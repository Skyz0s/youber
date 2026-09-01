"""Análisis de patrones en datos de YouTube (uso educativo).

Funciones puras para estudiar *qué publica* un canal a partir de datos
públicos ya extraídos: hashtags más usados, patrones en los títulos
(números, mayúsculas, emojis, preguntas, "vs", listas "top N"...),
duración de los vídeos y un resumen global del canal.

Esto es **análisis descriptivo**, no manipulación de métricas.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from youber.research.data_models import ChannelData, VideoData

HASHTAG_RE = re.compile(r"#([\w\u00C0-\u024F]+)")
NUMBER_RE = re.compile(r"\d")
UPPERCASE_WORD_RE = re.compile(r"\b[A-ZÁÉÍÓÚÑÜ]{3,}\b")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F02F]"
)
QUESTION_RE = re.compile(r"\?")
VS_RE = re.compile(r"\bvs\.?\b", re.IGNORECASE)
TUTORIAL_RE = re.compile(r"\b(cómo|como|tutorial|guía|guia)\b", re.IGNORECASE)
TOP_LIST_RE = re.compile(r"\btop\s*\d+|\bmejores?\b", re.IGNORECASE)
COMPACT_NUMBER_RE = re.compile(r"([\d.,]+)\s*([KMBkmb]?)(?!\w)")


def extract_hashtags(text: str) -> list[str]:
    """Extrae los hashtags de un texto (descripción o título)."""
    return list(dict.fromkeys(HASHTAG_RE.findall(text)))


def parse_compact_count(text: str) -> float | None:
    """Convierte "1,2 M", "3.4M" o "12K" en número (mejor esfuerzo).

    Nota: NO se eliminan los espacios antes de buscar — el patrón ya los
    consume y ``(?!\\w)`` necesita el espacio (o el final) después del
    sufijo para no confundir "84 M de visualizaciones" con una palabra
    que empiece por M.

    Returns:
        El valor numérico, o ``None`` si no se reconoce ningún formato.
    """
    if not text:
        return None
    match = COMPACT_NUMBER_RE.search(text)
    if not match:
        return None
    raw, suffix = match.groups()
    try:
        value = _parse_decimal(raw)
    except ValueError:
        return None
    multiplier = {"": 1.0, "k": 1_000.0, "m": 1_000_000.0, "b": 1_000_000_000.0}
    return value * multiplier.get(suffix.lower(), 1.0)


def _parse_decimal(raw: str) -> float:
    """Normaliza "1,2" / "1.2" / "1.234,5" a float (mejor esfuerzo)."""
    if "," in raw and "." in raw:
        # El último separador suele ser el decimal ("1.234,5" es-ES).
        if raw.rfind(",") > raw.rfind("."):
            return float(raw.replace(".", "").replace(",", "."))
        return float(raw.replace(",", ""))
    if "," in raw:
        # Asumimos coma decimal ("1,2"), no separador de miles.
        return float(raw.replace(",", "."))
    return float(raw)


def hashtag_frequency(videos: list[VideoData]) -> Counter[str]:
    """Frecuencia de hashtags a lo largo de los vídeos del canal."""
    counter: Counter[str] = Counter()
    for video in videos:
        counter.update(video.hashtags)
    return counter


def title_patterns(titles: list[str]) -> dict[str, int]:
    """Cuenta patrones comunes en los títulos de los vídeos.

    Returns:
        Diccionario con el total de títulos y el recuento de cada patrón
        (números, palabras en MAYÚSCULAS, emojis, preguntas, "vs",
        palabras de tutorial y formatos de lista "top N").
    """
    total = len(titles)
    counts = {
        "total": total,
        "with_numbers": 0,
        "with_uppercase_words": 0,
        "with_emojis": 0,
        "with_question": 0,
        "with_vs": 0,
        "with_tutorial_keyword": 0,
        "with_top_list": 0,
    }
    for title in titles:
        if NUMBER_RE.search(title):
            counts["with_numbers"] += 1
        if UPPERCASE_WORD_RE.search(title):
            counts["with_uppercase_words"] += 1
        if EMOJI_RE.search(title):
            counts["with_emojis"] += 1
        if QUESTION_RE.search(title):
            counts["with_question"] += 1
        if VS_RE.search(title):
            counts["with_vs"] += 1
        if TUTORIAL_RE.search(title):
            counts["with_tutorial_keyword"] += 1
        if TOP_LIST_RE.search(title):
            counts["with_top_list"] += 1
    return counts


def parse_duration_to_seconds(duration: str | None) -> int | None:
    """Convierte ``"12:34"`` o ``"1:02:03"`` en segundos (mejor esfuerzo).

    Returns:
        Segundos, o ``None`` si el formato no se reconoce.
    """
    if not duration:
        return None
    parts = duration.strip().split(":")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return None


def duration_stats(videos: list[VideoData]) -> dict[str, Any]:
    """Estadísticas de duración de los vídeos (en segundos y por tramos).

    Returns:
        Recuento, media/mín/máximo (segundos) y reparto por tramos:
        cortos (<4 min), medios (4-15 min) y largos (>15 min).
    """
    durations = [
        seconds
        for video in videos
        if (seconds := parse_duration_to_seconds(video.duration)) is not None
    ]
    stats: dict[str, Any] = {
        "count": len(durations),
        "avg_seconds": None,
        "min_seconds": None,
        "max_seconds": None,
        "buckets": {"short_lt_4min": 0, "medium_4_15min": 0, "long_gt_15min": 0},
    }
    if not durations:
        return stats

    stats["avg_seconds"] = round(sum(durations) / len(durations), 1)
    stats["min_seconds"] = min(durations)
    stats["max_seconds"] = max(durations)
    for seconds in durations:
        if seconds < 4 * 60:
            stats["buckets"]["short_lt_4min"] += 1
        elif seconds <= 15 * 60:
            stats["buckets"]["medium_4_15min"] += 1
        else:
            stats["buckets"]["long_gt_15min"] += 1
    return stats


def channel_overview(channel: ChannelData) -> dict[str, Any]:
    """Resumen global del canal: cabecera + patrones + estadísticas.

    Args:
        channel: Canal ya analizado.

    Returns:
        Diccionario con los datos de cabecera, hashtags más frecuentes,
        patrones de títulos y estadísticas de duración.
    """
    videos = channel.videos
    hashtags = hashtag_frequency(videos).most_common(10)

    parsed_views = [
        count
        for video in videos
        if (count := parse_compact_count(video.views)) is not None
    ]
    views_summary: dict[str, Any] = {
        "parsed": len(parsed_views),
        "avg": round(sum(parsed_views) / len(parsed_views)) if parsed_views else None,
        "max": max(parsed_views) if parsed_views else None,
    }

    return {
        "channel": {
            "name": channel.name,
            "url": channel.url,
            "handle": channel.handle,
            "subscribers": channel.subscribers,
            "total_views": channel.total_views,
        },
        "videos_count": len(videos),
        "top_hashtags": [{"hashtag": tag, "count": count} for tag, count in hashtags],
        "title_patterns": title_patterns([video.title for video in videos]),
        "duration_stats": duration_stats(videos),
        "views_summary": views_summary,
    }
