# Arquitectura Técnica — BARF

## Visión general

BARF se organiza en capas con una separación clara: la capa de automatización no sabe nada de política; la capa de política (guardrails) envuelve todo el tráfico.

```
┌─────────────────────────────────────────────────┐
│ Capa MCP (servidor)                             │
│  tools: audit_accessibility, study_navigation,  │
│         test_page, network_probe, learn_playwright
├─────────────────────────────────────────────────┤
│ Capa de investigación (módulos temáticos)       │
│  accessibility · ux · education · devtools · net │
├─────────────────────────────────────────────────┤
│ Capa de automatización (Playwright)             │
│  launch, contextos aislados, fixtures, helpers   │
├─────────────────────────────────────────────────┤
│ Capa de política (guardrails)                   │
│  rate limit · allowlist · sandbox · auditoría    │
└─────────────────────────────────────────────────┘
```

## Módulos propuestos

| Módulo | Responsabilidad | Tecnología |
|---|---|---|
| `barf/core` | Launch de navegadores, contextos aislados, fixtures, utilidades | Playwright sync/async |
| `barf/accessibility` | Auditoría: ARIA, contraste, foco, teclado, subtítulos | Playwright + axe-core (opcional) |
| `barf/ux` | Simulación de patrones de navegación, throttling de red, métricas de interacción | Playwright (`context.set_offline`, CDP) |
| `barf/network` | Sondeos de geolocalización/latencia en sandbox | Playwright + aiohttp |
| `barf/education` | Ejemplos comentados, materiales de taller, demos anti-bot en laboratorio | — |
| `barf/mcp` | Servidor MCP que expone las herramientas anteriores | `mcp` (Python SDK) |
| `barf/policy` | Rate limiting, allowlists, modo sandbox, log de auditoría | asyncio, sqlite/logging |

## Decisiones clave

1. **Python 3.11+** y el **SDK oficial de MCP** para el servidor; el núcleo usa Playwright para Python.
2. **Contextos aislados por tarea**: cada tarea lanza un contexto limpio (perfil temporal, sin cookies compartidas) — bueno para testing y para no contaminar datos.
3. **Guardrails en el núcleo, no en la periferia**: toda navegación pasa por `barf/policy` (límites por dominio, allowlist configurable, modo sandbox obligatorio para sondeos de red).
4. **Anti-bot solo en laboratorio**: `playwright-stealth` se documenta y se usa únicamente en un escenario local/aislado para estudiar detección; el código de producción no lo incluye.
5. **Auditoría**: cada acción automatizada se registra (qué, quién, cuándo, por qué, volumen) para mantener el proyecto transparente y reproducible.

## Política de seguridad (guardrails)

- **Sandbox por defecto**: sondeos de red/proxies corren en entorno aislado, sin cuentas reales.
- **Rate limiting**: límites de peticiones por dominio; se respeta robots.txt y uso razonable.
- **Allowlist**: solo dominios/propiedades autorizadas (propias o con permiso).
- **Sin acciones de engagement**: el framework nunca realiza likes, suscripciones, comentarios ni reproducciones sobre contenido de terceros.
- **Auditoría completa**: log persistente de toda actividad automatizada.

## Roadmap técnico

1. Estructura del repo + `pyproject.toml` + entorno (venv, `pip install -e .[dev]`)
2. `barf/core`: launch, contextos, fixture de ejemplo (abrir YouTube y volcar título)
3. `barf/mcp`: servidor con 2-3 herramientas (p. ej. `open_page`, `audit_accessibility`, `study_navigation`)
4. Módulo de accesibilidad con axe-core
5. Módulo de redes en sandbox
6. Docs finales + ejemplos de taller
