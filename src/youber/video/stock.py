"""Conector de clips de stock (Pexels/Pixabay) para el pipeline de vídeo.

Descarga clips cortos de vídeo (B-roll) con licencia de uso comercial desde
Pexels o Pixabay (APIs públicas con key gratuita) y los deja listos para
usar como ``--clips`` en :mod:`youber.script.builder` / ``youber-script``.

Flujo: guion → keywords por escena → búsqueda en el banco → descarga del
mejor clip por escena → render con música y textos.

Ética: stock footage con licencia libre (Pexels/Pixabay License) — contenido
legítimo, sin scraping ni descargas de plataformas protegidas.

Configuración (cualquiera de las dos; Pexels recomendada):
    PEXELS_API_KEY=...      # https://www.pexels.com/api/ (gratis)
    PIXABAY_API_KEY=...     # https://pixabay.com/api/docs/ (gratis)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import httpx

PEXELS_SEARCH = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH = "https://pixabay.com/api/videos/"


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-").lower() or "clip"


def _pexels_key() -> str | None:
    return os.getenv("PEXELS_API_KEY")


def _pixabay_key() -> str | None:
    return os.getenv("PIXABAY_API_KEY")


def available() -> dict[str, bool]:
    """Qué bancos de stock están configurados."""
    return {"pexels": bool(_pexels_key()), "pixabay": bool(_pixabay_key())}


async def search_pexels(
    query: str, per_page: int = 5, min_width: int = 1280
) -> list[dict]:
    """Busca vídeos en Pexels y devuelve los mejores (HD, con fichero)."""
    key = _pexels_key()
    if not key:
        raise ValueError("Falta PEXELS_API_KEY (https://www.pexels.com/api/)")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            PEXELS_SEARCH,
            params={"query": query, "per_page": per_page, "orientation": "landscape"},
            headers={"Authorization": key},
        )
        resp.raise_for_status()
        data = resp.json()
    results: list[dict] = []
    for video in data.get("videos", []):
        files = video.get("video_files", [])
        best = None
        for f in files:
            if f.get("width", 0) and f["width"] >= min_width:
                best = f
                break
        if best and best.get("link"):
            results.append(
                {
                    "id": video.get("id"),
                    "url": best["link"],
                    "width": best.get("width"),
                    "height": best.get("height"),
                    "duration": video.get("duration"),
                    "source": "pexels",
                }
            )
    return results


async def search_pixabay(query: str, per_page: int = 5) -> list[dict]:
    """Busca vídeos en Pixabay y devuelve los de mayor resolución."""
    key = _pixabay_key()
    if not key:
        raise ValueError("Falta PIXABAY_API_KEY (https://pixabay.com/api/docs/)")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            PIXABAY_SEARCH,
            params={"key": key, "q": query, "per_page": per_page, "video_type": "film"},
        )
        resp.raise_for_status()
        data = resp.json()
    results: list[dict] = []
    for video in data.get("hits", []):
        # Elegimos la mayor resolución disponible
        best = None
        for key_name in ("large", "medium", "small"):
            url = video.get("videos", {}).get(key_name, {}).get("url")
            if url:
                best = url
                break
        if best:
            results.append(
                {
                    "id": video.get("id"),
                    "url": best,
                    "width": video.get("videos", {}).get("large", {}).get("width"),
                    "height": video.get("videos", {}).get("large", {}).get("height"),
                    "duration": video.get("duration"),
                    "source": "pixabay",
                }
            )
    return results


async def download_clip(item: dict, dest_dir: Path, label: str) -> Path | None:
    """Descarga un clip de stock a ``dest_dir/<label>-<id>.mp4``."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{_safe(label)}-{item['source']}-{item['id']}.mp4"
    if target.exists() and target.stat().st_size > 1000:
        return target
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(item["url"])
        resp.raise_for_status()
    target.write_bytes(resp.content)
    return target if target.stat().st_size > 1000 else None


async def fetch_clips_for_scenes(
    scenes: list[dict],
    dest_dir: Path,
    bank: str = "auto",
    per_scene: int = 1,
) -> dict[str, list[Path]]:
    """Para cada escena, busca y descarga clips según sus keywords.

    Args:
        scenes: Lista de dicts con ``title``/``text`` (se usan como query).
        dest_dir: Directorio donde guardar los clips.
        bank: ``"pexels"``, ``"pixabay"`` o ``"auto"`` (elige la configurada).
        per_scene: Clips a descargar por escena.

    Returns:
        Dict ``escena -> [rutas]`` con los clips descargados.
    """
    pexels_ok = bool(_pexels_key())
    pixabay_ok = bool(_pixabay_key())
    if bank == "auto":
        bank = "pexels" if pexels_ok else ("pixabay" if pixabay_ok else "none")
    if bank == "none":
        raise ValueError(
            "No hay key de stock configurada: pon PEXELS_API_KEY o PIXABAY_API_KEY"
        )

    result: dict[str, list[Path]] = {}
    for index, scene in enumerate(scenes):
        query = (scene.get("keywords") or scene.get("text") or scene.get("title") or "")[:100]
        if not query:
            continue
        label = f"escena{index + 1}"
        try:
            if bank == "pexels":
                items = await search_pexels(query, per_page=per_scene + 2)
            else:
                items = await search_pixabay(query, per_page=per_scene + 2)
        except Exception as exc:
            print(f"  ⚠️  {label}: búsqueda falló ({exc})")
            continue
        paths: list[Path] = []
        for item in items[:per_scene]:
            path = await download_clip(item, dest_dir, label)
            if path:
                paths.append(path)
        result[label] = paths
        print(f"  ✅ {label} «{query[:40]}» → {len(paths)} clip(s)")
    return result
