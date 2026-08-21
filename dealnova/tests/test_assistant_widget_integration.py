from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_assistant_widget_is_wired_on_home_and_shop_home_pages():
    home_template = (ROOT / "app/templates/home.html").read_text(encoding="utf-8-sig")
    shop_home_template = (ROOT / "app/templates/shop/home.html").read_text(
        encoding="utf-8-sig"
    )
    partial = (ROOT / "app/templates/partials/_assistant_widget.html").read_text(
        encoding="utf-8-sig"
    )

    assert '{% include "partials/_assistant_widget.html" %}' in home_template
    assert '{% include "partials/_assistant_widget.html" %}' in shop_home_template
    assert "css/assistant/widget.css" in home_template
    assert "css/assistant/widget.css" in shop_home_template
    assert "js/assistant/widget.js" in home_template
    assert "js/assistant/widget.js" in shop_home_template
    assert "data-bootstrap-url" in partial
    assert "data-message-url" in partial


def test_assistant_api_blueprint_and_engine_exist():
    routes_source = (ROOT / "app/assistant/routes.py").read_text(encoding="utf-8-sig")
    engine_source = (ROOT / "app/assistant/engine.py").read_text(encoding="utf-8-sig")
    widget_js_source = (ROOT / "app/static/js/assistant/widget.js").read_text(
        encoding="utf-8-sig"
    )

    assert 'Blueprint("assistant_api"' in routes_source
    assert 'url_prefix="/api/assistant"' in routes_source
    assert "def assistant_bootstrap()" in engine_source
    assert "def assistant_reply(" in engine_source
    assert "find_products" in engine_source
    assert "find_services" in engine_source
    assert "find_locations" in engine_source
    assert "find_shops" in engine_source
    assert "help_delivery" in engine_source
    assert "FLOW_CATALOG" in engine_source
    assert "FLOW_DELIVERY" in engine_source
    assert "_search_products_or_services" in engine_source
    assert "_search_locations" in engine_source
    assert "SEMANTIC_PROFILES" in engine_source
    assert "coiffure" in engine_source
    assert "esthetique" in engine_source
    assert "electricite" in engine_source
    assert "electricien" in engine_source
    assert "appartement" in engine_source
    assert "studio" in engine_source
    assert "_search_catalog_via_existing_api" in engine_source
    assert "_search_shops_by_name" in engine_source
    assert 'url_for("shops.shop_detail"' in engine_source
    assert "search_public_products" in engine_source
    assert "search_public_locations" in engine_source
    assert "get_categories" in engine_source
    assert "_category_context_for_query" in engine_source
    assert "_category_alias_terms" in engine_source
    assert "LOCATION_CATEGORY_HINTS" in engine_source
    assert "Product.category_id.in_(category_ids)" in engine_source
    assert "Question livraison" not in engine_source
    assert "DELIVERY_SPEED_OPTIONS" not in engine_source
    assert "8h a 3h du matin" in engine_source
    assert "ASSISTANT_DELIVERY_HOURS_TEXT" in engine_source
    assert "def _is_yes_intent" in engine_source
    assert "def _is_no_intent" in engine_source
    assert "delivery_confirm" in engine_source
    assert "delivery_decline" in engine_source
    assert "oui/non" in engine_source
    assert "nom" in engine_source
    assert '"action": "become_vendor"' in engine_source
    assert 'url_for("auth.vendor_access")' in engine_source
    assert "redirect_url" in engine_source
    assert "redirectIfNeeded" in widget_js_source
    assert "window.location.assign" in widget_js_source
    assert "response.redirect_url" in widget_js_source
    assert "list.slice(0, 8)" in widget_js_source
    assert "_search_products_or_services(kind, [], budget_max_dh)" not in engine_source


def test_assistant_widget_mobile_keyboard_safety_hooks_exist():
    css_source = (ROOT / "app/static/css/assistant/widget.css").read_text(
        encoding="utf-8-sig"
    )
    js_source = (ROOT / "app/static/js/assistant/widget.js").read_text(
        encoding="utf-8-sig"
    )

    assert ".bm-assistant-form input" in css_source
    assert "font-size: 16px" in css_source
    assert "visualViewport" in js_source
    assert "bm-assistant-open" in js_source


def test_assistant_widget_is_floating_draggable_and_has_welcome_hint():
    partial = (ROOT / "app/templates/partials/_assistant_widget.html").read_text(
        encoding="utf-8-sig"
    )
    css_source = (ROOT / "app/static/css/assistant/widget.css").read_text(
        encoding="utf-8-sig"
    )
    js_source = (ROOT / "app/static/js/assistant/widget.js").read_text(
        encoding="utf-8-sig"
    )

    assert 'id="bmAssistantHint"' in partial
    assert "data-welcome-hint" in partial
    assert "POSITION_STORAGE_KEY" in js_source
    assert "pointerdown" in js_source
    assert "onDragMove" in js_source
    assert "showHintIfNeeded" in js_source
    assert "window.setTimeout(showHintIfNeeded" in js_source
    assert ".bm-assistant-hint" in css_source
    assert ".bm-assistant.is-dragging .bm-assistant-toggle" in css_source
