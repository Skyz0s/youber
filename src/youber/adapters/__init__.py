"""Paquete de adaptadores de integración (OpenMontage, etc.)."""

from __future__ import annotations

from youber.adapters.adapter import (
    DEFAULT_PIPELINE,
    OpenMontageAdapter,
    OpenMontageError,
)

__all__ = ["DEFAULT_PIPELINE", "OpenMontageAdapter", "OpenMontageError"]
