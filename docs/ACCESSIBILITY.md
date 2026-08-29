# Accesibilidad — BARF

Guía del módulo de auditoría de accesibilidad: cómo ejecutarla, cómo leer los
reportes y cómo usar el mapeo WCAG y las recomendaciones automáticas.

## ¿Qué es WCAG?

Las **Web Content Accessibility Guidelines (WCAG)** son el estándar W3C para
accesibilidad web. Se organizan en 4 principios:

1. **Perceptible** (1.x) — la información debe poder percibirse (alternativas
   de texto, contraste, subtítulos...).
2. **Operable** (2.x) — la interfaz debe poder usarse (teclado, tiempo,
   navegación, objetivos táctiles...).
3. **Comprensible** (3.x) — la información y el funcionamiento deben ser
   comprensibles (idioma, etiquetas, ayuda...).
4. **Robusto** (4.x) — el contenido debe funcionar con tecnologías de apoyo
   (ARIA, nombres accesibles, ids únicos...).

Cada criterio tiene un nivel de conformidad: **A** (mínimo), **AA**
(recomendado) y **AAA** (avanzado).

## Cómo auditar

### Con la CLI (`youber-audit`)

```bash
youber-audit https://www.google.com
youber-audit https://example.com --rules color-contrast label --impact serious
```

Guarda el reporte Markdown en `reports/` y muestra el resumen en consola.

### Con los ejemplos

```bash
python examples/audit_google.py
python examples/custom_audit.py --url https://example.com --rules color-contrast
python examples/batch_audit.py --csv examples/urls.csv
```

### Con código

```python
import asyncio
from youber.accessibility.axe_runner import AxeRunner
from youber.accessibility.reporters import generate_json_report, generate_summary
from youber.core.browser import BrowserManager

async def main():
    manager = BrowserManager(headless=True)
    await manager.launch()
    context = await manager.new_context()
    page = await manager.new_page(context)
    await manager.navigate(page, "https://example.com")

    runner = AxeRunner()
    results = await runner.run_axe(page, {"impactLevels": ["critical", "serious"]})
    print(generate_summary(results))
    data = generate_json_report(results)   # integrable con otras herramientas

    await manager.close()

asyncio.run(main())
```

### Desde MCP

El servidor MCP expone `audit_accessibility(page_id)` (ver
[MCP_SERVER.md](MCP_SERVER.md)); la implementación delega en `AxeRunner`.

## Opciones de `run_axe`

| Opción | Descripción | Ejemplo |
|---|---|---|
| `context` | Selector CSS o definición de contexto | `"#main"`, `{"include": [["#main"]]}` |
| `rules` | Solo estas reglas | `["color-contrast", "label"]` |
| `tags` | Solo reglas con estos tags | `["wcag2a", "wcag2aa"]` |
| `impactLevels` | Filtrar por impacto | `["critical", "serious"]` |

## Cómo leer el reporte Markdown

Cada violación incluye: **ID** de la regla, **impacto** (🔴 critical, 🟠
serious, 🟡 moderate, 🔵 minor), **descripción**, **elementos afectados**
(selectores) y **enlace a la quickref WCAG** del criterio correspondiente.

## Reglas comunes y su criterio WCAG

| Regla axe | WCAG | Qué comprueba |
|---|---|---|
| `color-contrast` | 1.4.3 (AA) | Contraste texto/fondo ≥ 4.5:1 |
| `image-alt` | 1.1.1 (A) | Texto alternativo en imágenes |
| `html-has-lang` | 3.1.1 (A) | Atributo `lang` en `<html>` |
| `document-title` | 2.4.2 (A) | Título descriptivo de la página |
| `link-name` | 2.4.4 (A) | Nombre accesible en enlaces |
| `label` | 1.3.1 (A) | Etiquetas en campos de formulario |
| `region` | 1.3.1 (A) | Contenido agrupado en landmarks |
| `heading-order` | 1.3.1 (A) | Encabezados sin saltos de nivel |
| `frame-title` | 2.4.1 (A) | Título en `<iframe>` |
| `target-size` | 2.5.8 (AA, WCAG 2.2) | Objetivos táctiles ≥ 24x24 px |

El mapeo completo está en `src/youber/accessibility/wcag.py` (más de 70
reglas). Nota: el mapeo es orientativo; una regla de axe puede cubrir varios
criterios.

## Recomendaciones y aprendizaje

- `get_fix_suggestion(rule_id, element)` — sugerencia concreta de corrección.
- `get_learning_resource(rule_id)` — recurso educativo (MDN, WebAIM, W3C).

```python
from youber.accessibility.recommendations import get_fix_suggestion, get_learning_resource

print(get_fix_suggestion("color-contrast", "#boton"))
# Aumenta el contraste entre texto y fondo hasta al menos 4.5:1...
print(get_learning_resource("color-contrast"))
# https://webaim.org/articles/contrast/
```

## Limitaciones

- axe-core detecta **automáticamente comprobables**; hay criterios WCAG que
  requieren revisión manual (los resultados `incomplete`).
- Una auditoría automática no equivale a una evaluación de conformidad
  completa (para eso se necesita una auditoría humana experta).
