# Investigación anti-bot — BARF

> Documento **educativo**. Estudiar cómo funcionan los sistemas anti-bot sirve
> para entender la web, defender la privacidad y construir tests honestos.
> BARF **no** proporciona mecanismos de evasión: la investigación se hace
> siempre en laboratorio, observando señales, sin saltarse ninguna protección.

## Introducción: ¿qué son los sistemas anti-bot?

Los sistemas anti-bot protegen servicios web de tráfico automatizado
indeseado: scraping masivo, fraude, spam, creación de cuentas falsas o
manipulación de métricas. Para distinguir humanos de programas analizan
múltiples señales del cliente (navegador) y del tráfico (red), y deciden si
bloquean, ralentizan o desafían la petición.

Entender estas señales es relevante para:

- **Desarrolladores**: saber qué expone su propio navegador al automatizar
  tests (y por qué algunos tests se comportan distinto en CI).
- **Investigadores de privacidad**: cuantificar la información que un sitio
  puede recolectar sin permiso.
- **Educadores**: enseñar cómo funciona la detección y por qué los
  anti-cheats y anti-fraude existen.

## Técnicas comunes

### 1. Reputación de IP y bloqueo

- Listas negras de IPs de centros de datos y proveedores cloud.
- Rate limiting por IP/UA/cuenta.
- Análisis de geolocalización de la IP frente a la zona horaria del cliente.
- El tráfico residencial es más difícil de distinguir; por eso algunos usan
  proxies residenciales — **técnica que BARF no emplea para evadir**.

### 2. Browser fingerprinting

El navegador expone decenas de señales que, combinadas, forman una huella
casi única:

- `user-agent`, `platform`, `language(s)`
- Resolución de pantalla, colorDepth, `deviceMemory`, `hardwareConcurrency`
- Zona horaria (`Intl`), fuentes instaladas, plugins
- Render de **canvas** (huella gráfica muy estable) y WebGL
- APIs como `navigator.webdriver` (marcada por WebDriver/Playwright)

### 3. Comportamiento humano vs automatizado

- Velocidad y trayectoria del ratón (curvas, aceleración).
- Patrones de scroll y tiempos entre acciones (dwell, lectura).
- Orden de foco y eventos de teclado (keystroke dynamics).
- Coherencia temporal: un "humano" que actúa 24/7 o a velocidad constante
  es sospechoso.

### 4. CAPTCHA y desafíos

- Desafíos cognitivos (texto, imágenes) o invisibles (honeypots, pruebas de
  comportamiento).
- Los retos modernos evalúan el historial de la sesión y el contexto del
  navegador, no solo la respuesta.

## Cómo se estudian en laboratorio

Con BARF (entorno controlado, sin evasión):

1. **Observación de señales** — `examples/research_demo.py` recopila las
   señales que un sitio puede ver (UA, webdriver, canvas hash, timezone...)
   y explica para qué se usan.
2. **Métricas de detección** — en un sitio propio o de prueba, mide:
   - ¿Cambia la respuesta según el user agent?
   - ¿Qué peticiones bloquea un WAF con reglas conocidas?
   - ¿Qué señales expone un navegador automatizado frente a uno normal?
3. **Análisis de señales** — compara navegador headless vs headed, con/sin
   permisos, distintos dispositivos (`youber-sandbox`), y documenta qué
   cambia.

```bash
python examples/research_demo.py --url https://example.com
youber-sandbox --url https://example.com --device iPhone --region JP
```

## Limitaciones y ética

- **Uso educativo**: el conocimiento aquí descrito es para entender y
  defender, no para saltarse protecciones en entornos reales.
- **No evasión**: BARF no incluye ni documenta técnicas de evasión
  operativas (patches de fingerprinting, rotación de identidades, etc.).
- **Respeto a términos de servicio**: solo se prueban propiedades propias o
  con permiso explícito; se respeta robots.txt y el uso razonable.
- **Consentimiento y volumen**: nada de scraping a escala, nada de ocultar
  actividad.

## Enlaces a recursos académicos

- [W3C — Web Accessibility & User Agent (privacidad)](https://www.w3.org/)
- [Electronic Frontier Foundation — Panopticlick (huella del navegador)](https://panopticlick.eff.org/)
- [Tor Project — Fingerprinting research](https://www.torproject.org/about/history/)
- [OWASP — Automated Threats to Web Applications](https://owasp.org/www-project-automated-threats-to-web-applications/)
- [MDN — Navigator API](https://developer.mozilla.org/es/docs/Web/API/Navigator)
- [W3C — WebDriver specification (señal `webdriver`)](https://www.w3.org/TR/webdriver1/)
- [Playwright — Emulation docs](https://playwright.dev/python/docs/emulation)

## Referencia rápida de señales (research_demo)

| Señal | Para qué se usa en detección |
|---|---|
| `navigator.webdriver` | Marca explícita de control automatizado |
| `user_agent` / `platform` | Identificar navegador/SO; inconsistencias |
| `canvas_hash` | Huella gráfica estable (fingerprint) |
| `timezone` | Cruzar con geolocalización de la IP |
| `plugins_count` | Entornos headless suelen reportar 0 |
| `hardware_concurrency` / `device_memory` | Detectar virtualización |
