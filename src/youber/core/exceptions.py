"""Excepciones propias del framework BARF.

Jerarquía:

- :class:`BrowserException` — error general de navegación.
  - :class:`TimeoutException` — la operación superó el tiempo máximo.
  - :class:`NavigationException` — error al navegar a una URL.

``TimeoutException`` también hereda de ``TimeoutError`` nativo, de forma que
``except TimeoutError`` captura tanto timeouts del framework como de Playwright.
"""


class BrowserException(Exception):
    """Error general del framework de navegación."""


class TimeoutException(BrowserException, TimeoutError):
    """La operación superó el tiempo máximo permitido."""


class NavigationException(BrowserException):
    """Error durante la navegación a una URL."""
