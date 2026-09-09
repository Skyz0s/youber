"""Tests de youber.montage: driver incluido, CLI --topic e instalacion.

Sin red: se verifica que el driver empaquetado (montage_driver/montage.py)
existe y cumple el contrato, que adapter.install_driver() lo copia al clon,
y el modo --topic del CLI con adapter/analizador mockeados (el driver real
NO se ejecuta aqui: necesita PEXELS_API_KEY o --demo).
"""

from __future__ import annotations

from pathlib import Path

from youber.montage.adapter import OpenMontageAdapter
from youber.montage.cli import _run_produce, build_parser
from youber.montage.models import PatternSource, ProductionPlan

DRIVER_SOURCE = Path(__file__).resolve().parents[1] / "montage_driver" / "montage.py"

_CONTRACT_FLAGS = (
    "--prompt",
    "--output-dir",
    "--output",
    "--pipeline",
    "--playbook",
    "--budget-usd",
    "--duration",
    "--resolution",
    "--fps",
)


def _make_fake_clone(root: Path) -> Path:
    """Checkout fake de OpenMontage (solo marcadores, sin driver)."""
    clone = root / "OpenMontage"
    clone.mkdir(parents=True, exist_ok=True)
    (clone / "config.yaml").write_text("name: openmontage-fake\n", encoding="utf-8")
    return clone


# ---------------------------------------------------------------------------
# Driver empaquetado
# ---------------------------------------------------------------------------


def test_driver_empaquetado_existe_y_cumple_contrato():
    """El repo versiona montage_driver/montage.py con la interfaz del contrato."""
    assert DRIVER_SOURCE.is_file()
    content = DRIVER_SOURCE.read_text(encoding="utf-8")
    for flag in _CONTRACT_FLAGS + ("--self-check", "--demo"):
        assert flag in content, f"falta {flag} en el driver"


# ---------------------------------------------------------------------------
# install_driver()
# ---------------------------------------------------------------------------


def test_install_driver_copia_al_clon(tmp_path):
    clone = _make_fake_clone(tmp_path)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    assert not adapter.available()
    installed = adapter.install_driver()
    assert installed == clone / "montage.py"
    assert installed is not None and installed.is_file()
    assert adapter.available()
    assert installed.read_bytes() == DRIVER_SOURCE.read_bytes()


def test_install_driver_no_sobrescribe_sin_force(tmp_path):
    clone = _make_fake_clone(tmp_path)
    (clone / "montage.py").write_text("# driver local custom\n", encoding="utf-8")
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    installed = adapter.install_driver()
    assert installed is not None
    assert "# driver local custom" in installed.read_text(encoding="utf-8")


def test_install_driver_force_sobrescribe(tmp_path):
    clone = _make_fake_clone(tmp_path)
    (clone / "montage.py").write_text("# driver local custom\n", encoding="utf-8")
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    installed = adapter.install_driver(force=True)
    assert installed is not None
    assert installed.read_bytes() == DRIVER_SOURCE.read_bytes()


def test_install_driver_sin_clon_devuelve_none(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMONTAGE_DIR", raising=False)
    adapter = OpenMontageAdapter(project_dir=tmp_path)
    assert adapter.openmontage_dir is None
    assert adapter.install_driver() is None


# ---------------------------------------------------------------------------
# CLI: --topic (tema libre)
# ---------------------------------------------------------------------------


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


async def test_cli_topic_no_usa_analizador(tmp_path, monkeypatch):
    """--topic construye el plan sin PatternAnalyzer (sin patron que analizar)."""
    import youber.montage.cli as cli

    def boom(*_args, **_kwargs):  # el analizador NO debe llegar a usarse
        raise AssertionError("PatternAnalyzer no debe ejecutarse con --topic")

    monkeypatch.setattr(cli, "PatternAnalyzer", boom)
    monkeypatch.setattr(cli, "OpenMontageAdapter", FakeAdapterSuccess)
    out_file = tmp_path / "demo.mp4"
    args = build_parser().parse_args(
        ["--topic", "Python tutorial", "--pipeline", "screen-demo", "-o", str(out_file)]
    )
    code = await _run_produce(args)
    assert code == 0
    plan = FakeAdapterSuccess.last_plan
    assert plan is not None
    assert plan.pattern.title == "Python tutorial"
    assert plan.pipeline == "screen-demo"
    assert plan.pattern.source == PatternSource.LOCAL
    assert plan.output_path == out_file


async def test_cli_sin_pattern_ni_topic_devuelve_1(monkeypatch):
    """Sin --pattern ni --topic, youber-produce falla con codigo 1."""

    class FakeAdapter:
        def __init__(self, project_dir: Path | None = None):
            self.project_dir = project_dir

        async def produce(self, plan: ProductionPlan):  # noqa: ARG002
            raise AssertionError("no debe producir sin entrada")

    import youber.montage.cli as cli

    monkeypatch.setattr(cli, "PatternAnalyzer", lambda *a, **k: None)
    monkeypatch.setattr(cli, "OpenMontageAdapter", FakeAdapter)
    args = build_parser().parse_args([])
    code = await _run_produce(args)
    assert code == 1


# ---------------------------------------------------------------------------
# CLI: --install-driver
# ---------------------------------------------------------------------------


class FakeAdapterInstall:
    target: Path | None = None

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir

    def install_driver(self, force: bool = False):
        FakeAdapterInstall.target = Path("montage.py")
        return FakeAdapterInstall.target

    def describe(self) -> str:
        return "fake"


async def test_cli_install_driver_devuelve_0(monkeypatch):
    import youber.montage.cli as cli

    monkeypatch.setattr(cli, "OpenMontageAdapter", FakeAdapterInstall)
    args = build_parser().parse_args(["--install-driver"])
    code = await _run_produce(args)
    assert code == 0
    assert FakeAdapterInstall.target == Path("montage.py")


class FakeAdapterNoInstall:
    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir

    def install_driver(self, force: bool = False):
        return None

    def describe(self) -> str:
        return "no hay clon"


async def test_cli_install_driver_sin_clon_devuelve_1(monkeypatch):
    import youber.montage.cli as cli

    monkeypatch.setattr(cli, "OpenMontageAdapter", FakeAdapterNoInstall)
    args = build_parser().parse_args(["--install-driver"])
    code = await _run_produce(args)
    assert code == 1
