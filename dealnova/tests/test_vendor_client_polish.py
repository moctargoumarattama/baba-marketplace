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


def test_vendor_manage_shop_keeps_items_on_dedicated_pages():
    template = _read("app/templates/vendor/manage_shop.html")
    vendor_routes = _read("app/routes/vendor.py")

    assert "Locations de cette boutique" not in template
    assert "shop_locations" not in template
    assert "location_views_total" not in template
    assert "location_top" not in template
    assert "Ajouter une location" not in template
    assert "shop_locations=" not in vendor_routes
    assert "location_views_total=" not in vendor_routes
    assert "location_top=" not in vendor_routes
    assert "Mes locations" in template
    assert "Nouvelle location" in template


def test_vendor_manage_shop_uses_premium_compact_layout_without_losing_actions():
    template = _read("app/templates/vendor/manage_shop.html")
    css = _read("app/static/css/vendor/vendor_manage_shop_page.css")

    assert "vendor-premium-shell" in template
    assert "shop-command-bar" in template
    assert "premium-action-card" in template
    assert "premium-info-card" in template
    assert "premium-location-panel" in template
    assert "Modifier la boutique" in template
    assert "Voir ma boutique" in template
    assert "Désactiver" in template
    assert "Livre des encaissements" in template
    assert "Mes locations" in template
    assert "Nouvelle location" in template
    assert "Utiliser ma position" in template
    assert "Partager WhatsApp" in template
    assert ".vendor-premium-shell" in css
    assert ".shop-command-bar" in css
    assert ".premium-action-card" in css
    assert ".premium-location-panel" in css
    assert template.index("premium-info-card") < template.index("premium-action-card")
    assert "quick-action-chevron" in template
    assert "clip-path: polygon" in css
    assert "--chevron-cut" in css


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
    assert 'const title = "Bienvenue";' in script
    assert 'const message = "Ravi de vous revoir";' in script
    assert "showNativeWelcomeNotification" in script
    assert "registration.showNotification" in script
    assert "Notification.requestPermission" in script
    assert "navigator.vibrate" in script
    assert "sessionStorage" in script
    assert "bmClientWelcomeShown" in script
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


def test_vendor_dashboard_uses_compact_premium_daily_layout():
    template = _read("app/templates/vendor/dashboard.html")
    css = _read("app/static/css/vendor/vendor_dashboard.css")
    script = _read("app/static/js/pages/vendor/dashboard_page.js")

    assert "vendor-daily-dashboard" in template
    assert "daily-overview" in template
    assert "daily-kpis" in template
    assert "dashboardShopStatusBar" in template
    assert "daily-alerts-panel" in template
    assert "daily-all-clear" in template
    assert "daily-actions-grid" in template
    assert "vendorSoundPromptMount" in template
    assert template.index("daily-overview") < template.index("today-section")
    assert template.index("dashboardShopStatusBar") < template.index("today-section")
    assert template.index("recentOrdersList") > template.index("today-section")
    assert "À traiter maintenant" in template
    assert "Compact unified layout" not in css
    assert "Premium polish" not in css
    assert ".vendor-daily-dashboard" in css
    assert ".daily-overview" in css
    assert ".daily-kpis" in css
    assert ".daily-actions-grid" in css
    assert ".daily-all-clear" in css
    assert ".vendor-sound-prompt" in css
    assert "vendorSoundPromptMount" in script
    assert "document.body.appendChild(prompt)" not in script


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
    assert "Email *" in template
    assert 'name="email"' in template
    assert "Email (optionnel)" not in template
    assert "Validation admin avant activation." in template
    assert "Votre demande sera verifiee par un admin/gestionnaire" not in template


def test_vendor_access_backend_requires_email():
    source = _read("app/routes/auth.py")

    assert 'or not form_data["email"]' in source
    assert "Nom, telephone, email, boutique, ville et type sont obligatoires." in source
    assert "if not email_normalized:" in source


def test_admin_vendor_request_pages_use_plain_french_guidance():
    vendor_requests = _read("app/templates/admin/vendor_requests.html")
    change_requests = _read("app/templates/admin/vendor_change_requests.html")

    assert "Comptes clients recents" in vendor_requests
    assert "Cette page sert a suivre les nouveaux comptes crees depuis l'inscription publique." in vendor_requests
    assert "Les comptes vendeurs se creent maintenant directement." in vendor_requests
    assert "Clients inscrits" in vendor_requests
    assert "Voir le compte" in vendor_requests
    assert "Accepter et creer le compte vendeur" not in vendor_requests
    assert "Refuser cette demande" not in vendor_requests
    assert "Bloquer ce contact" not in vendor_requests

    assert "A faire maintenant" in change_requests
    assert "Ces vendeurs demandent une modification" in change_requests
    assert "Avant" in change_requests
    assert "Apres" in change_requests
    assert "Accepter la modification" in change_requests


def test_login_vendor_card_matches_current_vendor_request_workflow():
    template = _read("app/templates/auth/login.html")

    assert "Accès vendeur" in template
    assert "Creez votre espace vendeur et connectez-vous sans attendre une validation admin." in template
    assert "Creer un acces vendeur" in template
    assert "Continuer sans compte" in template
    assert "Comment ça marche" not in template
    assert "ouvrir WhatsApp" not in template
    assert "On vous crée un compte et on vous envoie vos identifiants" not in template


def test_vendor_access_form_is_compact_and_mobile_adaptive():
    template = _read("app/templates/auth/vendor_access.html")

    assert "max-width: 560px" in template
    assert "padding: clamp(0.9rem, 3vw, 1.45rem)" in template
    assert "overflow-x: clip" in template
    assert "max-width: 100%" in template
    assert "min-height: auto;" in template
    assert "min-height: 2.15rem" in template
    assert 'rows="2"' in template
    assert "Email *" in template
    assert 'name="email"' in template
    assert "Email (optionnel)" not in template
    assert "Creation immediate du compte et de la boutique." in template
    assert "Creer mon espace vendeur" in template
    assert "Validation admin avant activation." not in template
    assert "Votre demande sera verifiee par un admin/gestionnaire" not in template
