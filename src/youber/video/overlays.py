"""Superposiciones (overlays) del motor de edición de vídeo de BARF.

Construye los filtros de FFmpeg para dibujar textos (``drawtext``) e
imágenes (``overlay``) sobre el vídeo, con posición configurable,
transparencia y ventana temporal (``enable=between(t, ...)``).
"""

from __future__ import annotations

from youber.video.models import ImageOverlay, TextOverlay, TextPosition

# Mapeo de posición a expresiones x/y de FFmpeg.
# Se usan expresiones simbólicas (w/h/text_w/text_h) para adaptarse a la
# resolución final del proyecto.
_POSITIONS: dict[TextPosition, tuple[str, str]] = {
    TextPosition.TOP_LEFT: ("10", "10"),
    TextPosition.TOP_CENTER: ("(w-text_w)/2", "10"),
    TextPosition.TOP_RIGHT: ("w-text_w-10", "10"),
    TextPosition.CENTER: ("(w-text_w)/2", "(h-text_h)/2"),
    TextPosition.BOTTOM_LEFT: ("10", "h-text_h-10"),
    TextPosition.BOTTOM_CENTER: ("(w-text_w)/2", "h-text_h-10"),
    TextPosition.BOTTOM_RIGHT: ("w-text_w-10", "h-text_h-10"),
}

# Posiciones para imágenes: el filtro overlay usa W/H (fondo) y w/h (imagen).
_IMAGE_POSITIONS: dict[TextPosition, tuple[str, str]] = {
    TextPosition.TOP_LEFT: ("10", "10"),
    TextPosition.TOP_CENTER: ("(W-w)/2", "10"),
    TextPosition.TOP_RIGHT: ("W-w-10", "10"),
    TextPosition.CENTER: ("(W-w)/2", "(H-h)/2"),
    TextPosition.BOTTOM_LEFT: ("10", "H-h-10"),
    TextPosition.BOTTOM_CENTER: ("(W-w)/2", "H-h-10"),
    TextPosition.BOTTOM_RIGHT: ("W-w-10", "H-h-10"),
}


def _escape_text(text: str) -> str:
    """Escapa caracteres especiales de FFmpeg dentro del texto del overlay."""
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _enable_window(start_time: float, duration: float | None, total_duration: float) -> str:
    """Expresión ``enable=between(t, ...)`` para la ventana temporal."""
    end = start_time + duration if duration is not None else total_duration
    return f"between(t,{start_time:.3f},{end:.3f})"


def _escape_fontfile(path: str) -> str:
    """Escapa una ruta de fuente para el filtro drawtext (los ``:`` separan opciones)."""
    return path.replace("\\", "/").replace(":", "\\:")


def text_overlay_filter(
    overlay: TextOverlay,
    total_duration: float,
) -> str:
    """Construye el filtro ``drawtext`` para un :class:`TextOverlay`.

    Args:
        overlay: Texto a dibujar con posición, tamaño, color y ventana.
        total_duration: Duración total del vídeo (para overlays sin fin).

    Returns:
        Cadena de filtro ``drawtext=...`` lista para ``filter_complex``.
    """
    x, y = _POSITIONS[overlay.position]
    parts = [
        f"text='{_escape_text(overlay.text)}'",
        f"fontsize={overlay.font_size}",
        f"fontcolor={overlay.color}",
        f"x={x}",
        f"y={y}",
    ]
    if overlay.font_file:
        parts.append(f"fontfile='{_escape_fontfile(overlay.font_file)}'")
    if overlay.background:
        parts.append(f"box=1:boxcolor={overlay.background}:boxborderw=10")
    parts.append(f"enable='{_enable_window(overlay.start_time, overlay.duration, total_duration)}'")
    return f"drawtext={':'.join(parts)}"


def image_overlay_filter(
    overlay: ImageOverlay,
    input_label: str,
    output_label: str,
    total_duration: float,
    image_index: int,
) -> str:
    """Construye los filtros para superponer una imagen (marca de agua).

    Devuelve dos fragmentos separados por ``;``: el primero prepara la
    imagen (escala + transparencia) y el segundo la superpone al vídeo.

    Args:
        overlay: Imagen a superponer.
        input_label: Etiqueta del stream de vídeo actual (p. ej. ``vout``).
        output_label: Etiqueta del stream resultante.
        total_duration: Duración total del vídeo.
        image_index: Índice de la imagen (para etiquetas únicas).

    Returns:
        Fragmento de ``filter_complex`` con dos cadenas unidas por ``;``.
    """
    x, y = _IMAGE_POSITIONS[overlay.position]
    prepared = f"imgp{image_index}"
    return (
        f"[{image_index}:v]scale=iw*{overlay.scale}:-1,"
        f"format=rgba,colorchannelmixer=aa={overlay.opacity:.2f}[{prepared}];"
        f"[{input_label}][{prepared}]"
        f"overlay=x={x}:y={y}:"
        f"enable='{_enable_window(overlay.start_time, overlay.duration, total_duration)}'"
        f"[{output_label}]"
    )
