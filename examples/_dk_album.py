"""Inspecciona el HTML de la página del álbum de DistroKid (no descarga)."""
import re
import sys

import httpx

sys.path.insert(0, "examples")
from distrokid_download import _parse_headers  # noqa: E402

text = open(
    r"C:\Users\bypau\.youber\distrokid_headers.txt",
    encoding="utf-8",
    errors="replace",
).read()
headers = _parse_headers(text)

chrome_ua = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
base = {
    "User-Agent": chrome_ua,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es,ca;q=0.9,es;q=0.8",
    "Referer": "https://distrokid.com/dashboard/",
    "Cookie": headers["cookie"],
}

ALBUM_URL = (
    "https://distrokid.com/dashboard/album/"
    "?albumuuid=3106381A-EB94-420B-91EDFEF4DEF34A3E"
)

with httpx.Client(headers=base, timeout=60, follow_redirects=True) as client:
    resp = client.get(ALBUM_URL)
    print(f"status={resp.status_code} len={len(resp.text)}")
    html = resp.text

    # 1) Enlaces de descarga directa (wav/mp3/flac...)
    print("\n== Enlaces de descarga (audio) ==")
    for m in re.finditer(r'href="([^"]+)"', html):
        href = m.group(1)
        if re.search(r"\.(wav|mp3|flac|aiff|m4a|ogg)(\?|$)", href, re.I) or "download" in href.lower():
            print("  ", href[:150])

    # 2) Texto 'Download' / 'Descargar' con su contexto
    print("\n== Texto download/descargar (contexto) ==")
    for m in re.finditer(r"(download|descargar)", html, re.I):
        start = max(0, m.start() - 120)
        ctx = html[start : m.start() + 120]
        ctx = re.sub(r"\s+", " ", ctx)
        print("  …", ctx[:220])

    # 3) Títulos de canciones (patrones típicos: 'songTitle', 'track', h3...)
    print("\n== Posibles títulos de pistas ==")
    for m in re.finditer(r'<(h[1-4]|div|span)[^>]*class="[^"]*(song|track|title)[^"]*"[^>]*>([^<]{2,80})<', html, re.I):
        print("  ", m.group(3).strip()[:80])

    # 4) albumuuid de otros álbumes (para el listado completo)
    print("\n== Otros albumuuid en la página ==")
    uuids = set(re.findall(r"albumuuid=([0-9A-Fa-f-]{36})", html))
    for u in sorted(uuids):
        print("  ", u)
