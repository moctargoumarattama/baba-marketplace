from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_audience_page_keeps_all_existing_monitoring_sections():
    template = _read("app/templates/admin/audience.html")

    assert "aud-monitor-polish" in template
    assert "aud-hero" in template
    assert "audMainCards" in template
    assert "audConversionCards" in template
    assert "audConnectedList" in template
    assert "audTopPages" in template
    assert "audTopSources" in template
    assert "audHeatmap" in template
    assert "audCities" in template
    assert "audHeaderDebug" in template
    assert "Installations app total" in template
    assert "Nouveaux visiteurs" in template
    assert "Visiteurs de retour" in template


def test_audience_page_uses_clear_french_without_mojibake():
    template = _read("app/templates/admin/audience.html")

    assert "Résumé en direct" in template
    assert "Détails" in template
    assert "Équipe seulement" in template
    assert "Données Cloudflare reçues" in template
    assert "Ã" not in template
    assert "â€™" not in template
