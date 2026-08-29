"""Utilidades de consola para BARF (compatibilidad Windows)."""

from __future__ import annotations

import sys


def ensure_utf8_console() -> None:
    """Reconfigura stdout/stderr a UTF-8 cuando el sistema usa otra codificación.

    Las consolas de Windows usan cp1252 por defecto, que no puede codificar
    emojis (🔎, 📄, ✅...). Con ``errors="replace"`` la salida nunca rompe el
    script, y en terminales modernos los emojis se muestran correctamente.
    """
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            except (AttributeError, ValueError):
                pass
