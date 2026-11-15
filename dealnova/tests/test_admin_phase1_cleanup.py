from pathlib import Path

from flask import session
from flask_login import login_user
import pytest

from dealnova.app import create_app
from dealnova.app.config import Config
from dealnova.app.extensions import db
from dealnova.app.models.blocked import BlockedContact
from dealnova.app.models.product import Product
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.routes import admin as admin_routes


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


@pytest.fixture()
def isolated_app(tmp_path):
    db_path = tmp_path / "phase1_cleanup.sqlite3"
    upload_dir = tmp_path / "uploads"
    backups_dir = tmp_path / "backups"
    upload_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    class Phase1TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path.as_posix()}"
        UPLOAD_FOLDER = str(upload_dir)
        MAINTENANCE_BACKUP_DIR = str(backups_dir)

    app = create_app(Phase1TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.engine.dispose()


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_phase1_dead_code_and_templates_cleaned():
    assert not (ROOT / "app/static/js/core/core_cart.js").exists()

    loader_client = _read("app/static/js/core/page_loader_client.js")
    assert "coreCart" not in loader_client
    assert "core_cart.js" not in loader_client

    core_live = _read("app/static/js/core/core_live.js")
    assert "initDeliveriesLive" not in core_live
    assert "BMCoreCart" not in core_live

    admin_table = _read("app/static/js/admin/admin_table.js")
    assert "initOrdersPage" not in admin_table
    assert "initDeliveriesPage" not in admin_table

    admin_components = _read("app/static/css/admin/admin_components.css")
    assert ".admin-order-toast" not in admin_components

    base_html = _read("app/templates/admin/base.html")
    for dead_token in (
        "data-notify-url",
        "data-notify-interval",
        "data-notify-pages",
        "adminOrderSoundToggle",
        "admin-order-toast",
    ):
        assert dead_token not in base_html
    assert "admin_users.vendor_change_requests" in base_html
    assert (
        "{% if current_user.role == 'admin' %}\n            <li class=\"nav-item\"><a class=\"nav-link {% if 'fraud' in ep %}"
        not in base_html
    )
    assert (
        "{% if current_user.role == 'admin' %}\n            <li class=\"nav-item\"><a class=\"nav-link {% if 'log' in ep %}"
        not in base_html
    )
    assert "admin.maintenance" in base_html

    dashboard_html = _read("app/templates/admin/dashboard.html")
    assert "Livraison et montants" not in dashboard_html
    assert "Livraison et part Baba" not in dashboard_html

    audience_html = _read("app/templates/admin/audience.html")
    assert "/admin/deliveries" not in audience_html

    vendor_order_detail = _read("app/templates/vendor/order_detail.html")
    assert "admin.mark_delivered" not in vendor_order_detail
    assert "Marquer livree" not in vendor_order_detail

    admin_py = _read("app/routes/admin.py")
    for removed in (
        "def mark_delivered(",
        "def cancel_order(",
        "def order_archives(",
        "def delete_archived_order(",
        "def deliveries_live(",
        "def deliveries_archives(",
        "def deliveries(",
        "def all_orders(",
        "def order_detail(",
        "def whatsapp_promo_send_test(",
    ):
        assert removed not in admin_py

    admin_users_py = _read("app/routes/admin_users.py")
    for removed in (
        "def create_shop(",
        "recent_users =",
        "recent_shops =",
        "MANAGER_BLOCKED_ENDPOINTS",
        "def restrict_sensitive_pages_for_manager(",
    ):
        assert removed not in admin_users_py


def test_restrict_admin_flashes_message_for_non_staff(isolated_app):
    with isolated_app.app_context():
        vendor = User(
            username="vnd_phase1",
            email="vnd_phase1@example.test",
            role="vendor",
            is_active=True,
        )
        vendor.set_password("SecretPass123!")
        db.session.add(vendor)
        db.session.commit()

        with isolated_app.test_request_context("/admin/pricing"):
            login_user(vendor)
            resp = admin_routes.restrict_admin()
            assert resp.status_code == 302
            assert resp.headers.get("Location", "").endswith("/")
            flashes = session.get("_flashes", [])
            assert ("danger", "Accès réservé aux administrateurs") in flashes


def test_manager_can_access_all_operational_pages_except_maintenance(isolated_app):
    with isolated_app.app_context():
        manager = User(
            username="mgr_phase1",
            email="mgr_phase1@example.test",
            role="manager",
            is_active=True,
        )
        manager.set_password("ManagerPass123!")
        db.session.add(manager)
        db.session.commit()
        manager_id = manager.id

    client = isolated_app.test_client()
    _login(client, manager_id)

    for path in (
        "/admin/",
        "/admin/audience",
        "/admin/audience/live",
        "/admin/fraud",
        "/admin/logs",
        "/admin/vendor-change-requests",
        "/admin/catalog-quality",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, f"Expected 200 on {path}, got {resp.status_code}"

    dashboard_html = client.get("/admin/").get_data(as_text=True)
    assert "Trafic live" in dashboard_html
    assert "Voir les logs" in dashboard_html
    assert "Demandes modifications" in dashboard_html
    assert "/admin/fraud" in dashboard_html
    assert "/admin/logs" in dashboard_html
    assert "/admin/audience" in dashboard_html
    assert "Maintenance systeme" not in dashboard_html

    # Manager can moderate fraud contacts
    block_resp = client.post(
        "/admin/fraud/block",
        data={"kind": "phone", "value": "0611223344", "reason": "Test fraude"},
        follow_redirects=False,
    )
    assert block_resp.status_code == 302
    with isolated_app.app_context():
        blocked = BlockedContact.query.filter_by(kind="phone", value="0611223344").first()
        assert blocked is not None
        assert blocked.is_active is True
        block_id = blocked.id

    unblock_resp = client.post(f"/admin/fraud/unblock/{block_id}", follow_redirects=False)
    assert unblock_resp.status_code == 302
    with isolated_app.app_context():
        blocked = db.session.get(BlockedContact, block_id)
        assert blocked is not None
        assert blocked.is_active is False

    # Manager remains blocked from technical maintenance & creating admin accounts
    assert client.get("/admin/maintenance").status_code == 302
    assert (
        client.post(
            "/admin/maintenance/backups/create",
            data={"backup_type": "database"},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        ).status_code
        == 403
    )
    assert client.get("/admin/user/create").status_code == 302


def test_catalog_quality_and_hide_out_of_stock_skip_services(isolated_app):
    with isolated_app.app_context():
        admin = User(
            username="adm_cat_phase1",
            email="adm_cat_phase1@example.test",
            role="admin",
            is_active=True,
        )
        admin.set_password("AdminPass123!")
        vendor = User(
            username="vnd_cat_phase1",
            email="vnd_cat_phase1@example.test",
            role="vendor",
            is_active=True,
        )
        vendor.set_password("VendorPass123!")
        db.session.add_all([admin, vendor])
        db.session.flush()

        shop = Shop(name="Shop Cat Phase 1", slug="shop-cat-phase1", vendor_id=vendor.id, is_active=True)
        db.session.add(shop)
        db.session.flush()

        physical_zero = Product(
            kind="physical",
            name="Produit Rupture Phase 1",
            description="En rupture",
            price=120.0,
            price_cents_value=12000,
            image_file="prod_zero.jpg",
            stock=0,
            is_active=True,
            vendor_id=vendor.id,
            shop_id=shop.id,
        )
        physical_in_stock = Product(
            kind="physical",
            name="Produit Disponible Phase 1",
            description="Disponible",
            price=150.0,
            price_cents_value=15000,
            image_file="prod_ok.jpg",
            stock=5,
            is_active=True,
            vendor_id=vendor.id,
            shop_id=shop.id,
        )
        service_offer = Product(
            kind="service",
            name="Plombier Express Phase 1",
            description="Service sans stock",
            price=200.0,
            price_cents_value=20000,
            image_file="service_ok.jpg",
            stock=0,
            is_active=True,
            vendor_id=vendor.id,
            shop_id=shop.id,
        )
        db.session.add_all([physical_zero, physical_in_stock, service_offer])
        db.session.commit()

        admin_id = admin.id
        phys_zero_id = physical_zero.id
        phys_ok_id = physical_in_stock.id
        service_id = service_offer.id

    client = isolated_app.test_client()
    _login(client, admin_id)

    filtered_html = client.get("/admin/catalog-quality?out_of_stock=1").get_data(as_text=True)
    assert "Produit Rupture Phase 1" in filtered_html
    assert "Plombier Express Phase 1" not in filtered_html
    assert '<div class="stat-value" id="countOut">1</div>' in filtered_html

    all_html = client.get("/admin/catalog-quality").get_data(as_text=True)
    assert '<span class="badge bg-secondary">Service</span>' in all_html

    hide_resp = client.post("/admin/catalog-quality/hide-out-of-stock", follow_redirects=False)
    assert hide_resp.status_code == 302

    with isolated_app.app_context():
        assert db.session.get(Product, phys_zero_id).is_active is False
        assert db.session.get(Product, phys_ok_id).is_active is True
        assert db.session.get(Product, service_id).is_active is True
