"""Simulación de geolocalización, idioma y zona horaria (uso educativo).

Permite estudiar cómo responde una web a visitantes de distintas regiones:
se cambia la geolocalización (API pública de Playwright) y se emulan el
locale y la zona horaria con *init scripts* (la API pública solo permite
fijarlos al crear el contexto, y CDP no acepta un segundo override sobre uno
ya activo). Después se extraen las señales de localización que la página
detecta.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

REGIONS: dict[str, dict[str, Any]] = {
    "ES": {"country": "España", "locale": "es-ES", "timezone": "Europe/Madrid", "latitude": 40.4168, "longitude": -3.7038},
    "US": {"country": "Estados Unidos", "locale": "en-US", "timezone": "America/New_York", "latitude": 40.7128, "longitude": -74.0060},
    "UK": {"country": "Reino Unido", "locale": "en-GB", "timezone": "Europe/London", "latitude": 51.5074, "longitude": -0.1278},
    "DE": {"country": "Alemania", "locale": "de-DE", "timezone": "Europe/Berlin", "latitude": 52.5200, "longitude": 13.4050},
    "FR": {"country": "Francia", "locale": "fr-FR", "timezone": "Europe/Paris", "latitude": 48.8566, "longitude": 2.3522},
    "JP": {"country": "Japón", "locale": "ja-JP", "timezone": "Asia/Tokyo", "latitude": 35.6762, "longitude": 139.6503},
    "BR": {"country": "Brasil", "locale": "pt-BR", "timezone": "America/Sao_Paulo", "latitude": -23.5505, "longitude": -46.6333},
    "IN": {"country": "India", "locale": "hi-IN", "timezone": "Asia/Kolkata", "latitude": 28.6139, "longitude": 77.2090},
    "AU": {"country": "Australia", "locale": "en-AU", "timezone": "Australia/Sydney", "latitude": -33.8688, "longitude": 151.2093},
    "MX": {"country": "México", "locale": "es-MX", "timezone": "America/Mexico_City", "latitude": 19.4326, "longitude": -99.1332},
}


def _locale_script(locale: str) -> str:
    """Init script que emula el locale (``navigator.language``)."""
    return f"""
    (() => {{
        Object.defineProperty(navigator, 'language', {{
            get: () => '{locale}',
            configurable: true,
        }});
    }})();
    """


def _timezone_script(timezone_id: str) -> str:
    """Init script que emula la zona horaria (``Intl``)."""
    return f"""
    (() => {{
        const orig = Intl.DateTimeFormat.prototype.resolvedOptions;
        Intl.DateTimeFormat.prototype.resolvedOptions = function () {{
            const opts = orig.call(this);
            opts.timeZone = '{timezone_id}';
            return opts;
        }};
    }})();
    """


def get_region_options() -> dict[str, dict[str, Any]]:
    """Devuelve las regiones disponibles para simulación.

    Returns:
        Diccionario ``{codigo: {country, locale, timezone, latitude, longitude}}``.
    """
    return {code: dict(info) for code, info in REGIONS.items()}


async def simulate_location(page: Any, country_code: str) -> dict[str, Any]:
    """Simula la ubicación, idioma y zona horaria de una región.

    Aplica la geolocalización con la API pública de Playwright y emula el
    locale y la zona horaria con *init scripts* (aplican en la siguiente
    navegación o recarga).

    Args:
        page: Página de Playwright.
        country_code: Código de región (ES, US, UK, JP, BR...).

    Returns:
        Información de la región aplicada (con su código).

    Raises:
        ValueError: si el código de región no existe.
    """
    region = REGIONS.get(country_code.upper())
    if region is None:
        raise ValueError(
            f"Región desconocida: {country_code}. Usa get_region_options()"
        )
    context = page.context
    await context.grant_permissions(["geolocation"])
    await context.set_geolocation(
        {"latitude": region["latitude"], "longitude": region["longitude"]}
    )
    await page.add_init_script(_locale_script(region["locale"]))
    await page.add_init_script(_timezone_script(region["timezone"]))
    logger.info(
        f"Ubicación simulada: {region['country']} ({country_code.upper()}) "
        f"[{region['timezone']}]"
    )
    return dict(region, code=country_code.upper())


async def test_localization(page: Any, url: str, region: str) -> dict[str, Any]:
    """Prueba cómo responde una web a una región determinada.

    Navega a la URL con la región simulada y extrae señales de localización
    (idioma del documento, locale del navegador, zona horaria, título).

    Args:
        page: Página de Playwright.
        url: URL a visitar.
        region: Código de región (ES, US, ...).

    Returns:
        Señales de localización detectadas en la página.
    """
    await simulate_location(page, region)
    await page.goto(url, wait_until="domcontentloaded")
    signals = await page.evaluate(
        """() => ({
            url: location.href,
            lang: document.documentElement.lang || null,
            navigator_language: navigator.language,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            title: document.title,
        })"""
    )
    logger.info(
        f"Localización ({region}): lang={signals['lang']} "
        f"nav={signals['navigator_language']} tz={signals['timezone']}"
    )
    return signals
