"""Prueba end-to-end de todo el proceso (necesita FFmpeg; se salta si no está).

Ejecuta ``examples/e2e_pipeline.py``: catálogo sintético → workflow
``--lyrics-video`` → journal → subida → métricas → importación del CSV de
Studio → dataset → informe → recordatorio.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from examples.e2e_pipeline import run_e2e

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.mark.skipif(not HAS_FFMPEG, reason="Requiere FFmpeg/ffprobe")
async def test_e2e_todo_el_proceso(tmp_path: Path) -> None:
    """Las 8 etapas del proceso pasan y dejan artefactos reales."""
    outcome = await run_e2e(tmp_path / "e2e", duration=4)

    fallos = [f"{check.name}: {check.detail}" for check in outcome["checks"] if not check.ok]
    assert not fallos, f"etapas fallidas: {fallos}"
    assert outcome["ok"] is True
    assert len(outcome["checks"]) == 8

    artefactos = outcome["artifacts"]
    assert artefactos["vídeo final"].is_file()
    assert artefactos["vídeo final"].stat().st_size > 1000
    assert artefactos["CSV de Studio"].is_file()
    assert "Informe del registro" in artefactos["informe de análisis"].read_text(encoding="utf-8")
    assert artefactos["journal"].is_file()
