# Guía de investigación anti-bot — BARF

Guía práctica para montar experimentos **observacionales** de detección con
BARF, en laboratorio y sin evasión. Complementa el documento teórico
[ANTI_BOT_RESEARCH.md](ANTI_BOT_RESEARCH.md).

## Reglas del laboratorio

1. Solo propiedades propias o de prueba (localhost, fixtures, example.com).
2. Volúmenes bajos y uso razonable: nada de medir a escala.
3. Observar y documentar, nunca ocultar actividad ni saltarse bloqueos.
4. Si un sitio bloquea, **se respeta el bloqueo** y se anota el resultado.

## Experimento 1: qué señales expone tu navegador automatizado

```bash
python examples/research_demo.py
python examples/research_demo.py --json
```

Observa en la salida `webdriver: True` (Playwright marca el flag por diseño):
es la demostración perfecta de que la automatización *se puede detectar* y de
que BARF no pretende ocultarlo.

## Experimento 2: comparativa headless vs headed

El mismo script con `BrowserManager(headless=False)` (o `--headed`) muestra
qué señales cambian (plugins, canvas, resolución). Documenta las diferencias
en tu cuaderno de laboratorio.

## Experimento 3: variación de entorno con el sandbox

```bash
youber-sandbox --url https://example.com --device iPhone --region JP
youber-sandbox --url https://example.com --device Desktop
```

Compara `navigator_language`, `timezone`, viewport y `touch` entre
configuraciones. El sandbox sirve para estudiar *localización y diseño*,
no para hacerse pasar por otro usuario.

## Experimento 4: respuesta de un sitio propio

Si tienes un servidor de pruebas con un WAF (p. ej. un challenge de
Cloudflare en modo test o `fail2ban`):

1. Haz `N` peticiones rápidas con `open_page` y registra los códigos.
2. Repite con pausas largas (`dwell_ms` alto).
3. Compara: ¿cuándo aparece el challenge? ¿qué header/estado devuelve?

Esto enseña rate limiting y challenges sin violar nada (es tu servidor).

## Qué medir y cómo anotarlo

Por experimento:

- Fecha, URL, entorno (headless, dispositivo, región, red).
- Señales observadas (salida de `research_demo.py`).
- Respuesta del sitio (status, headers, challenge, bloqueo).
- Conclusión educativa (qué señal lo delata, qué mejora en detección).

## Cómo NO usar esto

- No para saltarte CAPTCHAs, WAFs o bloqueos de sitios ajenos.
- No para scraping a escala ni para ocultar identidad.
- No para manipular métricas ni engagement.
- El `playwright-stealth` se menciona en el proyecto solo como objeto de
  estudio (qué señales parchea), nunca como herramienta de producción.
