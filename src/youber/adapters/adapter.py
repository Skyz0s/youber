# src/youber/adapters/adapter.py
"""Re-export del adaptador de OpenMontage (compatibilidad).

La implementación canónica vive en ``youber.montage.adapter`` (es la que usa
``youber-produce`` vía ``youber.montage.cli``). Este módulo se mantiene como
re-export para no romper imports antiguos de ``youber.adapters.adapter``.
"""

from __future__ import annotations

from youber.montage.adapter import DEFAULT_PIPELINE, OpenMontageAdapter, OpenMontageError

__all__ = ["DEFAULT_PIPELINE", "OpenMontageAdapter", "OpenMontageError"]
