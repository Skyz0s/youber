# Ejemplos — BARF

Guía de los ejemplos incluidos en `examples/`. Todos generan reportes
Markdown en `reports/` (directorio ignorado por git) y muestran un resumen en
consola.

## Requisitos

```bash
pip install -r requirements.txt
playwright install chromium
```

## Auditorías individuales

Auditan la página principal de un sitio conocido y guardan el reporte.

```bash
python examples/audit_google.py                  # https://www.google.com
python examples/audit_youtube.py                 # https://www.youtube.com
python examples/audit_github.py                  # https://github.com
```

Opciones comunes: `--url URL` (otro destino), `--output-dir DIR` (dónde
guardar), `--headed` (mostrar el navegador).

Cada script expone una función `audit(url, output_dir, headless)` reutilizable
desde código o tests.

## Auditoría personalizada

```bash
python examples/custom_audit.py --url https://example.com \
    --rules color-contrast label \
    --impact serious
```

Solo ejecuta las reglas indicadas, filtra por impacto y muestra
**recomendaciones automáticas** con enlaces a recursos educativos. Genera
reporte **Markdown + JSON**.

## Auditoría por lotes (CSV)

```bash
python examples/batch_audit.py --csv examples/urls.csv
```

El CSV debe tener cabecera `url` y, opcionalmente, `name`:

```csv
url,name
https://example.com,Example
https://example.org,Example Org
```

Genera un reporte por sitio (`reports/<name>.md`) y un resumen
(`reports/summary.md`) con el total de violaciones por sitio. Las URLs se
auditan de forma secuencial y con volumen bajo.

## Salida

Los reportes se guardan en `reports/`:

- `audit-google-com-20260829-103000.md` — reporte de una auditoría individual
- `audit-custom-<host>-<ts>.md` / `.json` — auditoría personalizada
- `<name>.md` + `summary.md` — auditoría por lotes

Cada reporte contiene: fecha, totales, tabla de violaciones (ID, impacto,
descripción, elementos afectados, enlace WCAG) y checks superados. Ver
[ACCESSIBILITY.md](ACCESSIBILITY.md) para saber cómo interpretarlo.

## Prueba de funcionamiento de todo el proceso (end-to-end)

Valida la cadena completa sobre datos sintéticos, **sin red**: catálogo de
música + letras → workflow `--lyrics-video` (canción elegida por la letra,
prompt, render con FFmpeg) → decisión en el journal → subida + métricas →
importación del CSV de YouTube Studio → dataset features→resultados → informe
de correlaciones → recordatorio de métricas.

```bash
python examples/e2e_pipeline.py                            # escribe en ./e2e-run
python examples/e2e_pipeline.py --workdir C:/tmp/e2e --duration 6
```

Imprime una tabla con el estado de cada una de las 8 etapas (✅/❌) y sale con
código 0 solo si todas pasan. Los artefactos (vídeo final, CSV, informe,
journal) quedan en el directorio de trabajo para inspeccionarlos.

En la suite es `tests/test_e2e_pipeline.py` (se salta si no hay FFmpeg), así que
`pytest tests/test_e2e_pipeline.py` ejecuta el mismo proceso.

## Integración con tests

Los ejemplos se prueban en `tests/test_examples.py` usando una página local
(`tests/fixtures/accessible.html`) para que la validación no dependa de la red
ni de terceros.
