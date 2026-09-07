"""Módulo youber.montage — Motor de producción con OpenMontage.

Pipeline: vídeo patrón → análisis de estructura → OpenMontage hybrid pipeline →
composición final con nuestra pista de audio.
"""

from __future__ import annotations

__all__ = [
    "adapter",
    "pattern_analyzer",
    "models",
    "cli",
]

__version__ = "0.1.0"