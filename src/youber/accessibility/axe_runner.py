"""Ejecución de auditorías de accesibilidad con axe-core.

``AxeRunner`` inyecta axe-core (vendored en ``youber/assets/axe.min.js``) en
una página y ejecuta ``axe.run()`` con opciones configurables: contexto,
reglas/tags concretos y filtro por nivel de impacto. Los resultados se pueden
cachear por (URL, opciones) para auditorías repetidas.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Page
from pydantic import BaseModel, Field

_AXE_JS = (
    Path(__file__).resolve().parent.parent / "assets" / "axe.min.js"
).read_text(encoding="utf-8")

IMPACT_LEVELS = ("critical", "serious", "moderate", "minor")


class AxeResults(BaseModel):
    """Resultado estructurado de una auditoría axe-core.

    Attributes:
        url: URL auditada.
        timestamp: Momento de la auditoría (UTC).
        violations: Reglas incumplidas (con nodos afectados).
        passes: Reglas superadas.
        incomplete: Reglas que requieren revisión manual.
        inapplicable: Reglas que no aplican a la página.
    """

    url: str = Field(description="URL auditada")
    timestamp: datetime = Field(description="Momento de la auditoría (UTC)")
    violations: list[dict[str, Any]] = Field(default_factory=list)
    passes: list[dict[str, Any]] = Field(default_factory=list)
    incomplete: list[dict[str, Any]] = Field(default_factory=list)
    inapplicable: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def total_violations(self) -> int:
        """Número total de violaciones."""
        return len(self.violations)

    def violations_by_impact(self) -> dict[str, int]:
        """Conteo de violaciones agrupadas por nivel de impacto."""
        counts: dict[str, int] = {level: 0 for level in IMPACT_LEVELS}
        for violation in self.violations:
            impact = violation.get("impact", "unknown")
            counts[impact] = counts.get(impact, 0) + 1
        return counts


class AxeRunner:
    """Ejecuta auditorías de accesibilidad con axe-core.

    Args:
        use_cache: Cachear resultados por (URL, opciones) dentro de la misma
            instancia.
    """

    def __init__(self, use_cache: bool = True) -> None:
        self.use_cache = use_cache
        self._cache: dict[tuple[str, str], AxeResults] = {}

    async def run_axe(
        self,
        page: Page,
        options: dict[str, Any] | None = None,
    ) -> AxeResults:
        """Ejecuta una auditoría axe-core sobre la página indicada.

        Args:
            page: Página de Playwright a auditar.
            options: Opciones de la auditoría:
                - ``context``: selector CSS (str) o definición de contexto
                  para ``axe.run`` (p. ej. ``{"include": [["#main"]]}``).
                - ``rules``: lista de IDs de reglas a ejecutar (``runOnly``).
                - ``tags``: lista de tags WCAG (p. ej. ``["wcag2a"]``).
                - ``impactLevels``: lista de impactos a conservar, p. ej.
                  ``["critical", "serious"]``.

        Returns:
            Resultados de la auditoría (:class:`AxeResults`).
        """
        normalized = options or {}
        cache_key = (
            page.url,
            json.dumps(normalized, sort_keys=True, default=str),
        )
        if self.use_cache and cache_key in self._cache:
            logger.debug(f"Auditoría servida desde caché: {page.url}")
            return self._cache[cache_key]

        await self._ensure_axe(page)
        raw = await page.evaluate(
            "(args) => axe.run(args.context || document, args.options)",
            {
                "context": normalized.get("context"),
                "options": self._build_options(normalized),
            },
        )
        results = self._from_raw(page.url, raw, normalized)

        if self.use_cache:
            self._cache[cache_key] = results
        logger.info(f"Auditoría completada: {results.total_violations} violaciones en {page.url}")
        return results

    def clear_cache(self) -> None:
        """Vacía la caché de resultados."""
        self._cache.clear()

    @staticmethod
    def _build_options(options: dict[str, Any]) -> dict[str, Any]:
        axe_options: dict[str, Any] = {}
        run_only: dict[str, Any] | None = None
        if options.get("rules"):
            run_only = {"type": "rule", "values": options["rules"]}
        elif options.get("tags"):
            run_only = {"type": "tag", "values": options["tags"]}
        if run_only:
            axe_options["runOnly"] = run_only
        return axe_options

    @staticmethod
    async def _ensure_axe(page: Page) -> None:
        """Inyecta axe-core en la página si aún no está presente."""
        has_axe = await page.evaluate("typeof axe !== 'undefined'")
        if not has_axe:
            await page.add_script_tag(content=_AXE_JS)

    def _from_raw(
        self,
        url: str,
        raw: dict[str, Any],
        options: dict[str, Any],
    ) -> AxeResults:
        impact_levels = options.get("impactLevels")
        return AxeResults(
            url=url,
            timestamp=datetime.now(UTC),
            violations=self._filter_impact(raw.get("violations", []), impact_levels),
            passes=list(raw.get("passes", [])),
            incomplete=self._filter_impact(raw.get("incomplete", []), impact_levels),
            inapplicable=list(raw.get("inapplicable", [])),
        )

    @staticmethod
    def _filter_impact(
        items: list[dict[str, Any]],
        impact_levels: Any,
    ) -> list[dict[str, Any]]:
        if not impact_levels:
            return items
        allowed = set(impact_levels)
        return [item for item in items if item.get("impact") in allowed]
