# BARF — Browser Automation Research Framework

> Framework **educativo** de automatización de navegadores para investigación, accesibilidad y estudio de UX.
> El nombre es horrible a propósito. El código, no. ⚙️

## Descripción

BARF es un framework educativo de automatización de navegadores construido
sobre **Playwright**, con:

- **Servidor MCP** (Model Context Protocol, SDK 2.x) para agentes de IA
- **Auditoría de accesibilidad** (axe-core + mapeo WCAG 2.1/2.2 + reportes)
- **Estudio de UX** (patrones de navegación, heatmaps, user journeys)
- **Investigación de YouTube** (datos públicos de canales/vídeos, patrones y exportación)
- **Edición de audio** (música de fondo propia, efectos, sincronización con FFmpeg)
- **Catálogo de música** (biblioteca local, moods, búsqueda y sugerencias)
- **Edición de vídeo** (proyectos multi-clip, transiciones, overlays, render con FFmpeg)
- **Subida a YouTube** (contenido propio, OAuth 2.0, publicación programada)
- **Sandbox de simulaciones** (geolocalización, red, dispositivos)
- **CLI**: `youber-audit`, `youber-sandbox`, `youber-client` (interactiva), `youber-research`, `youber-workflow`, `youber-music`, `youber-edit` y `youber-upload`

## Propósito educativo

- Enseñar cómo funcionan Playwright, MCP y los sistemas anti-bot
- Auditar accesibilidad web de forma reproducible (WCAG)
- Estudiar cómo los usuarios interactúan con las interfaces
- Aprender a integrar navegadores con agentes de IA vía MCP

## Restricciones (no negociables)

- ❌ No manipular métricas (visualizaciones, likes, suscriptores, watch time)
- ❌ No evadir sistemas de seguridad ni anti-bot en entornos reales
- ❌ No spam, scraping abusivo ni contenido malicioso
- ✅ Código open source y con fines educativos
- ✅ Respetar robots.txt y términos de servicio
- ✅ Solo se prueban propiedades propias o con permiso explícito

## Instalación

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## Ejemplos rápidos

Auditoría de accesibilidad:

```bash
youber-audit https://example.com
```

CLI interactiva (cliente MCP):

```bash
youber-client
> audit https://example.com
> geo JP https://example.com
```

Investigación de YouTube (datos públicos):

```bash
youber-research https://www.youtube.com/@python -n 20 -o python_channel.csv
youber-research https://youtu.be/abc123 -o video_info.json
youber-research https://www.youtube.com/@python --insights -o reporte.md
```

Flujo completo (investigación + edición de audio):

```bash
youber-workflow --channel @python -n 10 -o reports
youber-workflow --demo -o reports   # sin red: canal sintético + medios generados
```

Desde código:

```python
import asyncio
from youber.accessibility.axe_runner import AxeRunner
from youber.core.browser import BrowserManager

async def main():
    manager = BrowserManager(headless=True)
    await manager.launch()
    context = await manager.new_context()
    page = await manager.new_page(context)
    await manager.navigate(page, "https://example.com")
    results = await AxeRunner().run_axe(page)
    print(f"Violaciones: {results.total_violations}")
    await manager.close()

asyncio.run(main())
```

## Documentación

- [Accesibilidad](docs/ACCESSIBILITY.md) — auditoría WCAG con axe-core
- [Servidor MCP](docs/MCP_SERVER.md) — herramientas del servidor
- [Cliente MCP](docs/CLIENT.md) — conexión al servidor desde código/terminal
- [Sandbox](docs/SANDBOX.md) — simulaciones de entorno
- [Investigación anti-bot](docs/ANTI_BOT_RESEARCH.md) — estudio educativo
- [Investigación de YouTube](docs/YOUTUBE_RESEARCH.md) — datos públicos y patrones
- [Edición de audio](docs/AUDIO.md) — música de fondo, efectos y sincronización
- [Flujo completo](docs/WORKFLOW.md) — investigación de YouTube + edición de audio
- [Catálogo de música](docs/MUSIC.md) — biblioteca local, moods y sugerencias
- [Edición de vídeo](docs/VIDEO_EDITOR.md) — proyectos, transiciones y overlays
- [Subida a YouTube](docs/UPLOAD.md) — OAuth 2.0 y publicación programada
- [Guía de laboratorio](docs/RESEARCH.md) — experimentos observacionales
- [Ejemplos](docs/EXAMPLES.md) — guía de los ejemplos
- [Publicación en PyPI](docs/PUBLISHING.md) — cómo publicar el paquete

## Calidad

- CI: GitHub Actions (Python 3.11/3.12) — lint, type-check, tests, coverage
- `ruff check src/ tests/ examples/`
- `mypy src/`
- `pytest tests/ -v --cov=youber`

## Contribución

1. Haz un fork del repositorio.
2. Crea una rama (`git checkout -b feature/nueva-funcionalidad`).
3. Asegúrate de que pasan `ruff`, `mypy` y `pytest`.
4. Abre un pull request.

Proyecto educativo: aporta ejemplos, documentación, tests o nuevas
herramientas de estudio.

## Licencia

MIT — ver [LICENSE](LICENSE).
