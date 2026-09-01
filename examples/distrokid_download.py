"""Descarga el catálogo propio de DistroKid a ``music/<álbum>/<canción>``.

Uso legítimo: descarga **tu propia música** (tu cuenta de artista) desde el
panel de tu distribuidora. Nada de contenido ajeno.

Cómo funciona:
- Usa las **cookies de tu sesión** de DistroKid (copiadas desde Chrome,
  igual que con YouTube Music).
- Trabaja con **URLs de álbumes** (``/dashboard/album/?albumuuid=...``):
  el listado ``/dashboard/music/`` está detrás del challenge de Cloudflare,
  pero las páginas de álbum responden bien con las cookies.
- En cada álbum lee los enlaces del Vault (``/vault/download/?id=...``) y
  descarga cada pista a ``music/<álbum>/<título>-mastered.wav``.

Uso:

.. code-block:: bash

    # lista álbumes y pistas (no descarga)
    python examples/distrokid_download.py --headers ~/.youber/distrokid_headers.txt \
        --albums albumes.txt --dry-run

    # descarga todo
    python examples/distrokid_download.py --headers ~/.youber/distrokid_headers.txt \
        --albums albumes.txt --out music

``albumes.txt``: una URL de álbum por línea (o un albumuuid suelto).
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import httpx

DEFAULT_OUT = Path("music")
ALBUM_BASE = "https://distrokid.com/dashboard/album/?albumuuid="
VAULT_BASE = "https://distrokid.com/vault/download/?id="
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _parse_headers(text: str) -> dict[str, str]:
    """Parsea cabeceras copiadas de Chrome (formatos antiguo y nuevo).

    - Antiguo: ``Nombre: valor`` en la misma línea.
    - Nuevo (Chrome 151+): nombre y valor en **líneas separadas**.
      Los pseudo-headers (``:authority``...) se ignoran con su valor.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("El pegado está vacío")

    headers: dict[str, str] = {}

    def _set(name: str, value: str) -> None:
        name = name.strip().lower()
        value = value.strip()
        if name == "cookie":
            headers["cookie"] = value
        elif name in ("user-agent", "accept-language"):
            headers[name] = value

    new_format = any(":" not in line for line in lines[:10])
    if new_format:
        index = 0
        while index < len(lines):
            name = lines[index]
            if name.startswith(":"):
                index += 2  # pseudo-header + su valor
                continue
            value = lines[index + 1] if index + 1 < len(lines) else ""
            _set(name, value)
            index += 2
    else:
        for line in lines:
            if ":" not in line:
                continue
            name, _, value = line.partition(":")
            _set(name, value)

    if "cookie" not in headers:
        raise ValueError("No encontré la cabecera Cookie en el pegado")
    headers.setdefault("user-agent", CHROME_UA)
    return headers


def _browser_headers(headers: dict[str, str]) -> dict[str, str]:
    """Cabeceras completas de navegador para evitar el challenge de Cloudflare."""
    return {
        "User-Agent": headers.get("user-agent", CHROME_UA),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": headers.get("accept-language", "es,ca;q=0.9,es;q=0.8"),
        "Referer": "https://distrokid.com/dashboard/",
        "Cookie": headers["cookie"],
    }


def _safe_name(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", text).strip().rstrip(".").strip() or "sin-titulo"


def _album_uuid(value: str) -> str:
    """Extrae el albumuuid de una URL o acepta el uuid suelto.

    DistroKid usa un identificador propio (grupos 8-4-4-16, ~35 chars),
    no un UUID estándar, así que la validación es flexible.
    """
    match = re.search(r"albumuuid=([0-9A-Za-z-]{24,48})", value)
    if match:
        return match.group(1)
    value = value.strip()
    if re.fullmatch(r"[0-9A-Za-z-]{24,48}", value):
        return value
    raise ValueError(f"No reconozco el albumuuid en: {value!r}")


def _album_name(html: str) -> str:
    """Nombre del álbum desde el <title> ('Knight Princess - Pimennys - DistroKid')."""
    m = re.search(r"<title>([^<]+)</title>", html)
    if not m:
        return "album"
    parts = [p.strip() for p in m.group(1).split("-") if p.strip()]
    parts = [p for p in parts if p.lower() not in ("distrokid",)]
    return _safe_name(parts[-1] if parts else "album")


def _tracks(html: str) -> list[tuple[str, str]]:
    """Devuelve ``[(título, vault_id)]`` de la página del álbum.

    El HTML tiene, por pista: una celda ``track-name`` con el título y una
    celda ``track-download`` con el enlace ``/vault/download/?id=...``,
    ambos en el mismo orden.
    """
    titles = re.findall(
        r'class="track-cell track-name[^"]*"[^>]*>(.*?)</div>', html, re.S | re.I
    )
    ids = re.findall(r"/vault/download/\?id=([A-Za-z0-9]+)", html)
    clean_titles: list[str] = []
    for raw in titles:
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            clean_titles.append(text)
    return list(zip(clean_titles, ids, strict=False))


def run(headers: dict[str, str], albums: list[str], dry_run: bool, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    uuids = [_album_uuid(a) for a in albums]
    print(f"📀 Álbumes a procesar: {len(uuids)}")
    if dry_run:
        print("   (dry-run: solo se listan pistas, no se descarga)")

    with httpx.Client(
        headers=_browser_headers(headers), timeout=120, follow_redirects=True
    ) as client:
        total_downloaded = 0
        for pos, uuid in enumerate(uuids, start=1):
            album_url = f"{ALBUM_BASE}{uuid}"
            print(f"\n📀 [{pos}/{len(uuids)}] {album_url}")
            try:
                resp = client.get(album_url)
            except httpx.HTTPStatusError as exc:
                print(f"   ❌ HTTP {exc.response.status_code} — saltando")
                continue
            if resp.status_code != 200:
                print(f"   ❌ status {resp.status_code} — saltando")
                continue
            html = resp.text
            if "<title>Just a moment" in html:
                print("   ❌ Challenge de Cloudflare — saltando")
                continue
            name = _album_name(html)
            tracks = _tracks(html)
            print(f"   Álbum: {name} · {len(tracks)} pistas")
            if not tracks:
                print("   ℹ️  Sin pistas detectadas")
                continue

            album_dir = out_dir / name
            album_dir.mkdir(parents=True, exist_ok=True)
            for track_title, vault_id in tracks:
                print(f"   🎵 {track_title} (vault={vault_id})")
                if dry_run:
                    continue
                dl = client.get(f"{VAULT_BASE}{vault_id}")
                if dl.status_code != 200 or len(dl.content) < 10_000:
                    print(f"      ❌ status {dl.status_code} — no guardado")
                    continue
                # nombre de fichero: content-disposition o título
                cd = dl.headers.get("content-disposition", "")
                m = re.search(r'filename="?([^";]+)"?', cd)
                fname = m.group(1) if m else f"{_safe_name(track_title)}.wav"
                target = album_dir / _safe_name(fname)
                target.write_bytes(dl.content)
                print(f"      ✅ {target.name} ({len(dl.content):,} bytes)")
                total_downloaded += 1
                time.sleep(0.5)  # cortesía

        print(f"\n🏁 Listo. Descargadas: {total_downloaded} pistas en {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headers", required=True, help="Fichero con las cabeceras de Chrome")
    parser.add_argument(
        "--albums",
        help="Fichero con una URL de álbum (o albumuuid) por línea",
    )
    parser.add_argument("--album", action="append", default=[], help="URL/uuid de un álbum (repetible)")
    parser.add_argument("--dry-run", action="store_true", help="Solo listar (no descarga)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Directorio de salida")
    args = parser.parse_args()

    albums: list[str] = list(args.album)
    if args.albums:
        albums.extend(
            line.strip()
            for line in Path(args.albums).read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        )
    if not albums:
        print("❌ Indica --albums <fichero> o --album <url> (repetible)")
        raise SystemExit(1)

    text = Path(args.headers).read_text(encoding="utf-8", errors="replace")
    try:
        headers = _parse_headers(text)
    except ValueError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc
    print(f"✅ Cookies leídas ({len(headers.get('cookie', ''))} caracteres).")
    run(headers=headers, albums=albums, dry_run=args.dry_run, out_dir=Path(args.out))


if __name__ == "__main__":
    main()
