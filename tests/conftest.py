"""Configuración de pytest para BARF.

Añade al ``sys.path`` la raíz del proyecto (para importar ``config``) y el
directorio ``src`` (para importar el paquete ``youber``).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
