"""Utilidades de consola para BARF (compatibilidad Windows)."""

from __future__ import annotations

import os
import sys
from typing import Any

#: Variable que fuerza la codificación de stdio en los subprocesos de Python.
UTF8_STDIO_ENV = "PYTHONIOENCODING"


def _reconfigure_stream(stream: Any) -> None:
    """Reconfigura un stream de texto a UTF-8 tolerante, si el stream lo permite."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def ensure_utf8_console() -> None:
    """Reconfigura stdout/stderr a UTF-8 con ``errors="replace"``.

    Las consolas y los procesos desprendidos de Windows usan cp1252 por defecto,
    que no puede codificar emojis (🔎, ✅) ni el carácter de reemplazo (``\\ufffd``)
    que aparece al leer logs con acentos en otra codificación. Un solo ``print``
    con un carácter no codificable mata el script con ``UnicodeEncodeError``
    (pasó en ``scratch/wait_wash_and_build.py``: el montaje terminó bien y el
    proceso murió solo al volcar su salida).

    Con ``errors="replace"`` imprimir nunca lanza: como mucho sustituye el
    carácter problemático por ``?`` y el resto del log se escribe igual.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            _reconfigure_stream(stream)


def utf8_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Devuelve una copia del entorno con stdio en UTF-8.

    Pensado para ``subprocess``/``Start-Process`` desprendidos: el proceso hijo
    nace ya en UTF-8 aunque herede una consola o un redirect en cp1252.
    """
    base = dict(os.environ if env is None else env)
    base[UTF8_STDIO_ENV] = "utf-8"
    return base
