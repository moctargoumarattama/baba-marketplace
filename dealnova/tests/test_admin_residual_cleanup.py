from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from dealnova.app import create_app
from dealnova.app.config import Config
from dealnova.app.extensions import db
from dealnova.app.models.blocked import BlockedContact
from dealnova.app.models.platform_settings import PlatformSettings
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.routes import admin, auth
from dealnova.app.services.migration import ensure_platform_settings_columns


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8-sig")


@pytest.fixture()
def residual_app(tmp_path):
    db_path = tmp_path / "residual.sqlite3"
    upload_dir = tmp_path / "uploads"
    backups_dir = tmp_path / "backups"
    upload_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    class ResidualTestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SECURITY_RATE_LIMIT_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path.as_posix()}"
        UPLOAD_FOLDER = str(upload_dir)
        MAINTENANCE_BACKUP_DIR = str(backups_dir)

    app = create_app(ResidualTestConfig)
    with app.app_context():
        db.create_all()
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()


def _login(client, user_id: int):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_legacy_files_models_and_column_are_removed():
    assert not (ROOT / "app/models/vendor_application.py").exists()
    assert not (ROOT / "app/templates/admin/vendor_requests.html").exists()
    assert (ROOT / "app/templates/admin/customers.html").exists()
    assert not hasattr(PlatformSettings, "seller_commission_percent")

    models_init = _read("app/models/__init__.py")
    assert "VendorApplication" not in models_init

    migration_py = _read("app/services/migration.py")
    assert "ensure_vendor_application_table" not in migration_py
    assert "seller_commission_percent" in migration_py

    app_init = _read("app/__init__.py")
    assert "ensure_vendor_application_table" not in app_init

    whatsapp_promo = _read("app/services/whatsapp_promo.py")
    assert "VendorApplication" not in whatsapp_promo


def test_legacy_admin_redirects_return_404_and_customers_page_works(residual_app):
    with residual_app.app_context():
        admin_user = User(username="adm_res", email="adm_res@example.test", role="admin", is_active=True)
        admin_user.set_password("AdminPass123!")
        mgr_user = User(username="mgr_res", email="mgr_res@example.test", role="manager", is_active=True)
        mgr_user.set_password("ManagerPass123!")
        customer = User(
            username="cust_res",
            email="cust_res@example.test",
            role="customer",
            full_name="Ancien Client",
            phone="0611002200",
            is_active=True,
        )
        customer.set_password("CustomerPass123!")
        db.session.add_all([admin_user, mgr_user, customer])
        db.session.commit()
        admin_id, mgr_id, cust_id = admin_user.id, mgr_user.id, customer.id

    client = residual_app.test_client()
    _login(client, admin_id)

    for removed_path in ("/admin/deliveries", "/admin/orders", "/admin/order/1", "/admin/vendor-requests"):
        assert client.get(removed_path).status_code == 404

    for uid in (admin_id, mgr_id):
        _login(client, uid)
        resp = client.get("/admin/customers")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Ancien Client" in html
        assert f"/admin/user/{cust_id}" in html

        detail = client.get(f"/admin/user/{cust_id}")
        assert detail.status_code == 200
        detail_html = detail.get_data(as_text=True)
        assert "Ancien Client" in detail_html
        assert "Client" in detail_html


def test_manager_can_manage_whatsapp_gateway_and_delete_shop_only_blocked_on_maintenance(residual_app, monkeypatch):
    with residual_app.app_context():
        mgr = User(username="mgr_full", email="mgr_full@example.test", role="manager", is_active=True)
        mgr.set_password("ManagerPass123!")
        vendor = User(username="vnd_del", email="vnd_del@example.test", role="vendor", is_active=True)
        vendor.set_password("VendorPass123!")
        db.session.add_all([mgr, vendor])
        db.session.flush()
        shop = Shop(vendor_id=vendor.id, name="Boutique Test", slug="boutique-test", is_active=True)
        db.session.add(shop)
        db.session.commit()
        mgr_id, vendor_id, shop_id = mgr.id, vendor.id, shop.id

    monkeypatch.setattr(admin, "get_whatsapp_gateway_status", lambda: {"status": "connected", "connected": True, "qr": None})
    monkeypatch.setattr(admin, "reconnect_whatsapp_gateway", lambda: {"success": True, "message": "QR ok"})
    monkeypatch.setattr(admin, "disconnect_whatsapp_gateway", lambda: {"success": True, "message": "Disconnected"})
    monkeypatch.setattr(
        admin,
        "test_whatsapp_tunnel_and_reception",
        lambda fallback_phone=None: {"success": True, "tunnel_ok": True, "message": "Tunnel OK"},
    )
    monkeypatch.setattr(
        "dealnova.app.services.whatsapp_promo.get_settings",
        lambda: {"groups": [], "admin_phone": "", "pinned_product_ids": []},
    )
    monkeypatch.setattr(
        "dealnova.app.services.whatsapp_promo.get_log",
        lambda: {"recent_logs": []},
    )
    monkeypatch.setattr(
        "dealnova.app.services.whatsapp_promo.get_wave_info",
        lambda *a, **kw: {"is_sending": False, "active_send": None, "wave_number": 1, "wave_title": "V1", "runs_today": 0},
    )
    monkeypatch.setattr("dealnova.app.services.whatsapp_promo.ensure_current_wave_preview", lambda **kw: {"source": "cache", "items": []})
    monkeypatch.setattr("dealnova.app.services.whatsapp_promo.get_today_clicks", lambda: {})
    monkeypatch.setattr("dealnova.app.services.whatsapp_promo.groups_to_text", lambda g: "")

    client = residual_app.test_client()
    _login(client, mgr_id)

    assert client.get("/admin/whatsapp-gateway").status_code == 200
    assert client.post("/admin/whatsapp-gateway/reconnect", headers={"X-Requested-With": "XMLHttpRequest"}).json["success"] is True
    assert client.post("/admin/whatsapp-gateway/test-tunnel", headers={"X-Requested-With": "XMLHttpRequest"}).json["success"] is True
    assert client.post("/admin/whatsapp-gateway/disconnect", headers={"X-Requested-With": "XMLHttpRequest"}).json["success"] is True

    del_resp = client.post(
        f"/admin/shop/{shop_id}/delete",
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json["success"] is True
    assert del_resp.json["vendor_user_deleted"] is True
    with residual_app.app_context():
        assert db.session.get(Shop, shop_id) is None
        assert db.session.get(User, vendor_id) is None

    # Only /admin/maintenance remains strictly blocked for manager
    assert client.get("/admin/maintenance").status_code == 302
    assert (
        client.post(
            "/admin/maintenance/mode/enable",
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        ).status_code
        == 403
    )


def test_vendor_access_uses_blocked_contact_without_vendor_application_and_migration_cleans_legacy_column(residual_app, monkeypatch):
    with residual_app.app_context():
        db.session.add(BlockedContact(kind="phone", value="0612345678", reason="Spam", is_active=True))
        db.session.commit()

    monkeypatch.setattr(auth, "send_vendor_welcome_whatsapp", lambda **kw: {"sent": False, "method": "skip"})
    monkeypatch.setattr(auth, "log_access", lambda *a, **kw: None)
    monkeypatch.setattr(auth.logging_service, "log_activity", lambda *a, **kw: None)
    monkeypatch.setattr(auth, "render_template", lambda tpl, **kw: f"tpl:{tpl}", raising=True)

    client = residual_app.test_client()
    blocked_resp = client.post(
        "/vendor-access",
        data={
            "full_name": "Blocked Vendor",
            "phone": "06 12 34 56 78",
            "city": "Rabat",
            "shop_name": "Blocked Shop",
            "shop_type": "products",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
        },
        follow_redirects=False,
    )
    assert blocked_resp.status_code == 200
    with residual_app.app_context():
        assert Shop.query.filter_by(name="Blocked Shop").first() is None

    ok_resp = client.post(
        "/vendor-access",
        data={
            "full_name": "Valid Vendor",
            "phone": "0699887766",
            "city": "Rabat",
            "shop_name": "Valid Shop",
            "shop_type": "products",
            "password": "StrongPassword123!",
            "password_confirm": "StrongPassword123!",
        },
        follow_redirects=False,
    )
    assert ok_resp.status_code == 302
    with residual_app.app_context():
        assert Shop.query.filter_by(name="Valid Shop").first() is not None

        # Simulate legacy DB still having seller_commission_percent column and verify migration removes it
        db.session.execute(
            text('ALTER TABLE "platform_settings" ADD COLUMN seller_commission_percent FLOAT NOT NULL DEFAULT 10.0')
        )
        db.session.commit()
        assert any(c["name"] == "seller_commission_percent" for c in inspect(db.engine).get_columns("platform_settings"))
        ensure_platform_settings_columns()
        assert not any(c["name"] == "seller_commission_percent" for c in inspect(db.engine).get_columns("platform_settings"))
        assert PlatformSettings.get() is not None


def test_shared_admin_rbac_module_is_used_across_all_admin_blueprints(residual_app):
    admin_py = _read("app/routes/admin.py")
    admin_users_py = _read("app/routes/admin_users.py")
    admin_categories_py = _read("app/routes/admin_categories.py")
    rentals_py = _read("app/routes/rentals.py")

    for src in (admin_py, admin_users_py, admin_categories_py, rentals_py):
        assert "admin_rbac" in src
        assert "def _current_admin_role(" not in src
        assert "def _is_manager(" not in src
        assert "def _is_manager_user(" not in src
        assert "def _is_full_admin(" not in src
        assert "def _is_ajax_request(" not in src

    with residual_app.app_context():
        vendor = User(username="vnd_rbac", email="vnd_rbac@example.test", role="vendor", is_active=True)
        vendor.set_password("VendorPass123!")
        mgr = User(username="mgr_rbac", email="mgr_rbac@example.test", role="manager", is_active=True)
        mgr.set_password("ManagerPass123!")
        db.session.add_all([vendor, mgr])
        db.session.commit()
        vendor_id, mgr_id = vendor.id, mgr.id

    client = residual_app.test_client()
    _login(client, vendor_id)
    for protected_url in ("/admin/categories/", "/admin/locations", "/admin/pricing", "/admin/users"):
        assert client.get(protected_url, follow_redirects=False).status_code == 302

    _login(client, mgr_id)
    for operational_url in ("/admin/categories/", "/admin/locations", "/admin/pricing", "/admin/users"):
        resp = client.get(operational_url, follow_redirects=False)
        assert resp.status_code == 200, f"{operational_url} -> {resp.status_code} {resp.headers.get('Location')}"
    assert client.get("/admin/maintenance", follow_redirects=False).status_code == 302


def test_dashboard_whatsapp_gateway_disconnected_alert(residual_app, monkeypatch):
    from dealnova.app.routes import admin_users

    with residual_app.app_context():
        mgr = User(username="mgr_wa_alert", email="mgr_wa_alert@example.test", role="manager", is_active=True)
        mgr.set_password("ManagerPass123!")
        db.session.add(mgr)
        db.session.commit()
        mgr_id = mgr.id

    client = residual_app.test_client()
    _login(client, mgr_id)

    monkeypatch.setattr(
        admin_users,
        "get_whatsapp_gateway_status",
        lambda: {"status": "disconnected", "reachable": False},
    )
    html_disc = client.get("/admin/").get_data(as_text=True)
    assert "Passerelle WhatsApp déconnectée" in html_disc
    assert "Reconnecter" in html_disc
    assert "/admin/whatsapp-gateway" in html_disc

    monkeypatch.setattr(
        admin_users,
        "get_whatsapp_gateway_status",
        lambda: {"status": "qr_ready", "reachable": True},
    )
    html_qr = client.get("/admin/").get_data(as_text=True)
    assert "Passerelle WhatsApp en attente de scan QR" in html_qr
    assert "Scanner le QR" in html_qr

    monkeypatch.setattr(
        admin_users,
        "get_whatsapp_gateway_status",
        lambda: {"status": "connected", "reachable": True},
    )
    html_ok = client.get("/admin/").get_data(as_text=True)
    assert "Passerelle WhatsApp déconnectée" not in html_ok
    assert "Passerelle WhatsApp en attente de scan QR" not in html_ok
