"""Inspecciona el álbum de DistroKid: títulos de pistas, otros álbumes y descarga de prueba."""
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

    # 1) Títulos de pistas: buscar la celda de nombre en la fila de cada track.
    #    Estructura: track-cell track-name ... <a ...>Título</a> o span con el título.
    print("\n== Celdas track-name (títulos) ==")
    titles = re.findall(
        r'class="track-cell track-name[^"]*"[^>]*>(.*?)</div>',
        html,
        re.S | re.I,
    )
    for t in titles[:20]:
        clean = re.sub(r"<[^>]+>", " ", t)
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean:
            print("  •", clean[:80])

    # 2) Alt de miniaturas (a veces llevan el título)
    print("\n== alt de imágenes ==")
    alts = re.findall(r'alt="([^"]{2,80})"', html)
    seen = set()
    for a in alts:
        if a not in seen and "distrokid" not in a.lower():
            seen.add(a)
            print("  •", a[:80])

    # 3) Otros albumuuid en la página (navegación entre álbumes)
    print("\n== albumuuid en la página ==")
    uuids = sorted(set(re.findall(r"albumuuid=([0-9A-Fa-f-]{36})", html)))
    for u in uuids:
        print("  ", u)

    # 4) Probamos el primer enlace de descarga (solo cabeceras, no guardamos)
    print("\n== Prueba de descarga /vault/download/?id=hU40A ==")
    dl = client.get("https://distrokid.com/vault/download/?id=hU40A")
    print(f"   status={dl.status_code} len={len(dl.content)}")
    print(f"   content-type={dl.headers.get('content-type')}")
    print(f"   content-disposition={dl.headers.get('content-disposition')}")
    ct = dl.headers.get("content-type", "")
    if "text/html" in ct:
        title = re.search(r"<title>([^<]+)</title>", dl.text)
        print(f"   title={title.group(1) if title else '-'}")
        print(f"   snippet: {re.sub(chr(10), ' ', dl.text[:200])}")
