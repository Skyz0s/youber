"""Configuración de pytest para BARF.

Añade al ``sys.path`` la raíz del proyecto (para importar ``config``) y el
directorio ``src`` (para importar el paquete ``youber``). También aísla el
*decision journal* del usuario: ningún test escribe en ``~/.youber``.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@pytest.fixture(autouse=True)
def _isolate_journal_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirige ``YOUBER_JOURNAL_DB`` a un directorio temporal por test.

    Igual que con ``OPENMONTAGE_DIR``: los tests no deben tocar el estado real
    del usuario. Los que necesitan un journal concreto pasan su propia ruta.
    """
    monkeypatch.setenv("YOUBER_JOURNAL_DB", str(tmp_path / "journal.db"))
