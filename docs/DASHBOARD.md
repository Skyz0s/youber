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
```

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

## Modelos

- **`Widget`**: `id`, `type`, `title`, `params`, `position`,
  `refresh_interval` (s), `enabled`, `created_at`, `updated_at`.
- **`WidgetData`**: `widget_id`, `type`, `title`, `data` (dict de métricas),
  `rendered_at`.

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
