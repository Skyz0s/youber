"""Renombra las pistas descargadas de DistroKid con los títulos reales.

Las descargas del Vault llegan con nombres tipo ``hdJustodelante.wav`` o
``MixeaLowBrighterhdCaos.wav`` (convención de DistroKid/Mixea) y sin
metadatos de título/artista/álbum. Este script:

1. Lee cada página de álbum (con las cookies) para obtener los títulos
   en el orden del álbum.
2. Renombra los ficheros de ``music/<álbum>/`` (ordenados por fecha de
   descarga, que coincide con el orden de la página) a ``<Título>.wav``.
3. Actualiza la base de datos del catálogo: artista = Knight Princess y
   álbum = nombre del álbum.

Uso:

.. code-block:: bash

    python examples/dk_fix_names.py --headers ~/.youber/distrokid_headers.txt \
        --albums ~/.youber/distrokid_albums.txt --music-dir music --artist "Knight Princess"
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from distrokid_download import (  # noqa: E402
    ALBUM_BASE,
    _album_name,
    _album_uuid,
    _browser_headers,
    _parse_headers,
    _safe_name,
    _tracks,
)


def _clean_title(raw: str) -> str:
    """Limpia el título: desentidades HTML y espacios normales."""
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def _album_dir_tracks(album_dir: Path) -> list[Path]:
    """Ficheros de audio del álbum, en orden de descarga (mtime)."""
    files = [p for p in album_dir.iterdir() if p.suffix.lower() in (".wav", ".mp3", ".flac")]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def fix_names(
    headers: dict[str, str],
    uuids: list[str],
    music_dir: Path,
    artist: str,
    dry_run: bool = False,
) -> None:
    """Renombra las pistas y actualiza el catálogo."""
    from youber.music.library import MusicLibrary

    library = MusicLibrary(music_dir)
    renamed = 0
    with httpx.Client(
        headers=_browser_headers(headers), timeout=60, follow_redirects=True
    ) as client:
        for uuid in uuids:
            resp = client.get(f"{ALBUM_BASE}{uuid}")
            if resp.status_code != 200:
                print(f"❌ {uuid}: HTTP {resp.status_code}")
                continue
            html_text = resp.text
            album = _album_name(html_text)
            tracks = _tracks(html_text)
            album_dir = music_dir / album
            if not album_dir.exists():
                print(f"ℹ️  No existe {album_dir} — ¿se descargó?")
                continue
            files = _album_dir_tracks(album_dir)
            if len(files) != len(tracks):
                print(
                    f"⚠️  {album}: {len(files)} ficheros vs {len(tracks)} títulos "
                    f"— salto (revisar manualmente)"
                )
                continue
            for fpath, (raw_title, _vault) in zip(files, tracks, strict=False):
                title = _clean_title(raw_title)
                new_name = _safe_name(title) + fpath.suffix
                target = album_dir / new_name
                if fpath != target:
                    if dry_run:
                        print(f"   {fpath.name} → {new_name}")
                    else:
                        fpath.rename(target)
                        renamed += 1
                # Actualiza el catálogo local (artista + álbum + título).
                track = None
                if not dry_run:
                    track = library.db.get_by_path(target)
                    if track is None:
                        # path antiguo tras el rename: buscar por título previo
                        track = library.db.get_by_path(fpath)
                    if track is not None:
                        track.title = title
                        track.artist = artist
                        track.album = album
                        track.file_path = target
                        library.db.update_track(track)
            print(f"✅ {album}: {len(files)} pistas renombradas")
    library.close()
    print(f"\n🏁 Renombradas: {renamed} fichero(s)" + (" (dry-run)" if dry_run else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headers", required=True, help="Fichero con las cabeceras de Chrome")
    parser.add_argument("--albums", required=True, help="Fichero con las URLs de álbumes")
    parser.add_argument("--music-dir", default="music", help="Directorio del catálogo")
    parser.add_argument("--artist", default="Knight Princess", help="Nombre del artista")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar qué se haría")
    args = parser.parse_args()

    text = Path(args.headers).read_text(encoding="utf-8", errors="replace")
    headers = _parse_headers(text)
    lines = [
        ln.strip()
        for ln in Path(args.albums).read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.strip()
    ]
    uuids = list(dict.fromkeys(_album_uuid(ln) for ln in lines))
    print(f"✅ Cookies OK · {len(uuids)} álbumes")
    fix_names(
        headers=headers,
        uuids=uuids,
        music_dir=Path(args.music_dir),
        artist=args.artist,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
