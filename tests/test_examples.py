"""Validación de los ejemplos (auditorías sobre una página local)."""

from pathlib import Path

from examples.audit_github import audit as audit_github
from examples.audit_google import audit as audit_google
from examples.audit_youtube import audit as audit_youtube
from examples.batch_audit import audit_csv
from examples.custom_audit import audit as audit_custom

ACCESSIBLE_URL = (Path(__file__).parent / "fixtures" / "accessible.html").resolve().as_uri()


async def test_audit_examples(tmp_path):
    """Los tres ejemplos de auditoría generan reporte Markdown válido."""
    for audit in (audit_google, audit_youtube, audit_github):
        report = await audit(ACCESSIBLE_URL, output_dir=tmp_path, headless=True)
        assert report.exists()
        content = report.read_text(encoding="utf-8")
        assert "Reporte de accesibilidad" in content
        assert "Sin violaciones" in content


async def test_custom_audit_example(tmp_path):
    """custom_audit respeta reglas/impactos y genera MD + JSON."""
    report = await audit_custom(
        ACCESSIBLE_URL,
        rules=["color-contrast"],
        impact_levels=["serious"],
        output_dir=tmp_path,
    )
    assert report.exists()
    json_files = list(tmp_path.glob("*.json"))
    assert json_files, "custom_audit debe generar también el reporte JSON"


async def test_batch_audit_example(tmp_path):
    """batch_audit procesa un CSV y genera reportes + resumen."""
    csv_path = tmp_path / "urls.csv"
    csv_path.write_text(f"url,name\n{ACCESSIBLE_URL},Accesible\n", encoding="utf-8")
    summary = await audit_csv(csv_path, output_dir=tmp_path)
    assert summary.exists()
    content = summary.read_text(encoding="utf-8")
    assert "Accesible" in content
    assert (tmp_path / "accesible.md").exists()
