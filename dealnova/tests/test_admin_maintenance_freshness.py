from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_maintenance_route_exposes_health_freshness_context():
    source = _read("app/routes/admin.py")

    assert "def _maintenance_health_freshness(" in source
    assert '"health_freshness": _maintenance_health_freshness(last_run, days)' in source
    assert '"status_label": "Frais"' in source
    assert '"status_label": "Ancien"' in source
    assert "is_fresh = total_seconds < 86400" in source


def test_maintenance_template_shows_health_freshness_and_recalc_command():
    template = _read("app/templates/admin/maintenance.html")

    assert "Données calculées le" in template
    assert "health_freshness.status_label" in template
    assert "Recalculer" in template
    assert "Commande à lancer" in template
    assert "flask cleanup --mode quick --days {{ days }}" in template


def test_maintenance_last_report_summary_hides_run_metadata_cards():
    template = _read("app/templates/admin/maintenance.html")

    assert "<strong>Mode</strong><span>{{ 'rapide'" not in template
    assert "<strong>Date d'execution</strong>" not in template
    assert "<strong>Duree</strong><span>{{ report.duration_ms" not in template
    assert "<strong>Fichiers supprimes</strong>" in template
