"""Encuadres derivados de un still: mas planos sin regenerar la imagen.

De un unico PNG se sacan variantes que se leen como cobertura distinta:

- ``punch_in``: acerca el encuadre (1,2-2,0x) manteniendo el centro.
- ``detail``: recorta una zona (pies, manos, picaporte, grieta) con un centro
  expresado en fracciones del ancho/alto.

Todas las variantes salen ya a la resolucion de trabajo del modelo
(1280x704, multiplos de 32) para que no haya reescalados raros despues.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PIL.Image import Resampling

#: Resolucion de trabajo del modelo (multiplos de 32).
OUT_SIZE = (1280, 704)


def _fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Recorta al aspecto pedido y redimensiona sin deformar."""
    target_w, target_h = size
    target_ratio = target_w / target_h
    w, h = img.size
    ratio = w / h
    if ratio > target_ratio:  # sobra ancho
        new_w = int(round(h * target_ratio))
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    elif ratio < target_ratio:  # sobra alto
        new_h = int(round(w / target_ratio))
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    return img.resize(size, Resampling.LANCZOS)


def punch_in(src: Path, out: Path, factor: float = 1.35, size: tuple[int, int] = OUT_SIZE) -> Path:
    """Acerca el encuadre ``factor`` veces manteniendo el centro."""
    with Image.open(src) as opened:
        img = opened.convert("RGB")
        w, h = img.size
        cw, ch = int(w / factor), int(h / factor)
        left, top = (w - cw) // 2, (h - ch) // 2
        crop = img.crop((left, top, left + cw, top + ch))
        _fit(crop, size).save(out, "PNG")
    return out


def detail(
    src: Path,
    out: Path,
    center: tuple[float, float] = (0.5, 0.5),
    zoom: float = 1.9,
    size: tuple[int, int] = OUT_SIZE,
) -> Path:
    """Recorta una zona alrededor de ``center`` (fracciones 0-1) y la agranda."""
    with Image.open(src) as opened:
        img = opened.convert("RGB")
        w, h = img.size
        cw, ch = int(w / zoom), int(h / zoom)
        cx, cy = float(center[0]) * w, float(center[1]) * h
        left = int(min(max(cx - cw / 2, 0), w - cw))
        top = int(min(max(cy - ch / 2, 0), h - ch))
        crop = img.crop((left, top, left + cw, top + ch))
        _fit(crop, size).save(out, "PNG")
    return out


def variant(
    src: Path,
    out: Path,
    kind: str,
    *,
    factor: float = 1.35,
    center: tuple[float, float] = (0.5, 0.5),
    zoom: float = 1.9,
) -> Path:
    """``kind`` = ``punch`` o ``detail``."""
    if kind == "punch":
        return punch_in(src, out, factor)
    if kind == "detail":
        return detail(src, out, center, zoom)
    raise ValueError(f"tipo de encuadre desconocido: {kind}")
