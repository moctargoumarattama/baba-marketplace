from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _dashboard_template() -> str:
    return (ROOT / "app/templates/admin/dashboard.html").read_text(
        encoding="utf-8-sig"
    )


def test_admin_dashboard_does_not_show_contact_kpi_strip():
    template = _dashboard_template()

    assert "activity-hub-kpis" not in template
    assert "activity-hub-kpi" not in template
    assert "Contacts 7 derniers jours" not in template
    assert "Boutiques contactees" not in template
    assert "Telephones uniques" not in template
    assert "Estimation 7 jours" not in template
