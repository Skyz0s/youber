# Dashboard de métricas (`youber.dashboard`)

Sistema de widgets visuales con métricas clave del ecosistema Youber:
catálogo de música, uso, proyectos recientes, subidas a YouTube, tareas
programadas y actividad diaria. Renderizado en **Markdown**, **HTML** o
**JSON**.

## Estructura

| Módulo | Responsabilidad |
|---|---|
| `models.py` | `WidgetType`, `Widget`, `WidgetData` (pydantic v2) |
| `data_sources.py` | Conexión a las fuentes: música (SQLite), scheduler (JSON), reportes, subidas |
| `metrics.py` | Cálculo de métricas (funciones puras, offline-testables) |
| `registry.py` | Registro de widgets: tipo → métrica + título + fuentes |
| `widgets.py` | `WidgetManager`: crea widgets y recolecta sus datos |
| `renderer.py` | Renderizado HTML / Markdown / JSON |
| `cli.py` | Comando `youber-dashboard` |

## Tipos de widget (`WidgetType`)

`channel-trends`, `music-usage`, `recent-projects`, `upload-status`,
`engagement-metrics`, `scheduled-tasks`, `channel-comparison`,
`daily-activity`, `top-videos`, `catalog-stats`.

## CLI

```bash
youber-dashboard list                                # widgets disponibles
youber-dashboard render catalog-stats                # un widget (Markdown)
youber-dashboard render music-usage -f json          # un widget en JSON
youber-dashboard dashboard --format html -o dash.html  # dashboard completo
youber-dashboard dashboard -f md                       # Markdown por consola
youber-dashboard dashboard --widgets catalog-stats,scheduled-tasks,upload-status -f html -o custom.html  # selección
youber-dashboard serve                                # dashboard en el navegador (puerto 8765)
youber-dashboard serve --port 9000 --refresh 30       # otro puerto y refresco cada 30 s
```

## Trabajar en el dashboard (modo servidor)

Para **ver y manejar el dashboard directamente en el navegador** (sin
comandos por cada cambio):

```bash
youber-dashboard serve
```

Abre `http://127.0.0.1:8787` (puerto configurable con `--port` o en la
configuración). La página:

- Muestra los widgets seleccionados con **auto-refresco** (por defecto
  cada 60 s; cambia con `--refresh`).
- Permite **marcar/desmarcar widgets con checkboxes** y guardar la
  selección; queda persistida en `~/.youber/dashboard.json`.
- Incluye un **buscador de música en plataformas** (Apple/iTunes o
  Spotify): escribe un texto, marca los resultados que te interesen y
  pulsa «Importar seleccionadas» para añadirlos al catálogo **sin salir
  del navegador** (solo metadatos públicos, nunca audio).
- Expone `GET /api/data` (JSON de los widgets), `GET /api/search-cloud`
  (buscar en plataforma) y `POST /api/import-cloud` (importar al
  catálogo) para integrarse con otras herramientas.

El buscador importa al mismo catálogo que muestra el widget
`catalog-stats` (`<music-dir>/.music.db`); al terminar, los widgets se
refrescan solos. El directorio de música se elige con `--music-dir`.

Configuración guardada (`~/.youber/dashboard.json`):

```json
{
  "widgets": ["catalog-stats", "scheduled-tasks", "upload-status"],
  "refresh_seconds": 60,
  "port": 8787
}
```

El servidor escucha solo en `127.0.0.1` (no expone datos fuera de la
máquina) y usa únicamente la librería estándar.

## Dashboard personalizado

Puedes construir un dashboard con una **selección concreta de widgets** de
dos formas: desde la CLI con `--widgets` (lista separada por comas) o desde
código con `WidgetManager.create_widget()` / `WidgetManager.collect_types()`.

```python
from youber.dashboard import WidgetManager
from youber.dashboard.renderer import render_dashboard_html

manager = WidgetManager()
data = manager.collect_types(["catalog-stats", "scheduled-tasks", "upload-status"])
html = render_dashboard_html(data)
Path("custom_dashboard.html").write_text(html, encoding="utf-8")
```

El orden en el HTML respeta la posición de cada widget (los creados juntos
siguen el orden de la lista), no el id aleatorio. Ejemplo completo:
`examples/custom_dashboard.py`.

## Uso desde código

```python
from youber.dashboard import WidgetManager, create_widget, WidgetType
from youber.dashboard.renderer import render_dashboard_markdown

manager = WidgetManager()  # carga fuentes por defecto (música, scheduler, reportes)
widget = create_widget(WidgetType.CATALOG_STATS)
data = manager.collect(widget)
print(render_dashboard_markdown([data]))
```

O con fuentes inyectadas (para tests o fuentes personalizadas):

```python
manager = WidgetManager(sources={"tracks": [...], "reports": [...], ...})
```

O crear y recolectar en un solo paso:

```python
manager = WidgetManager()
data = manager.collect_types(["catalog-stats", "upload-status", "scheduled-tasks"])
```

## Modelos

- **`Widget`**: `id`, `type`, `title`, `params`, `position`,
  `refresh_interval` (s), `enabled`, `created_at`, `updated_at`.
- **`WidgetData`**: `widget_id`, `type`, `title`, `data` (dict de métricas),
  `position` (ordena en el dashboard), `rendered_at`.

## Cómo funcionan las métricas

Las funciones de `metrics.py` son **puras**: reciben datos tipados (lista de
pistas, trabajos, reportes, vídeos) y devuelven dicts. El registro
(`registry.py`) asocia cada tipo de widget con su métrica y con los nombres
de las fuentes que necesita; `WidgetManager.collect()` carga esas fuentes y
las pasa como argumentos.

## Ética

Métricas descriptivas de la propia actividad del usuario. Sin manipular
métricas ajenas ni inflar nada: el dashboard muestra el estado real del
ecosistema local.
