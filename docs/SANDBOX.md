# Sandbox — BARF

Módulo de **simulaciones aisladas** para estudiar cómo responden las webs a
distintos entornos: geolocalización/idioma, condiciones de red y dispositivos.

> ⚠️ Uso educativo: el sandbox sirve para *observar y aprender*. No está
> pensado para ocultar actividad, saltarse restricciones ni operar a escala.
> Todo el tráfico generado debe ser de bajo volumen y sobre propiedades propias
> o con permiso.

## Geolocalización (`youber/sandbox/geolocation.py`)

Simula la ubicación, el idioma y la zona horaria de una región en el contexto
de la página. La geolocalización usa la API pública de Playwright; el locale
(navigator.language) y la zona horaria (Intl) se emulan con *init scripts*
porque la API pública solo permite fijarlos al crear el contexto.

### Regiones disponibles

| Código | País | Locale | Zona horaria |
|---|---|---|---|
| ES | España | es-ES | Europe/Madrid |
| US | Estados Unidos | en-US | America/New_York |
| UK | Reino Unido | en-GB | Europe/London |
| DE | Alemania | de-DE | Europe/Berlin |
| FR | Francia | fr-FR | Europe/Paris |
| JP | Japón | ja-JP | Asia/Tokyo |
| BR | Brasil | pt-BR | America/Sao_Paulo |
| IN | India | hi-IN | Asia/Kolkata |
| AU | Australia | en-AU | Australia/Sydney |
| MX | México | es-MX | America/Mexico_City |

### Uso

```python
from youber.sandbox.geolocation import simulate_location, test_localization

await simulate_location(page, "ES")          # aplica geo + locale + timezone
signals = await test_localization(page, "https://example.com", "JP")
print(signals)
# {'url': ..., 'lang': 'ja-JP', 'navigator_language': 'ja-JP',
#  'timezone': 'Asia/Tokyo', 'title': ...}
```

`test_localization` navega a la URL y extrae las señales que la web detecta:
útil para estudiar localización e i18n.

## Red (`youber/sandbox/network.py`)

Emula condiciones de red vía CDP (`Network.emulateNetworkConditions`).

### Perfiles

| Perfil | Latencia | Descarga | Subida | Offline |
|---|---|---|---|---|
| `4g` | 20 ms | ~4 Mbps | ~3 Mbps | no |
| `3g` | 100 ms | ~1.6 Mbps | ~768 Kbps | no |
| `2g` | 300 ms | ~250 Kbps | ~50 Kbps | no |
| `slow-3g` | 400 ms | ~400 Kbps | ~400 Kbps | no |
| `offline` | — | — | — | sí |

### Uso

```python
from youber.sandbox.network import simulate_network, test_performance

await simulate_network(page, "3g")
results = await test_performance(page, "https://example.com", ["4g", "3g", "slow-3g"])
for r in results:
    print(r["speed"], r.get("load_time_ms"))
```

`test_performance` mide tiempos de carga (Navigation Timing API) y restablece
la red al terminar.

## Dispositivos (`youber/sandbox/device.py`)

Aplica descriptores de dispositivo (viewport, user agent, táctil, device scale factor)
mediante CDP sobre la página actual. Los descriptores son equivalentes a los
que incluye Playwright.

### Dispositivos

| Alias | Descriptor Playwright | Viewport |
|---|---|---|
| `iPhone` | iPhone 13 | 390×664 |
| `Pixel` | Pixel 7 | 412×915 |
| `iPad` | iPad (gen 7) | 810×1080 |
| `Desktop` | Desktop Chrome | 1280×720 |

### Uso

```python
from youber.sandbox.device import simulate_device

await simulate_device(page, "iPhone")
print(await page.evaluate("navigator.userAgent"))   # contiene 'iPhone'
print(await page.evaluate("'ontouchstart' in window"))  # True
```

## CLI de demostración

```bash
youber-sandbox --url https://example.com --region ES --device iPhone --speed 3g
```

Aplica las simulaciones, navega y muestra las señales que la web detecta
(idioma, zona horaria, viewport, táctil...).

## Buenas prácticas

- Usa siempre **páginas propias o de prueba** (como `example.com` o los
  fixtures locales) para los primeros experimentos.
- Respeta robots.txt y los ToS del sitio que estudies.
- Mantén volúmenes bajos: el objetivo es aprender, no medir a escala.
