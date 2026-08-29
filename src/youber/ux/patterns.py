"""Detección de patrones de navegación (uso educativo).

Analiza historiales de páginas (URLs y tiempos) para clasificar el patrón de
navegación del usuario: breadcrumb, búsqueda, filtros, checkout, paginación,
contenido... El objetivo es aprender a leer la intención del usuario a partir
de las URLs.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from typing import Any
from urllib.parse import parse_qs, urlparse

SEARCH_PARAMS = ("q", "query", "search", "s", "busqueda", "keyword")
FILTER_PARAMS = (
    "filter",
    "filtro",
    "category",
    "categoria",
    "sort",
    "orden",
    "price",
    "precio",
    "brand",
)
CHECKOUT_SEGMENTS = ("cart", "checkout", "payment", "pago", "order", "pedido", "confirm")
PAGINATION_PARAMS = ("page", "pagina", "p", "offset")
PAGINATION_PATH = re.compile(r"/page[/-]?\d+", re.IGNORECASE)
CONTENT_PATH = re.compile(r"/(product|item|video|watch|articulo|post)/", re.IGNORECASE)


def _step_to_url(step: Any) -> str:
    """Extrae la URL de un paso del historial (dict, objeto o cadena)."""
    if isinstance(step, dict):
        return step.get("url", "")
    return getattr(step, "url", str(step))


def detect_navigation_pattern(page_history: list[Any]) -> dict[str, Any]:
    """Detecta patrones de navegación en un historial de páginas.

    Args:
        page_history: Lista de pasos (dicts con "url" o cadenas URL).

    Returns:
        Patrones detectados con evidencias, patrón dominante y progresión
        de profundidad de ruta.
    """
    urls = [_step_to_url(step) for step in page_history]
    total = len(urls)
    patterns: dict[str, dict[str, Any]] = {}

    def add(pattern: str, url: str) -> None:
        entry = patterns.setdefault(pattern, {"count": 0, "urls": []})
        entry["count"] += 1
        entry["urls"].append(url)

    for url in urls:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        path = parsed.path.lower()

        if any(key in query for key in SEARCH_PARAMS):
            add("search", url)
        if any(key in query for key in FILTER_PARAMS):
            add("filter", url)
        if any(segment in path for segment in CHECKOUT_SEGMENTS):
            add("checkout", url)
        if any(key in query for key in PAGINATION_PARAMS) or PAGINATION_PATH.search(path):
            add("pagination", url)
        if CONTENT_PATH.search(path):
            add("content", url)

    # Breadcrumb: cadena de rutas donde cada una es extensión de la anterior.
    max_chain = 0
    chain = 0
    previous_path: str | None = None
    for url in urls:
        path = urlparse(url).path.rstrip("/") or "/"
        if previous_path is not None and path.startswith(previous_path) and len(path) > len(previous_path):
            chain += 1
        else:
            chain = 1
        max_chain = max(max_chain, chain)
        previous_path = path
    if max_chain >= 2:
        patterns["breadcrumb"] = {"count": max_chain, "urls": urls}

    dominant = max(patterns, key=lambda key: patterns[key]["count"]) if patterns else None
    return {
        "total_steps": total,
        "patterns": patterns,
        "dominant": dominant,
        "depth_progression": [
            len([segment for segment in urlparse(url).path.split("/") if segment])
            for url in urls
        ],
    }


async def analyze_click_flow(
    page: Any,
    elements: list[str],
    sessions: int = 8,
    clicks_per_session: int = 3,
    seed: int = 42,
) -> dict[str, Any]:
    """Simula sesiones de clics sobre los elementos indicados y las analiza.

    Cada sesión abre una página nueva (contexto aislado), hace clic en
    ``clicks_per_session`` elementos en orden aleatorio (semilla fija para
    reproducibilidad) y registra si el clic funcionó y si provocó navegación.

    Args:
        page: Página de Playwright (se usa su navegador para las sesiones).
        elements: Selectores de elementos clicables a estudiar.
        sessions: Número de sesiones simuladas.
        clicks_per_session: Clics por sesión.
        seed: Semilla del generador aleatorio (resultados reproducibles).

    Returns:
        Secuencias de clics más comunes, tasas de éxito por elemento y total.

    Raises:
        RuntimeError: si la página no tiene navegador asociado.
    """
    browser = page.context.browser
    if browser is None:
        raise RuntimeError("La página no tiene navegador asociado")

    rng = random.Random(seed)
    stats = {element: {"found": 0, "navigated": 0, "failed": 0} for element in elements}
    sequences: list[tuple[str, ...]] = []
    base_url = page.url

    for _ in range(sessions):
        context = await browser.new_context()
        try:
            session_page = await context.new_page()
            await session_page.goto(base_url, wait_until="domcontentloaded")
            sequence: list[str] = []
            for _ in range(clicks_per_session):
                chosen = rng.choice(elements)
                locator = session_page.locator(chosen)
                if await locator.count() == 0:
                    stats[chosen]["failed"] += 1
                    continue
                stats[chosen]["found"] += 1
                before = session_page.url
                try:
                    await locator.first.click(timeout=2000)
                    await session_page.wait_for_load_state("domcontentloaded")
                    if session_page.url != before:
                        stats[chosen]["navigated"] += 1
                except Exception:
                    stats[chosen]["failed"] += 1
                sequence.append(chosen)
            sequences.append(tuple(sequence))
        finally:
            await context.close()

    counts = Counter(sequences)
    top = [{"sequence": list(seq), "count": n} for seq, n in counts.most_common(5)]
    return {
        "sessions": sessions,
        "clicks_per_session": clicks_per_session,
        "top_sequences": top,
        "unique_sequences": len(counts),
        "element_stats": stats,
    }
