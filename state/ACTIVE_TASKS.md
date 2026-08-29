# 🗂️ Tareas Activas — BARF

> Estado del proyecto, actualizado en cada fase.

## Fase 7: Publicación en PyPI + GitHub Release — ✅ Completada

- [x] `pyproject.toml` verificado (name youber, v0.1.0, deps, scripts, package-data axe-core, pre-commit en dev)
- [x] `MANIFEST.in` (spec de Skyzo) + `.pre-commit-config.yaml` + `CHANGELOG.md` (0.1.0)
- [x] Build local: `python -m build` → **twine check PASSED** (wheel + sdist)
- [x] **PyPI publicado: `youber 0.1.0` live** (https://pypi.org/project/youber/0.1.0/)
- [x] **Repo GitHub: https://github.com/Skyz0s/youber** (público, push desde `projects/barf/` como repo nuevo, 84 ficheros limpios)
- [x] **CI verde** (Python 3.11 + 3.12: ruff, mypy, 59 tests, coverage) — fix de headless en tests MCP (CI no tiene display X)
- [x] **Release v0.1.0**: https://github.com/Skyz0s/youber/releases/tag/v0.1.0 + workflow Publish OK (guard: salta si la versión ya está en PyPI)
- [ ] Trusted Publishing en PyPI (para futuros releases sin token) — pendiente de Skyzo
- [ ] Revocar el token de PyPI usado en el chat (recomendado)

## Fase 6: Cliente MCP + Investigación anti-bot + Publicación — ✅ Completada

- [x] Cliente `youber/client/` (session, tools, interactive + `youber-client`)
- [x] Herramientas sandbox en el servidor (simulate_geolocation/network/device)
- [x] `docs/ANTI_BOT_RESEARCH.md` + `docs/RESEARCH.md` + `examples/research_demo.py`
- [x] Publicación: README público, LICENSE (MIT), pyproject para PyPI (name `youber`, v0.1.0)
- [x] Tests: `test_mcp_client.py` (7 e2e, servidor real por stdio) + `test_interactive.py` (5)
- [x] Docs: `CLIENT.md`, `PUBLISHING.md`
- [x] Verificación: **pytest → 59 passed** (44-48s) + ruff + mypy limpios

## Fase 5: MCP 2.x + Estudio UX + CI/CD — ✅ Completada

- [x] Migración a MCP SDK 2.x (`MCPServer`, `mcp>=2.0.0,<3`, respuestas JSON vía `model_dump`)
- [x] `docs/MCP_SERVER.md` actualizado (2.x + sección de migración)
- [x] Módulo `youber/ux/` (patterns, heatmap, journey, report) + fixtures mini-site
- [x] `tests/test_ux.py` (8 tests)
- [x] `.github/workflows/ci.yml` (lint + typecheck + tests + coverage)
- [x] Config ruff + mypy en `pyproject.toml`
- [x] Verificación: `pytest` → **47 passed**

## Fase 4: Accesibilidad ampliada + ejemplos + sandbox — ✅ Completada

- [x] Módulo `youber/accessibility` (AxeRunner con caché, reporters, wcag 70+ reglas, recomendaciones)
- [x] Módulo `youber/sandbox` (geolocalización 10 regiones, red 5 perfiles, 4 dispositivos)
- [x] Ejemplos reales en `examples/` (google, youtube, github, custom, batch + urls.csv)
- [x] CLI: `youber-audit` y `youber-sandbox` ([project.scripts]) + `youber/console.py` (UTF-8 Windows)
- [x] Tests: `test_accessibility.py`, `test_sandbox.py`, `test_examples.py` → **39 passed**
- [x] Docs: `ACCESSIBILITY.md`, `SANDBOX.md`, `EXAMPLES.md`
- [x] Integración: auditoría real de google.com (1 violación serious) + demo sandbox (JP/iPhone/3g) + CLI

## Fase 3: Servidor MCP (`youber/mcp`) — ✅ Completada

- [x] Estructura `mcp/` (server, tools, models)
- [x] Herramientas: `open_page`, `navigate_to`, `get_page_info`
- [x] `audit_accessibility` con axe-core (vendored en `src/youber/assets/axe.min.js`)
- [x] Sesiones de navegador persistentes (page_id entre llamadas)
- [x] `tests/test_mcp_server.py` (6 tests)
- [x] `docs/MCP_SERVER.md`
- [x] Verificación: `pytest` → **16 passed**

## Fase 2: Núcleo Playwright (`youber/core`) — ✅ Completada

- [x] `BrowserManager` (launch, new_context, new_page, navigate, get_title, close)
- [x] Excepciones propias (`TimeoutException`, `NavigationException`, `BrowserException`)
- [x] Logging con loguru (decorador `@log_action` + `capture_logs`)
- [x] Fixture `sample_navigation()` (título + logs)
- [x] Tests `tests/test_browser.py` (launch, navegación, título)
- [x] Verificación: `playwright install chromium` + `pytest` → **10 passed**

## Fase 1: Configuración del entorno — ✅ Completada

- [x] Estructura de directorios (`src/youber`, `tests`, `examples`, `config`, `docs`)
- [x] `requirements.txt`, `.env.example`, `README.md`, `config/settings.py` (→ movido a `src/youber/settings.py` en Fase 4)
- [x] Paquete `youber` (v0.1.0) y tests de configuración (3 passed)
