"""Configuración de pytest para BARF.

Añade al ``sys.path`` la raíz del proyecto (para importar ``config``) y el
directorio ``src`` (para importar el paquete ``youber``). También aísla el
*decision journal* del usuario: ningún test escribe en ``~/.youber``.

Los tests que necesitan **salida a internet** (navegan a ``example.com``) van
marcados con ``needs_network`` y se saltan solos cuando no hay red: así la
suite queda verde de verdad en una máquina sin salida, en vez de acumular
fallos de entorno que se confunden con bugs.
"""

import sys
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

#: Destino que usan los tests de navegación real (ver ``needs_network``).
NETWORK_PROBE_URL = "https://example.com"
NETWORK_PROBE_TIMEOUT = 5.0


@pytest.fixture(autouse=True)
def _isolate_journal_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirige ``YOUBER_JOURNAL_DB`` a un directorio temporal por test.

    Igual que con ``OPENMONTAGE_DIR``: los tests no deben tocar el estado real
    del usuario. Los que necesitan un journal concreto pasan su propia ruta.
    """
    monkeypatch.setenv("YOUBER_JOURNAL_DB", str(tmp_path / "journal.db"))


@lru_cache(maxsize=1)
def network_available() -> bool:
    """``True`` si hay salida real a internet (se comprueba una vez por sesión).

    Se pide la página de verdad: un *firewall* puede aceptar la conexión TCP y
    luego resetear el TLS, así que un simple ``connect()`` mentiría y los tests
    de navegación volverían a fallar en vez de saltarse.
    """
    try:
        with urllib.request.urlopen(
            NETWORK_PROBE_URL, timeout=NETWORK_PROBE_TIMEOUT
        ) as response:
            return getattr(response, "status", 200) == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Salta los tests ``needs_network`` cuando no hay salida a internet."""
    if network_available():
        return
    skip = pytest.mark.skip(
        reason=f"sin salida a {NETWORK_PROBE_URL}: test de navegación real saltado"
    )
    for item in items:
        if "needs_network" in item.keywords:
            item.add_marker(skip)
