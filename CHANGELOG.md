# Changelog

Todos los cambios relevantes del proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y el
proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added

- **Registro de decisiones** (`youber/journal`, CLI `youber-journal`): cada
  vídeo generado deja una huella auditable — patrón detectado en los metadatos,
  atributos extraídos, canción elegida con su motivo, puntuación y ranking de
  candidatas, prompt/guion, vídeo renderizado y, después, las métricas del canal
  (impresiones, CTR, retención, vistas, suscripciones...).
  - `youber.journal`: `DecisionJournal` (SQLite en `~/.youber/journal.db`),
    modelos pydantic y almacén con métricas por ventana.
  - **Dataset + análisis**: `dataset` (features → resultados) y `analyze`
    (correlaciones de Pearson por feature y medias por grupo) para estudiar qué
    características del matching predicen un vídeo que funciona.
  - **Importación**: `youber-journal import <csv>` cruza un export de YouTube
    Studio (modo avanzado) con las decisiones por id de vídeo o título.
  - Integrado en `youber-workflow` (clásico y `--lyrics-video`) con
    `--journal-db` / `--no-journal`; docs en `docs/DECISION_JOURNAL.md`.
- `youber.music.selector`: `score_breakdown` (desglose auditable del scoring
  por señal: tema, sentimiento, mood, keywords, favorita y uso previo).
- **La duración del vídeo sigue a la canción**: en `--lyrics-video`, si no
  indicas `--duration`, el vídeo dura lo que la canción elegida (sin
  desajustes de audio); `--duration N` sigue teniendo prioridad y, sin
  catálogo, se usa la media del canal. El journal guarda la duración de la
  canción (`track_duration`) como feature para el análisis.

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
