from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_courier_blueprint_and_pages_are_removed():
    assert not (ROOT / "app/routes/courier.py").exists()
    assert not (ROOT / "app/templates/courier").exists()
    assert not (ROOT / "app/static/js/pages/courier_deliveries_page.js").exists()

    app_init = _read("app/__init__.py")
    assert "routes import" in app_init
    assert "courier" not in app_init
    assert 'register_blueprint(courier.bp)' not in app_init
    assert 'url_for("courier.' not in app_init


def test_courier_role_is_not_visible_or_routable():
    auth_source = _read("app/routes/auth.py")
    admin_users_source = _read("app/routes/admin_users.py")
    admin_base = _read("app/templates/admin/base.html")
    create_user = _read("app/templates/admin/create_user.html")
    users_filters = _read("app/templates/admin/partials/_users_filters.html")

    combined = "\n".join([auth_source, admin_users_source, admin_base, create_user, users_filters])
    forbidden = [
        'role == "courier"',
        "role='courier'",
        'role="courier"',
        'value="courier"',
        "Livreur",
        "livreur",
        "courier.",
        "/courier",
    ]
    for token in forbidden:
        assert token not in combined


def test_admin_delivery_has_no_courier_assignment_logic():
    admin_source = _read("app/routes/admin.py")
    for template in ("admin/deliveries.html", "admin/order_detail.html"):
        assert not (ROOT / "app/templates" / template).exists()
        assert template not in admin_source

    forbidden = [
        "assign_courier",
        "courier_whatsapp",
        "build_courier_whatsapp_message",
        "courier_id_filter",
        "courier_filters",
        "available_couriers",
        "courier_id",
        "courier.",
        "Livreur",
        "livreur",
        "Net livreur",
        '"assigned"',
        '"picked_up"',
        '"delivering"',
    ]
    for token in forbidden:
        assert token not in admin_source


def test_whatsapp_delivery_entry_point_and_admin_compatibility_remain():
    assert (ROOT / "app/templates/support/delivery_whatsapp_loader.html").exists()

    app_init = _read("app/__init__.py")
    shop_source = _read("app/routes/shop.py")
    admin_source = _read("app/routes/admin.py")

    assert 'register_blueprint(shop.bp, url_prefix="/shop")' in app_init
    assert '@bp.route("/delivery/whatsapp")' in shop_source
    assert "def delivery_whatsapp_loader():" in shop_source
    assert '@bp.route("/deliveries")' in admin_source
