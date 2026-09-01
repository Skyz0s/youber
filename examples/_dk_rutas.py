"""Prueba rutas alternativas del panel de DistroKid para listar álbumes."""
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

urls = [
    "https://distrokid.com/dashboard/albums/",
    "https://distrokid.com/dashboard/music",
    "https://distrokid.com/dashboard/",
    "https://distrokid.com/vault/",
    "https://distrokid.com/dashboard/album/",
    "https://distrokid.com/artists/",
]

with httpx.Client(headers=base, timeout=60, follow_redirects=True) as client:
    for url in urls:
        try:
            resp = client.get(url)
            body = resp.text
            title = ""
            if "<title>" in body:
                start = body.find("<title>") + 7
                end = body.find("</title>", start)
                title = body[start:end][:70]
            uuids = len(set(re.findall(r"albumuuid=([0-9A-Fa-f-]{36})", body)))
            print(f"{resp.status_code} {url} | title={title!r} | albumuuid={uuids}")
            if uuids:
                # muestra los primeros
                for u in sorted(set(re.findall(r"albumuuid=([0-9A-Fa-f-]{36})", body)))[:20]:
                    print("     ", u)
        except Exception as exc:
            print(f"ERR {url}: {exc}")
