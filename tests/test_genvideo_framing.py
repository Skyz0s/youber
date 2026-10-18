"""Tests de los encuadres derivados (`youber.genvideo.framing`)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from youber.genvideo.framing import OUT_SIZE, detail, punch_in, variant


def _quadrants(path: Path, size: tuple[int, int] = (400, 240)) -> Path:
    """Imagen con cuatro cuadrantes de colores para comprobar recortes."""
    img = Image.new("RGB", size, (0, 0, 0))
    w, h = size
    img.paste((255, 0, 0), (0, 0, w // 2, h // 2))          # arriba-izq rojo
    img.paste((0, 255, 0), (w // 2, 0, w, h // 2))          # arriba-der verde
    img.paste((0, 0, 255), (0, h // 2, w // 2, h))          # abajo-izq azul
    img.paste((255, 255, 0), (w // 2, h // 2, w, h))        # abajo-der amarillo
    img.save(path, "PNG")
    return path


def _center_color(path: Path) -> tuple[int, int, int]:
    with Image.open(path) as img:
        w, h = img.size
        return img.convert("RGB").getpixel((w // 2, h // 2))


def test_punch_in_devuelve_tamano_de_trabajo(tmp_path: Path) -> None:
    src = _quadrants(tmp_path / "src.png")
    out = punch_in(src, tmp_path / "punch.png", factor=1.5)
    with Image.open(out) as img:
        assert img.size == OUT_SIZE


def test_punch_in_mantiene_el_centro(tmp_path: Path) -> None:
    """Un punch-in centrado no debe quedarse con un solo cuadrante."""
    src = _quadrants(tmp_path / "src.png")
    out = punch_in(src, tmp_path / "punch.png", factor=1.2)
    color = _center_color(out)
    # en el centro de la imagen original hay mezcla: ningun canal debe ser 0 o 255 puro
    assert all(0 < canal < 255 for canal in color)


def test_detail_recorta_la_zona_pedida(tmp_path: Path) -> None:
    src = _quadrants(tmp_path / "src.png")
    out = detail(src, tmp_path / "detail.png", center=(0.25, 0.25), zoom=3.0)
    with Image.open(out) as img:
        assert img.size == OUT_SIZE
    r, g, b = _center_color(out)
    assert r > 200 and g < 60 and b < 60  # cuadrante rojo


def test_variant_despacha_por_tipo(tmp_path: Path) -> None:
    src = _quadrants(tmp_path / "src.png")
    punch = variant(src, tmp_path / "v1.png", "punch", factor=1.3)
    det = variant(src, tmp_path / "v2.png", "detail", center=(0.75, 0.75), zoom=3.0)
    assert punch.exists() and det.exists()
    r, g, b = _center_color(det)
    assert r > 200 and g > 200 and b < 60  # cuadrante amarillo
