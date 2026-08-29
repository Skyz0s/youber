"""Núcleo del framework BARF: navegación, fixtures y utilidades."""

from youber.core.browser import BrowserManager
from youber.core.exceptions import BrowserException, NavigationException, TimeoutException

__all__ = [
    "BrowserManager",
    "BrowserException",
    "NavigationException",
    "TimeoutException",
]
