# Changelog

Todos los cambios relevantes del proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y el
proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added

- **Bucle de aprendizaje del journal** (`youber-journal learn` / `weights`): las
  métricas reales del canal ya no se quedan en un informe — **ajustan los pesos
  del selector de canciones**.
  - `youber.music.weights`: `SelectionWeights` encapsula los pesos del scoring
    (con sus valores por defecto como *prior*), los guarda en JSON
    (`YOUBER_WEIGHTS` o `~/.youber/selection_weights.json`) y explica su
    procedencia (`source_label()`).
  - `youber.journal.learn`: `learn_weights()` correlaciona cada señal
    (`theme_score`, `sentiment_match`, `mood_match`, `keyword_hits`,
    `favorite`, `usage_count`) con la métrica elegida y reescala el peso base
    por `1 + dirección · fuerza · r · n/(n+min_samples)` (encogimiento hacia el
    prior con pocos datos), acotado a `[0.25, 4.0]`. En las señales de castigo
    la dirección se invierte: reusar canciones que rinden peor **sube** el
    castigo.
  - `youber.music.selector` acepta `weights=` en `score_breakdown`,
    `score_track_for_profile`, `select_tracks` y `select_best_track`; el flujo
    `youber-workflow --lyrics-video` los carga solos (``--no-weights`` fuerza el
    prior) y muestra su procedencia.
  - **Sin datos suficientes** (5 vídeos medidos por defecto) devuelve los pesos
    por defecto: el comportamiento no cambia hasta que haya evidencia real.
  - `youber-journal learn [--metric ctr] [--min-samples N] [--report FILE]` y
    `youber-journal weights [--clear]`.
  - 21 tests nuevos en `tests/test_weights.py`; `tests/conftest.py` aísla
    `YOUBER_WEIGHTS` por test; docs en `docs/DECISION_JOURNAL.md` y
    `docs/MUSIC.md`.

- **Publicación completa** (`youber.upload`): el flujo ya no termina en
  «subir el vídeo» — sube también la **miniatura** (`thumbnails.set`) y las
  **pistas de subtítulos** (`captions.insert`), y añade **capítulos** a la
  descripción.
  - `youber.upload.thumbnail`: elige el fotograma del instante con más energía
    del audio (el estribillo; descarta los fundidos), lo recorta a 16:9
    (1280×720) y puede rotular el título con el mismo lenguaje visual de los
    subtítulos (blanco con contorno). Resuelve la fuente del sistema en
    Windows (FFmpeg no usa fontconfig ahí).
  - `youber.upload.captions`: cuerpo `multipart/related` de `captions.insert`
    (snippet JSON + `.srt`) sin dependencias extra.
  - `youber.upload.chapters`: `build_chapters()` valida los requisitos de
    YouTube (3+ capítulos, 10 s mínimo, el primero en `00:00`) y omite el
    bloque si no se cumplen; `chapters_from_script()` los saca del guion.
  - `youber-upload thumbnail <video_id> --video|--image [--text] [--time]` y
    `youber-upload captions <video_id> <srt> [--language] [--name] [--draft]
    [--list] [--delete <id>]`.
  - `youber-workflow --lyrics-video --upload` con `--thumbnail/--no-thumbnail`
    (sí por defecto), `--captions` y `--chapters`; el `.srt` alineado se
    guarda como artefacto (`sync_video_with_track(..., srt_out=...)`) aunque no
    se suba.
  - **Scopes**: la app pide ahora `youtube` **y** `youtube.force-ssl`;
    `captions.insert` no acepta el scope de solo subida. Si el token guardado
    es anterior, la subida de la pista avisa de que hay que rehacer
    `youber-upload auth`.
  - 28 tests nuevos en `tests/test_upload_publish.py`; docs en
    `docs/UPLOAD.md`.

- **Estilo visual automático** (`youber.visuals.selector`): el estilo de los
  planos ya no es fijo — se deduce del **audio** (energía, valencia, tempo,
  baile, acústica, modo del `AudioProfile`; o la sonoridad medida con FFmpeg si
  no hay perfil) y de los **metadatos de YouTube** (temas/sentimiento y
  palabras clave del título, descripción y etiquetas).
  - `build_signals` (mezcla ponderada de fuentes), `score_styles` /
    `choose_style` (puntuación lineal + bonus por palabras clave y desempate
    determinista por `variation_key`), `transition_for` (tempo → fundidos),
    `seconds_per_shot_for` (energía → planos) y `motion_offset_for` (variedad
    del ciclo Ken Burns).
  - `--style auto` / `--ai-style auto` pasan a ser el **valor por defecto**
    (antes `cinematic`); forzar un estilo sigue disponible.
  - El plan guarda `style_reason`, `style_scores`, `style_signals`, `seed`,
    `motion_offset` y `seconds_per_shot`: cualquier render se puede repetir.
  - 26 tests nuevos en `tests/test_visuals_selector.py`; docs en
    `docs/VISUALS.md`.

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
  canción (`track_duration`) como feature para el análisis. Las transiciones
  solapadas se compensan para que el vídeo final dure exactamente lo mismo
  que la canción.

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
