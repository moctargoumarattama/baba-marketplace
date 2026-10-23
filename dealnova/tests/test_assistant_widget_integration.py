from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_assistant_widget_is_wired_once_on_the_shared_public_home():
    home_template = (ROOT / "app/templates/home.html").read_text(encoding="utf-8-sig")
    partial = (ROOT / "app/templates/partials/_assistant_widget.html").read_text(
        encoding="utf-8-sig"
    )

    # Catalogue redirects are covered in test_public_hub_navigation.py; the
    # shared home owns the widget and must not initialize it multiple times.
    assert home_template.count('{% include "partials/_assistant_widget.html" %}') == 1
    assert home_template.count("css/assistant/widget.css") == 1
    assert home_template.count("js/assistant/widget.js") == 1
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
    # Inventory, visibility and complete journeys are exercised against SQLite
    # in test_assistant_flows.py, rather than checking removed internal fallbacks.
    assert "build_public_catalog" in engine_source
    assert "assistant_welcome" in routes_source
    assert "redirect_url" in engine_source
    assert "redirectIfNeeded" in widget_js_source
    assert "window.location.assign" in widget_js_source
    assert "response.redirect_url" in widget_js_source
    assert "list.slice(0, 8)" in widget_js_source


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
