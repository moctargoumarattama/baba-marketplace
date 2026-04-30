from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_vendor_manage_shop_exports_valid_google_maps_link():
    template = _read("app/templates/vendor/manage_shop.html")

    assert "https://www.google.com/maps?q=" in template
    assert "https://www.google.com/mapsq=" not in template


def test_vendor_product_form_has_mobile_sticky_save_button_and_polished_labels():
    template = _read("app/templates/vendor/product_form.html")

    assert 'id="productForm"' in template
    assert 'class="mobile-save-bar"' in template
    assert 'form="productForm"' in template
    assert "Créer le" in template
    assert "Creez le" not in template
    assert "Apercu" not in template


def test_public_templates_do_not_keep_visible_typos():
    shop_home = _read("app/templates/shop/home.html")
    earnings = _read("app/templates/vendor/earnings.html")

    assert "choississez" not in shop_home
    assert "Choisissez" in shop_home
    assert "Paiements reçus" in earnings
    assert "Paiements recus" not in earnings
    assert "A verifier" not in earnings
    assert "Je suis payé" in earnings


def test_vendor_dashboard_no_longer_depends_on_fontawesome_icons():
    base_template = _read("app/templates/base.html")
    back_fab = _read("app/static/js/core/back_fab.js")
    dashboard = _read("app/templates/vendor/dashboard.html")
    product_grid = _read("app/templates/vendor/partials/_product_grid.html")
    dashboard_js = _read("app/static/js/pages/vendor/dashboard_page.js")

    assert "fontawesome" not in base_template.lower()
    assert "fa-arrow-left" not in back_fab
    assert "fas fa-" not in dashboard
    assert "fas fa-" not in product_grid
    assert "fas fa-" not in dashboard_js
