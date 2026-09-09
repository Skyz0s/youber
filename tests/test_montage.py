"""Tests del módulo youber.montage: adapter OpenMontage, CLI youber-produce.

Estrategia: sin red ni clon real de OpenMontage. Se crean checkouts fake
(tmp_path) con un driver ``montage.py`` que escribe un .mp4 de mentira para
ejercitar el subprocess real, y se mockean analizador/adapter para el e2e CLI.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from youber.adapters import OpenMontageAdapter as ReexportedAdapter
from youber.adapters.adapter import OpenMontageAdapter as ReexportedAdapterDirect
from youber.montage.adapter import OpenMontageAdapter, OpenMontageError
from youber.montage.cli import _run_produce, build_parser
from youber.montage.models import PatternSource, PatternSpec, ProductionPlan

FAKE_DRIVER_OK = """\
import argparse
import pathlib

p = argparse.ArgumentParser()
p.add_argument("--prompt")
p.add_argument("--output-dir")
p.add_argument("--output")
p.add_argument("--pipeline")
p.add_argument("--playbook")
p.add_argument("--budget-usd")
p.add_argument("--duration")
p.add_argument("--resolution")
p.add_argument("--fps")
args = p.parse_args()

out_dir = pathlib.Path(args.output_dir)
out_dir.mkdir(parents=True, exist_ok=True)
target = pathlib.Path(args.output) if args.output else out_dir / "video.mp4"
target.write_bytes(b"fake-mp4-content")
print(f"ok {target}")
"""

FAKE_DRIVER_FAIL = """\
import sys
print("driver exploded", file=sys.stderr)
sys.exit(2)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_clone(root: Path, driver_body: str = FAKE_DRIVER_OK) -> Path:
    """Crea un checkout fake de OpenMontage con config.yaml + montage.py."""
    clone = root / "OpenMontage"
    clone.mkdir(parents=True, exist_ok=True)
    (clone / "config.yaml").write_text("name: openmontage-fake\n", encoding="utf-8")
    (clone / "montage.py").write_text(driver_body, encoding="utf-8")
    return clone


def _make_plan(*, output_path: Path | None = None) -> ProductionPlan:
    pattern = PatternSpec(
        source=PatternSource.LOCAL,
        path="pattern.mp4",
        title="Patrón de prueba",
        duration=30.0,
        resolution=(1920, 1080),
        fps=30.0,
    )
    return ProductionPlan(pattern=pattern, pipeline="documentary", output_path=output_path)


# ---------------------------------------------------------------------------
# Unificación de adapters
# ---------------------------------------------------------------------------


def test_re_export_adapta_mismo_tipo():
    """adapters/adapter.py y adapters/__init__.py re-exportan el canónico."""
    assert ReexportedAdapter is OpenMontageAdapter
    assert ReexportedAdapterDirect is OpenMontageAdapter


def test_adapter_expone_produce_y_produce_video():
    """El adapter canónico (usado por el CLI) expone produce() + produce_video()."""
    adapter = OpenMontageAdapter(project_dir=Path("."))
    assert hasattr(adapter, "produce")
    assert hasattr(adapter, "produce_video")


# ---------------------------------------------------------------------------
# Detección del checkout
# ---------------------------------------------------------------------------


def test_available_con_clon_y_driver(tmp_path: Path):
    clone = _make_fake_clone(tmp_path)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    assert adapter.openmontage_dir == clone
    assert adapter.driver == clone / "montage.py"
    assert adapter.available()


def test_no_disponible_sin_clon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENMONTAGE_DIR", raising=False)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    assert not adapter.available()
    assert "OPENMONTAGE_DIR" in adapter.describe()


def test_no_disponible_clon_sin_driver(tmp_path: Path):
    clone = tmp_path / "OpenMontage"
    clone.mkdir()
    (clone / "config.yaml").write_text("name: openmontage\n", encoding="utf-8")
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    assert adapter.openmontage_dir == clone
    assert not adapter.available()
    assert "montage.py" in adapter.describe()


def test_openmontage_dir_por_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clone = _make_fake_clone(tmp_path, FAKE_DRIVER_FAIL)
    monkeypatch.setenv("OPENMONTAGE_DIR", str(clone))
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    assert adapter.openmontage_dir == clone
    assert adapter.available()


# ---------------------------------------------------------------------------
# produce() con driver fake (subprocess real)
# ---------------------------------------------------------------------------


async def test_produce_ok_sin_output_path(tmp_path: Path):
    _make_fake_clone(tmp_path)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    result = await adapter.produce(_make_plan())
    assert result.success is True
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.suffix == ".mp4"


async def test_produce_ok_con_output_path(tmp_path: Path):
    _make_fake_clone(tmp_path)
    out_file = tmp_path / "mi_video.mp4"
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    result = await adapter.produce(_make_plan(output_path=out_file))
    assert result.success is True
    assert result.output_path == out_file
    assert out_file.exists()


async def test_produce_ok_con_output_path_relativo(tmp_path: Path):
    """Rutas relativas se resuelven contra el proyecto, no contra el clon.

    Regresión: el driver corre con cwd=OpenMontage; si el adaptador pasaba
    una ruta de salida relativa (p.ej. ``output/out.mp4``), el MP4 acababa
    en el clon y el adaptador fallaba con "no escribió el archivo esperado".
    """
    _make_fake_clone(tmp_path)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    result = await adapter.produce(_make_plan(output_path=Path("output/mi_video.mp4")))
    assert result.success is True
    assert result.output_path is not None
    assert result.output_path.is_absolute()
    assert result.output_path == (tmp_path / "output" / "mi_video.mp4").resolve()
    assert result.output_path.exists()


async def test_produce_sin_clon_devuelve_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENMONTAGE_DIR", raising=False)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    result = await adapter.produce(_make_plan())
    assert result.success is False
    assert result.output_path is None
    assert result.error is not None
    assert "OPENMONTAGE_DIR" in result.error


async def test_produce_driver_fallido_devuelve_error(tmp_path: Path):
    _make_fake_clone(tmp_path, FAKE_DRIVER_FAIL)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    result = await adapter.produce(_make_plan())
    assert result.success is False
    assert result.error is not None
    assert "exit 2" in result.error or "OpenMontage falló" in result.error


async def test_produce_video_sin_clon_lanza_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OPENMONTAGE_DIR", raising=False)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    with pytest.raises(OpenMontageError):
        await adapter.produce_video("tema", output_dir=tmp_path)


# ---------------------------------------------------------------------------
# e2e CLI (youber-produce) con mocks
# ---------------------------------------------------------------------------


class FakeAnalyzer:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def analyze(self, pattern_input: str) -> PatternSpec:
        return PatternSpec(
            source=PatternSource.LOCAL,
            path=pattern_input,
            title="Fake pattern",
            duration=30.0,
            resolution=(1920, 1080),
            fps=30.0,
        )


class FakeAdapterSuccess:
    last_plan: ProductionPlan | None = None

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir

    async def produce(self, plan: ProductionPlan):
        FakeAdapterSuccess.last_plan = plan
        return type(
            "Result",
            (),
            {
                "success": True,
                "output_path": Path("out.mp4"),
                "duration": 30.0,
                "resolution": (1920, 1080),
                "error": None,
            },
        )()


class FakeAdapterFailure:
    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir

    async def produce(self, plan: ProductionPlan):
        return type(
            "Result",
            (),
            {
                "success": False,
                "output_path": None,
                "duration": 0.0,
                "resolution": (0, 0),
                "error": "pipeline híbrido no soportado",
            },
        )()


async def test_cli_produce_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import youber.montage.cli as cli

    monkeypatch.setattr(cli, "PatternAnalyzer", FakeAnalyzer)
    monkeypatch.setattr(cli, "OpenMontageAdapter", FakeAdapterSuccess)
    out_file = tmp_path / "out.mp4"
    args = build_parser().parse_args(
        ["--pattern", "video.mp4", "--mood", "epica", "-o", str(out_file)]
    )
    code = await _run_produce(args)
    assert code == 0
    assert FakeAdapterSuccess.last_plan is not None
    assert FakeAdapterSuccess.last_plan.audio.mood == "epica"


async def test_cli_produce_error_retorna_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import youber.montage.cli as cli

    monkeypatch.setattr(cli, "PatternAnalyzer", FakeAnalyzer)
    monkeypatch.setattr(cli, "OpenMontageAdapter", FakeAdapterFailure)
    args = build_parser().parse_args(
        ["--pattern", "video.mp4", "--audio", "musica.mp3"]
    )
    code = await _run_produce(args)
    assert code == 1


# ---------------------------------------------------------------------------
# Integración real (solo si hay un checkout de OpenMontage con driver)
# ---------------------------------------------------------------------------

_HAS_REAL_OPENMONTAGE = bool(os.environ.get("OPENMONTAGE_DIR")) and (
    Path(os.environ["OPENMONTAGE_DIR"]) / "montage.py"
).exists()


@pytest.mark.skipif(
    not _HAS_REAL_OPENMONTAGE,
    reason="Requiere OPENMONTAGE_DIR con montage.py (driver real)",
)
async def test_produce_integracion_real(tmp_path: Path):
    """Con un clon real que tenga driver montage.py, produce() genera vídeo."""
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    assert adapter.available()
    result = await adapter.produce(_make_plan())
    assert result.success is True
    assert result.output_path is not None
    assert result.output_path.exists()
