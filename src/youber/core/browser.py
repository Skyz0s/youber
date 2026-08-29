"""Núcleo de navegación del framework BARF.

Módulo base con la clase :class:`BrowserManager`, que encapsula el ciclo de
vida de un navegador Playwright: lanzamiento, creación de contextos aislados,
páginas, navegación, lectura de títulos y cierre.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from youber.core.exceptions import BrowserException, NavigationException, TimeoutException
from youber.core.logging import log_action
from youber.settings import get_settings

DEFAULT_VIEWPORT: dict[str, int] = {"width": 1920, "height": 1080}
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
DEFAULT_LOCALE: str = "es-ES"
DEFAULT_TIMEZONE_ID: str = "Europe/Madrid"
DEFAULT_PERMISSIONS: list[str] = ["geolocation"]


class BrowserManager:
    """Gestiona el ciclo de vida de un navegador Playwright.

    Args:
        headless: Ejecutar el navegador sin interfaz gráfica. Si es ``None``,
            se usa el valor de la configuración (``BROWSER_HEADLESS``).
        timeout: Timeout por defecto (ms) para las operaciones de navegación.
            Si es ``None``, se usa el valor de la configuración
            (``BROWSER_TIMEOUT``).
    """

    def __init__(self, headless: bool | None = None, timeout: int | None = None) -> None:
        settings = get_settings()
        self.headless: bool = settings.browser_headless if headless is None else headless
        self.timeout: int = settings.browser_timeout if timeout is None else timeout
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    @property
    def is_launched(self) -> bool:
        """Indica si el navegador está lanzado."""
        return self._browser is not None

    @log_action("Lanzando navegador")
    async def launch(self) -> BrowserManager:
        """Lanza el navegador Chromium.

        Returns:
            La propia instancia, para poder encadenar llamadas.

        Raises:
            BrowserException: Si el navegador ya está lanzado o falla el arranque.
        """
        if self.is_launched:
            raise BrowserException("El navegador ya está lanzado")
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
        except PlaywrightError as exc:
            raise BrowserException(f"No se pudo lanzar el navegador: {exc}") from exc
        logger.debug(f"Navegador lanzado (headless={self.headless})")
        return self

    @log_action("Creando contexto")
    async def new_context(self, **kwargs: Any) -> BrowserContext:
        """Crea un contexto de navegación aislado con valores por defecto.

        Los valores por defecto son: viewport 1920x1080, user agent de Chrome
        en Windows, locale ``es-ES``, timezone ``Europe/Madrid`` y permiso de
        geolocalización. Cualquier ``kwarg`` pasado sobrescribe su valor.

        Args:
            **kwargs: Opciones adicionales de Playwright que sobrescriben los
                valores por defecto.

        Returns:
            El contexto de navegación creado.

        Raises:
            BrowserException: Si el navegador no está lanzado.
        """
        self._require_launched()
        defaults: dict[str, Any] = {
            "viewport": DEFAULT_VIEWPORT,
            "user_agent": DEFAULT_USER_AGENT,
            "locale": DEFAULT_LOCALE,
            "timezone_id": DEFAULT_TIMEZONE_ID,
            "permissions": DEFAULT_PERMISSIONS,
        }
        defaults.update(kwargs)
        context = await self._browser.new_context(**defaults)  # type: ignore[union-attr]
        logger.debug(
            f"Contexto creado (locale={defaults['locale']}, "
            f"timezone={defaults['timezone_id']}, viewport={defaults['viewport']})"
        )
        return context

    @log_action("Creando página")
    async def new_page(self, context: BrowserContext) -> Page:
        """Crea una nueva página dentro del contexto indicado.

        Args:
            context: Contexto de navegación donde crear la página.

        Returns:
            La página recién creada.
        """
        page = await context.new_page()
        logger.debug(f"Página creada: {page.url}")
        return page

    @log_action("Navegando")
    async def navigate(self, page: Page, url: str) -> int | None:
        """Navega a la URL indicada en la página dada.

        Args:
            page: Página sobre la que navegar.
            url: URL de destino.

        Returns:
            Código de estado HTTP de la respuesta, o ``None`` para esquemas
            sin respuesta HTTP (p. ej. ``file://`` o ``data:``).

        Raises:
            TimeoutException: Si la navegación supera el timeout configurado.
            NavigationException: Si la navegación falla por cualquier otro motivo.
        """
        try:
            response = await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as exc:
            raise TimeoutException(f"Timeout ({self.timeout} ms) navegando a {url}") from exc
        except PlaywrightError as exc:
            raise NavigationException(f"No se pudo navegar a {url}: {exc}") from exc
        status = response.status if response is not None else None
        logger.debug(f"Página cargada: {url} (status={status})")
        return status

    @log_action("Obteniendo título")
    async def get_title(self, page: Page) -> str:
        """Obtiene el título de la página actual.

        Args:
            page: Página de la que leer el título.

        Returns:
            El título de la página.

        Raises:
            TimeoutException: Si la operación supera el timeout configurado.
            BrowserException: Si falla la lectura del título.
        """
        try:
            return await page.title()
        except PlaywrightTimeoutError as exc:
            raise TimeoutException("Timeout obteniendo el título de la página") from exc
        except PlaywrightError as exc:
            raise BrowserException(f"No se pudo obtener el título: {exc}") from exc

    @log_action("Cerrando navegador")
    async def close(self) -> None:
        """Cierra el navegador y libera los recursos de Playwright."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        logger.debug("Navegador cerrado")

    def _require_launched(self) -> None:
        """Lanza :class:`BrowserException` si el navegador no está lanzado."""
        if not self.is_launched:
            raise BrowserException("El navegador no está lanzado. Usa launch() primero")
