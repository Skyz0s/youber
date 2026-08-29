"""research_demo.py — Observación educativa de señales del navegador.

Este demo NO evade nada: abre una página y recopila las señales que un
sistema anti-bot podría observar, explicando para qué se usa cada una.
El objetivo es educativo: entender qué información expone un navegador y
por qué existen los sistemas de detección.

Uso: python examples/research_demo.py [--url URL] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from typing import Any

from youber.console import ensure_utf8_console
from youber.core.browser import BrowserManager

DEFAULT_URL = "https://example.com"

SIGNAL_EXPLANATIONS: dict[str, str] = {
    "user_agent": "Identifica navegador/SO. Los bots suelen usar UA antiguas o inconsistentes.",
    "platform": "Plataforma declarada. Inconsistencias con la UA delatan automatización.",
    "language": "Idioma del navegador. Combinaciones raras son señal de entornos de prueba.",
    "languages": "Lista de idiomas preferidos.",
    "webdriver": "Flag que marcan los navegadores controlados por WebDriver/Playwright.",
    "plugins_count": "Número de plugins; los entornos headless suelen reportar 0.",
    "hardware_concurrency": "Núcleos de CPU reportados; entornos virtualizados suelen reportar pocos.",
    "device_memory": "Memoria del dispositivo aproximada (GB).",
    "screen": "Resolución y profundidad de color de la pantalla.",
    "timezone": "Zona horaria del sistema; cruzarla con la IP puede delatar proxies/VPN.",
    "canvas_hash": "Hash del render de canvas: huella gráfica muy estable (fingerprinting).",
    "do_not_track": "Preferencia DNT declarada.",
}


async def collect_signals(url: str) -> dict[str, Any]:
    """Recopila señales observables del navegador sobre la URL indicada.

    Args:
        url: URL a visitar.

    Returns:
        Señales del navegador (UA, webdriver, canvas hash, etc.).
    """
    manager = BrowserManager(headless=True)
    try:
        await manager.launch()
        context = await manager.new_context()
        page = await manager.new_page(context)
        await manager.navigate(page, url)
        raw = await page.evaluate(
            """() => {
                const canvas = document.createElement('canvas');
                canvas.width = 200;
                canvas.height = 60;
                const ctx = canvas.getContext('2d');
                ctx.textBaseline = 'top';
                ctx.font = '14px Arial';
                ctx.fillStyle = '#f60';
                ctx.fillRect(0, 0, 200, 60);
                ctx.fillStyle = '#069';
                ctx.fillText('BARF research demo', 10, 20);
                return {
                    user_agent: navigator.userAgent,
                    platform: navigator.platform,
                    language: navigator.language,
                    languages: navigator.languages,
                    webdriver: navigator.webdriver,
                    plugins_count: navigator.plugins.length,
                    hardware_concurrency: navigator.hardwareConcurrency,
                    device_memory: navigator.deviceMemory ?? null,
                    screen: [screen.width, screen.height, screen.colorDepth],
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    canvas_data_url: canvas.toDataURL(),
                    do_not_track: navigator.doNotTrack ?? null,
                };
            }"""
        )
        canvas_data: str = raw.pop("canvas_data_url")
        raw["canvas_hash"] = hashlib.sha256(canvas_data.encode()).hexdigest()[:16]
        return raw
    finally:
        await manager.close()


def print_report(signals: dict[str, Any]) -> None:
    """Imprime el reporte explicado de las señales observadas."""
    print("\n" + "=" * 70)
    print("SEÑALES OBSERVABLES DEL NAVEGADOR (estudio educativo)")
    print("=" * 70)
    for key, value in signals.items():
        explanation = SIGNAL_EXPLANATIONS.get(key, "")
        print(f"\n• {key}: {value}")
        if explanation:
            print(f"  → {explanation}")
    print("\n" + "=" * 70)
    print("Estas señales son las mismas que cualquier web recibe al visitarla.")
    print("Estudiarlas sirve para entender la detección y defender la privacidad;")
    print("NO se usan para evadir sistemas de seguridad.")
    print("=" * 70)


def main() -> None:
    """Entry point del demo."""
    ensure_utf8_console()
    parser = argparse.ArgumentParser(description="Observación educativa de señales del navegador")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"URL a visitar (por defecto: {DEFAULT_URL})")
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args()

    signals = asyncio.run(collect_signals(args.url))
    if args.json:
        print(json.dumps(signals, indent=2, ensure_ascii=False))
    else:
        print_report(signals)


if __name__ == "__main__":
    main()
