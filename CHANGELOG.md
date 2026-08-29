# Changelog

Todos los cambios relevantes del proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y el
proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [0.1.0] - 2026-08-29

Primera publicación (Alpha).

### Added

- **Núcleo Playwright** (`youber/core`): `BrowserManager` con contextos
  aislados, excepciones propias, logging con loguru y fixture de ejemplo.
- **Servidor MCP** (`youber/mcp`): MCPServer (MCP SDK 2.x) con herramientas
  `open_page`, `navigate_to`, `get_page_info`, `audit_accessibility`,
  `simulate_geolocation`, `simulate_network` y `simulate_device`; sesiones de
  navegador persistentes.
- **Cliente MCP** (`youber/client`): `create_mcp_session` (stdio/SSE/
  streamable-http con reintentos), `MCPTools` y CLI interactiva
  `youber-client` (rich).
- **Accesibilidad** (`youber/accessibility`): `AxeRunner` con caché y
  opciones, mapeo de 70+ reglas a WCAG 2.1/2.2, reportes Markdown/JSON/resumen
  y recomendaciones con recursos educativos. axe-core vendored (offline).
- **UX** (`youber/ux`): detección de patrones de navegación, heatmaps de
  scroll/clics, trazado de user journeys con puntos de abandono y reportes.
- **Sandbox** (`youber/sandbox`): simulaciones de geolocalización (10
  regiones), red (5 perfiles vía CDP) y dispositivos (iPhone/Pixel/iPad/Desktop).
- **CLI**: `youber-audit` (auditoría rápida) y `youber-sandbox` (demo de
  simulaciones).
- **Ejemplos** en `examples/`: auditorías de google/youtube/github, auditoría
  personalizada, batch por CSV y demo observacional anti-bot.
- **Documentación**: ACCESSIBILITY, MCP_SERVER, CLIENT, SANDBOX, EXAMPLES,
  ANTI_BOT_RESEARCH, RESEARCH y PUBLISHING.
- **CI/CD**: GitHub Actions (Python 3.11/3.12, ruff, mypy, pytest con
  cobertura), configuración ruff/mypy y pre-commit hooks.

### Fixed

- Empaquetado: `config/` movido dentro del paquete (`youber/settings.py`).
- Compatibilidad Windows: consola UTF-8 para emojis y slugs saneados.
- Tests e2e: gestión de sesión MCP dentro del test (compatibilidad
  pytest-asyncio + anyio) y aislamiento de variables de entorno.
