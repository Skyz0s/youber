"""Exportación de datos de investigación de YouTube (JSON, CSV, Markdown).

Convierte :class:`ChannelData` / :class:`VideoData` en formatos estructurados
para análisis posterior (hojas de cálculo, notebooks, informes).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from youber.research.data_models import ChannelData, VideoData


def generate_channel_json(channel: ChannelData) -> str:
    """Serializa el canal (con sus vídeos) a JSON legible."""
    return channel.model_dump_json(indent=2)


def generate_videos_csv(videos: list[VideoData]) -> str:
    """Genera un CSV con los vídeos (una fila por vídeo, UTF-8 con BOM).

    El BOM permite que Excel abra el fichero con acentos correctamente.
    """
    fieldnames = [
        "title",
        "url",
        "video_id",
        "views",
        "likes",
        "comments",
        "duration",
        "publish_date",
        "thumbnail_url",
        "description",
        "hashtags",
        "channel_name",
        "channel_url",
        "extracted_at",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for video in videos:
        row = video.model_dump()
        row["hashtags"] = " ".join(f"#{tag}" for tag in row["hashtags"])
        writer.writerow(row)
    return "\ufeff" + buffer.getvalue()


def generate_channel_markdown(channel: ChannelData) -> str:
    """Genera un informe Markdown del canal: cabecera + tabla de vídeos."""
    lines = [
        f"# Canal — {channel.name}",
        "",
        f"- **URL:** {channel.url}",
        f"- **Handle:** {channel.handle or '-'}",
        f"- **Suscriptores:** {channel.subscribers or '-'}",
        f"- **Total de visualizaciones:** {channel.total_views or '-'}",
        f"- **Vídeos recogidos:** {len(channel.videos)}",
        "",
        "## Vídeos",
        "",
        "| Título | Vistas | Duración | Publicado | URL |",
        "|---|---|---|---|---|",
    ]
    for video in channel.videos:
        safe_title = video.title.replace("|", "\\|")
        lines.append(
            f"| {safe_title} | {video.views} | {video.duration or '-'} | "
            f"{video.publish_date or '-'} | {video.url} |"
        )
    return "\n".join(lines) + "\n"


def export_channel(
    channel: ChannelData,
    path: str | Path,
    fmt: str = "json",
) -> Path:
    """Guarda un canal en el formato indicado (``json``, ``csv`` o ``md``).

    Args:
        channel: Canal a exportar.
        path: Ruta del fichero de salida.
        fmt: Formato de salida: ``json``, ``csv`` (solo vídeos) o ``md``.

    Returns:
        La ruta del fichero escrito.

    Raises:
        ValueError: si el formato no está soportado.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        target.write_text(generate_channel_json(channel), encoding="utf-8")
    elif fmt == "csv":
        target.write_text(generate_videos_csv(channel.videos), encoding="utf-8")
    elif fmt == "md":
        target.write_text(generate_channel_markdown(channel), encoding="utf-8")
    else:
        raise ValueError(f"Formato no soportado: {fmt!r} (usa json, csv o md)")
    return target


def export_videos(
    videos: list[VideoData],
    path: str | Path,
    fmt: str = "csv",
) -> Path:
    """Guarda una lista de vídeos en el formato indicado (``csv`` o ``json``).

    Args:
        videos: Vídeos a exportar.
        path: Ruta del fichero de salida.
        fmt: Formato de salida: ``csv`` o ``json``.

    Returns:
        La ruta del fichero escrito.

    Raises:
        ValueError: si el formato no está soportado.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        target.write_text(generate_videos_csv(videos), encoding="utf-8")
    elif fmt == "json":
        payload = [video.model_dump(mode="json") for video in videos]
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        raise ValueError(f"Formato no soportado: {fmt!r} (usa csv o json)")
    return target
