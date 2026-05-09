from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_maintenance_page_is_split_into_compact_sections():
    template = _read("app/templates/admin/maintenance.html")

    assert "maintenance-tabs" in template
    assert 'data-maintenance-tab="overview"' in template
    assert 'data-maintenance-tab="backups"' in template
    assert 'data-maintenance-tab="mode"' in template
    assert 'data-maintenance-tab="logs"' in template
    assert 'data-maintenance-tab="danger"' in template
    assert 'data-maintenance-panel="overview"' in template
    assert 'data-maintenance-panel="backups"' in template
    assert 'data-maintenance-panel="mode"' in template
    assert 'data-maintenance-panel="logs"' in template
    assert 'data-maintenance-panel="danger"' in template


def test_maintenance_sections_keep_existing_blocks():
    template = _read("app/templates/admin/maintenance.html")

    assert "Dernier rapport de maintenance" in template
    assert "Sante systeme" in template
    assert "Sauvegardes base de donnees" in template
    assert "Trafic live" in template
    assert "Mode maintenance" in template
    assert "Historique nettoyage" in template
    assert "Erreurs recentes" in template
    assert "Reinitialisation de la base" in template
    assert "maintenanceTabPanels" in template
