"""Convierte las cabeceras copiadas de Chrome/Edge en el fichero de YouTube Music.

El ``setup()`` de ytmusicapi 1.12+ espera cabeceras en formato
``nombre: valor`` (una línea por cabecera), pero Chrome/Edge modernos
(150+) copian en el formato nuevo: **nombre y valor en líneas separadas**
(sin dos puntos), incluyendo pseudo-cabeceras ``:authority``/``:method``.
Este script entiende ambos formatos y genera
``~/.youber/ytmusic_headers.json`` listo para BARF.

Uso:

1. Abre https://music.youtube.com logueado.
2. F12 → Network → F5 → clic en una petición ``browse`` o ``next``.
3. En Request Headers → clic derecho → Copy → Copy request headers.
4. Pega aquí abajo y pulsa Enter, Ctrl+Z, Enter (fin de entrada):

    python examples/ytmusic_headers_from_chrome.py

También acepta un fichero: ``python examples/ytmusic_headers_from_chrome.py pegado.txt``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TARGET = Path.home() / ".youber" / "ytmusic_headers.json"

# Cabeceras que no se copian al fichero (ruido o secretos de red).
_SKIP_PREFIX = ("sec-", "x-browser-", ":")
_SKIP_EXACT = {
    "host",
    "content-length",
    "accept-encoding",
    "pragma",
    "cache-control",
    "priority",
    "upgrade-insecure-requests",
    "decodificados",
    "decoded",
}


def parse_chrome_headers(lines: list[str]) -> dict[str, str]:
    """Parsea el pegado de Chrome en formato clásico o de líneas separadas."""
    headers: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue

        # Artefactos de la UI de Chrome ("Decodificados:" / "Decoded:").
        if line.lower().startswith(("decodificados", "decoded")):
            continue

        # Formato clásico: "nombre: valor" en la misma línea.
        if ": " in line:
            key, _, value = line.partition(": ")
            key = key.strip().lower()
            value = value.strip()
            if key and value:
                headers[key] = value
            continue

        # Pseudo-cabecera (":authority"): ignorar línea y su valor.
        if line.startswith(":"):
            index += 1
            continue

        # Formato nuevo: "nombre" en esta línea, "valor" en la siguiente.
        key = line.lower()
        if index < len(lines) and lines[index].strip():
            headers[key] = lines[index].strip()
            index += 1
    return headers


def ensure_authorization(headers: dict[str, str]) -> dict[str, str]:
    """Genera el header ``authorization`` (SAPISIDHASH) si falta.

    ytmusicapi 1.12+ solo reconoce las cabeceras como autenticación de
    navegador si incluyen ``authorization: SAPISIDHASH…``. Ese valor se
    calcula a partir de la cookie ``__Secure-3PAPISID`` y el origen, así
    que podemos generarlo sin que el usuario tenga que copiar de una
    petición concreta.
    """
    if "authorization" in headers:
        return headers
    from ytmusicapi.helpers import get_authorization, sapisid_from_cookie

    # El hash se firma con el origen del sitio: las llamadas de BARF van a
    # music.youtube.com, así que forzamos ese origen aunque el pegado sea
    # de www.youtube.com.
    origin = "https://music.youtube.com"
    try:
        sapisid = sapisid_from_cookie(headers.get("cookie", ""))
    except Exception:
        sapisid = None
    if sapisid:
        headers["authorization"] = get_authorization(f"{sapisid} {origin}")
        headers["origin"] = origin
    return headers


def clean_headers(headers: dict[str, str]) -> dict[str, str]:
    """Filtra cabeceras irrelevantes y normaliza claves a minúsculas."""
    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.strip().lower()
        if not lowered or not value:
            continue
        if lowered in _SKIP_EXACT:
            continue
        if lowered.startswith(_SKIP_PREFIX):
            continue
        cleaned[lowered] = value.strip()
    return cleaned


def build_headers_file(lines: list[str], target: Path = TARGET) -> dict[str, str]:
    """Parsea, limpia, genera la autorización y guarda el fichero."""
    parsed = parse_chrome_headers(lines)
    headers = clean_headers(parsed)
    headers = ensure_authorization(headers)

    missing: list[str] = []
    if "cookie" not in headers:
        missing.append("cookie")
    if "authorization" not in headers:
        missing.append("authorization (SAPISIDHASH)")
    if "x-goog-authuser" not in headers:
        # ytmusicapi lo añade por defecto; lo ponemos explícito.
        headers["x-goog-authuser"] = "0"
    if missing:
        raise ValueError(
            "Faltan cabeceras necesarias: " + ", ".join(missing)
            + ". Copia desde www.youtube.com o music.youtube.com "
            "(una petición con cookie de sesión) y repite."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(headers, indent=2, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    return headers


def main() -> None:
    """Lee el pegado (stdin o fichero) y genera el fichero de headers."""
    if len(sys.argv) > 1:
        lines = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
        source = sys.argv[1]
    else:
        print("Pega las cabeceras (Copy request headers) y pulsa Enter, Ctrl+Z, Enter:")
        lines = sys.stdin.read().splitlines()
        source = "stdin"

    try:
        headers = build_headers_file(lines)
    except ValueError as exc:
        print(f"✗ {exc}")
        raise SystemExit(1) from exc

    print(f"✅ Cabeceras guardadas en {TARGET}")
    print(f"   ({len(headers)} cabeceras, incluye cookie y x-goog-authuser)")
    print("Recarga el dashboard (http://127.0.0.1:8787) y pulsa 'Importar'.")


if __name__ == "__main__":
    main()
