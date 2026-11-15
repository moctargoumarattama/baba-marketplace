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


def test_admin_dashboard_compact_layout_without_duplications():
    template = _dashboard_template()

    # Compact two-column Bento row + bounded insight lists
    assert "dash-bento-row" in template
    assert "activity-insights" in template
    assert "scrollbar-gutter: stable" in template
    assert "overscroll-behavior: contain" in template

    # Redundant duplicate blocks removed
    assert "Actions rapides" not in template
    assert "activity-hub-card" not in template
    assert "Ce qui demande votre attention" not in template


def test_noc_dark_mode_removed_across_app():
    app_dir = ROOT / "app"
    forbidden = (
        'data-admin-theme="noc"',
        'data-theme="noc"',
        "adminThemeToggle",
        "maintenanceThemeToggle",
        "admin-theme-mode",
        "admin_theme_mode",
        "Theme NOC",
    )

    offenders = []
    for ext in ("*.html", "*.css", "*.js", "*.py"):
        for path in app_dir.rglob(ext):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.relative_to(ROOT)} -> {token}")

    assert offenders == [], f"Residual NOC dark mode references found: {offenders}"


def test_admin_fraud_page_and_routes_removed():
    assert not (ROOT / "app/templates/admin/fraud.html").exists()

    for rel in (
        "app/routes/admin_users.py",
        "app/routes/admin.py",
        "app/templates/admin/base.html",
        "app/templates/admin/bookings.html",
        "app/static/js/core/page_loader.js",
        "app/static/js/admin/admin_table.js",
    ):
        content = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        assert "fraud_monitor" not in content
        assert "/admin/fraud" not in content
        assert "initFraudPage" not in content

