"""Mantener el equipo despierto mientras dura el lote de generación.

En Windows el plan de energía suspende el equipo tras un rato sin actividad:
sin esto, un lote de ocho horas moriría a los pocos minutos de dejar de tocar
el ratón — y el trabajo programado de las 22:00 ni siquiera llegaría a arrancar
si el equipo se durmió antes.

:func:`keep_awake` guarda los tiempos de suspensión actuales (corriente alterna
y batería), los pone a «nunca» y los **restaura al salir**, pase lo que pase.
Fuera de Windows —o si ``powercfg`` no está disponible— no hace nada: el módulo
de generación no depende de esto para funcionar.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager

#: Valor de ``powercfg`` que significa «no suspender».
NEVER = 0

#: Valores hexadecimales de la consulta de ``powercfg``: los dos últimos son
#: los de corriente alterna y batería (los tres primeros, mínimo, máximo e
#: incremento). La consulta está localizada, así que se leen por posición.
_HEX = re.compile(r"0x[0-9a-fA-F]+")


def is_windows() -> bool:
    """``True`` si el sistema es Windows (único donde aplica este módulo)."""
    return sys.platform.startswith("win")


def _run_powercfg(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Ejecuta ``powercfg`` sin shell y con la salida capturada."""
    return subprocess.run(["powercfg", *args], capture_output=True)


def _text(result: subprocess.CompletedProcess[bytes]) -> str:
    """Salida de ``powercfg`` como texto ASCII-seguro (solo se leen hex y flags)."""
    raw = (result.stdout or b"") + (result.stderr or b"")
    return raw.decode("utf-8", "replace")


def standby_timeouts() -> tuple[int | None, int | None]:
    """Tiempos de suspensión actuales en segundos: ``(alterna, batería)``.

    Returns:
        Los dos valores, o ``(None, None)`` si no se pueden leer (sin Windows,
        sin ``powercfg`` o respuesta inesperada).
    """
    if not is_windows():
        return None, None
    try:
        result = _run_powercfg(["query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"])
    except OSError:
        return None, None
    if result.returncode != 0:
        return None, None
    values = _HEX.findall(_text(result))
    if len(values) < 2:
        return None, None
    return int(values[-2], 16), int(values[-1], 16)


def set_standby_timeout(seconds: int, *, battery: bool = False) -> bool:
    """Pone el tiempo de suspensión (corriente alterna o batería).

    Returns:
        ``True`` si el sistema aceptó el cambio.
    """
    if not is_windows():
        return False
    flag = "standby-timeout-dc" if battery else "standby-timeout-ac"
    try:
        result = _run_powercfg(["/change", flag, str(int(seconds))])
    except OSError:
        return False
    return result.returncode == 0


@contextmanager
def keep_awake() -> Iterator[bool]:
    """Desactiva la suspensión durante el bloque y la deja como estaba al salir.

    Yields:
        ``True`` si de verdad se ha desactivado (Windows con ``powercfg``),
        ``False`` si el sistema no lo necesita o no se puede.
    """
    if not is_windows():
        yield False
        return
    alterna, bateria = standby_timeouts()
    if alterna is None or bateria is None:
        yield False
        return
    desactivado = set_standby_timeout(NEVER) or set_standby_timeout(NEVER, battery=True)
    try:
        yield desactivado
    finally:
        set_standby_timeout(alterna)
        set_standby_timeout(bateria, battery=True)
