from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_vendor_manage_shop_exports_valid_google_maps_link():
    template = _read("app/templates/vendor/manage_shop.html")

    assert "https://www.google.com/maps?q=" in template
    assert "https://www.google.com/mapsq=" not in template


def test_vendor_manage_shop_does_not_show_opening_control_card():
    template = _read("app/templates/vendor/manage_shop.html")
    script = _read("app/static/js/pages/vendor/manage_shop_page.js")

    assert "Ouverture de la boutique" not in template
    assert "manageShopOpenStateCard" not in template
    assert "vendor.set_shop_open_state" not in template
    assert "Fermer temporairement" not in template
    assert '<i class="bi bi-door-open me-2"></i> Ouvrir la boutique' not in template
    assert "removeLegacyOpeningCard" in script
    assert "Ouverture de la boutique" in script


def test_product_service_shop_requires_phone_and_address():
    vendor_routes = _read("app/routes/vendor.py")
    edit_template = _read("app/templates/vendor/edit_shop.html")

    assert "_shop_requires_contact_details" in vendor_routes
    assert "_shop_has_required_contact_details" in vendor_routes
    assert "telephone et adresse sont obligatoires" in vendor_routes
    assert "return redirect(url_for(\"vendor.edit_shop\"))" in vendor_routes
    assert 'name="contact_phone"' in edit_template
    assert 'name="address"' in edit_template
    assert "required" in edit_template


def test_client_welcome_heads_up_notification_is_loaded_for_public_shell():
    base_template = _read("app/templates/base.html")
    script = _read("app/static/js/client_welcome_notification.js")

    assert "js/client_welcome_notification.js" in base_template
    assert "Bienvenue sur Baba Market" in script
    assert "showNativeWelcomeNotification" in script
    assert "registration.showNotification" in script
    assert "Notification.requestPermission" in script
    assert "navigator.vibrate" in script
    assert "vendor" in script and "admin" in script and "manager" in script
    assert "client-welcome-headsup" not in script


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
    assert "Caisse vendeur" in earnings
    assert "Paiements recus" not in earnings
    assert "A verifier" not in earnings
    assert "Marquer encaissé" in earnings


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


def test_login_vendor_card_matches_current_vendor_request_workflow():
    template = _read("app/templates/auth/login.html")

    assert "Accès vendeur" in template
    assert "Demander un accès vendeur" in template
    assert "Continuer sans compte" in template
    assert "Comment ça marche" not in template
    assert "ouvrir WhatsApp" not in template
    assert "On vous crée un compte et on vous envoie vos identifiants" not in template


def test_mobile_menu_button_uses_modern_visible_shell():
    css = _read("app/static/css/ui_shell.css")

    assert ".menu-toggle-icon::before" in css
    assert "linear-gradient(145deg, #10b981, #047857)" in css
    assert "min-width: clamp(4.12rem, 23vw, 4.48rem)" in css
    assert "color: #064e3b" in css


def test_mobile_drawer_height_adapts_to_content_without_bottom_gap():
    css = _read("app/static/css/ui_drawer_glass.css")

    assert "bottom: auto;" in css
    assert "height: auto !important;" in css
    assert "max-height: calc(100dvh - var(--bm-safe-bottom, 0px));" in css
    assert "min-height: 0;" in css
    assert "height: 100dvh !important;" not in css
    assert "min-height: calc(100dvh - var(--bm-safe-top, 0px));" not in css


def test_vendor_access_form_is_compact_and_mobile_adaptive():
    template = _read("app/templates/auth/vendor_access.html")

    assert "max-width: 560px" in template
    assert "padding: clamp(0.9rem, 3vw, 1.45rem)" in template
    assert "overflow-x: clip" in template
    assert "max-width: 100%" in template
    assert "min-height: auto;" in template
    assert "min-height: 2.15rem" in template
    assert 'rows="2"' in template
    assert "Validation admin avant activation." in template
    assert "Votre demande sera verifiee par un admin/gestionnaire" not in template


def test_admin_vendor_request_pages_use_plain_french_guidance():
    vendor_requests = _read("app/templates/admin/vendor_requests.html")
    change_requests = _read("app/templates/admin/vendor_change_requests.html")

    assert "A faire maintenant" in vendor_requests
    assert "Ces personnes veulent ouvrir une boutique" in vendor_requests
    assert "Accepter et creer le compte vendeur" in vendor_requests
    assert "Refuser cette demande" in vendor_requests
    assert "Bloquer ce contact" in vendor_requests

    assert "A faire maintenant" in change_requests
    assert "Ces vendeurs demandent une modification" in change_requests
    assert "Avant" in change_requests
    assert "Apres" in change_requests
    assert "Accepter la modification" in change_requests
