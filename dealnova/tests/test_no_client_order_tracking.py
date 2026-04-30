from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_client_order_tracking_routes_are_removed_from_cart_and_shop():
    cart_source = _read("app/routes/cart.py")
    shop_source = _read("app/routes/shop.py")
    combined = "\n".join([cart_source, shop_source])

    forbidden = [
        '@bp.route("/suivi"',
        '@bp.route("/mes-commandes"',
        '@bp.route("/track/<token>"',
        '@bp.route("/track/<token>/status"',
        "def track_by_phone",
        "def my_orders",
        "def track_status",
        "def track(token)",
        "def track_order",
        "cart.my_orders",
        "cart.track_by_phone",
        "shop.track_order",
    ]
    for token in forbidden:
        assert token not in combined


def test_client_order_tracking_templates_and_js_are_removed():
    removed_paths = [
        "app/templates/cart/my_orders.html",
        "app/templates/cart/track_phone.html",
        "app/templates/cart/track_verify_phone.html",
        "app/templates/shop/track_order.html",
        "app/static/js/pages/my_orders_page.js",
        "app/static/js/pages/track_order_page.js",
        "app/static/js/pages/track_phone_page.js",
        "app/static/js/pages/track_verify_phone_page.js",
        "app/static/css/pages/my_orders_page.css",
    ]
    for relative in removed_paths:
        assert not (ROOT / relative).exists(), relative


def test_public_ui_has_no_client_order_tracking_links_or_copy():
    files = [
        "app/templates/base.html",
        "app/static/js/ui_shell.js",
        "app/static/js/core/page_loader.js",
        "app/static/sw.js",
    ]
    combined = "\n".join(_read(path) for path in files)

    forbidden = [
        "Mes commandes",
        "Suivi commande",
        "Suivre ma commande",
        "Voir le suivi",
        "/cart/mes-commandes",
        "/cart/suivi",
        "/shop/suivi",
        "cart.my_orders",
        "cart.track_verify_phone",
        "shop.track_order",
        "track_order_page.js",
        "track_phone_page.js",
        "track_verify_phone_page.js",
        "my_orders_page.js",
    ]
    for token in forbidden:
        assert token not in combined


def test_whatsapp_cart_and_delivery_entry_points_remain():
    app_init = _read("app/__init__.py")
    cart_source = _read("app/routes/cart.py")
    delivery_source = _read("app/routes/delivery.py")

    assert "register_blueprint(cart.bp)" in app_init
    assert "register_blueprint(delivery.bp)" in app_init
    assert '@bp.route("/")' in cart_source
    assert '@bp.route("/checkout", methods=["GET", "POST"])' in cart_source
    assert '@bp.route("/whatsapp", methods=["POST"])' in cart_source
    assert "cart/vendor_whatsapp_checkout.html" in cart_source
    assert "ProductContactLead" in cart_source
    assert 'Blueprint("delivery_special"' in delivery_source
