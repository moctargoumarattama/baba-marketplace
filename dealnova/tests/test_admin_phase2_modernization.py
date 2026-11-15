from datetime import datetime, timedelta
from pathlib import Path

from dealnova.app import create_app
from dealnova.app.config import Config
from dealnova.app.extensions import db
from dealnova.app.models.audit import AuditLog
from dealnova.app.models.blocked import BlockedContact
from dealnova.app.models.booking import Booking
from dealnova.app.models.financial import FinancialEntry
from dealnova.app.services.finance_entries import (
    ENTRY_TYPE_RENTAL_COMMISSION,
    ENTRY_TYPE_SUBSCRIPTION,
)
from dealnova.app.models.product import Product
from dealnova.app.models.product_contact_lead import ProductContactLead
from dealnova.app.models.promo import Promo
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.services.admin_tools import csv_download_response, invalidate_admin_sidebar_badges

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def phase2_app(tmp_path):
    db_path = tmp_path / "phase2_modernization.sqlite3"
    upload_dir = tmp_path / "uploads"
    backups_dir = tmp_path / "backups"
    upload_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    class Phase2Config(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path.as_posix()}"
        UPLOAD_FOLDER = str(upload_dir)
        MAINTENANCE_BACKUP_DIR = str(backups_dir)

    app = create_app(Phase2Config)
    with app.app_context():
        db.create_all()
        invalidate_admin_sidebar_badges()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _seed_core_data():
    admin = User(
        username="adm_phase2",
        email="adm_phase2@example.test",
        full_name="Admin Phase 2",
        role="admin",
        is_active=True,
    )
    admin.set_password("AdminPass123!")

    manager = User(
        username="mgr_phase2",
        email="mgr_phase2@example.test",
        full_name="Manager Phase 2",
        role="manager",
        is_active=True,
    )
    manager.set_password("ManagerPass123!")

    vendor = User(
        username="vnd_phase2",
        email="vnd_phase2@example.test",
        full_name="=CMD|'/C calc'!A0",
        phone="0611223344",
        role="vendor",
        is_active=True,
        subscription_expires_at=datetime.utcnow() + timedelta(days=3),
    )
    vendor.set_password("VendorPass123!")
    db.session.add_all([admin, manager, vendor])
    db.session.flush()

    shop = Shop(
        name="AtelierAtlas",
        slug="atelier-atlas",
        address="Casablanca Maarif",
        contact_phone="0611223344",
        vendor_id=vendor.id,
        is_active=True,
    )
    db.session.add(shop)
    db.session.flush()

    product = Product(
        kind="physical",
        name="Perceuse Pro 18V",
        description="Sans fil",
        price=499.0,
        price_cents_value=49900,
        image_file="perceuse.jpg",
        stock=10,
        is_active=True,
        vendor_id=vendor.id,
        shop_id=shop.id,
    )
    service = Product(
        kind="service",
        name="Depannage Electrique",
        description="Intervention rapide",
        price=250.0,
        price_cents_value=25000,
        image_file="service.jpg",
        stock=0,
        is_active=True,
        vendor_id=vendor.id,
        shop_id=shop.id,
    )
    db.session.add_all([product, service])
    db.session.flush()
    return admin, manager, vendor, shop, product, service


def test_csv_formula_neutralization():
    resp = csv_download_response(
        "test_export",
        ["ColA", "ColB"],
        [["=1+1", "@SUM(A1:A2)"], ["+cmd", "-calc"], ["normal", "text"]],
    )
    body = resp.get_data(as_text=True)
    assert body.startswith("\ufeff")
    assert "'=1+1" in body
    assert "'@SUM(A1:A2)" in body
    assert "'+cmd" in body
    assert "'-calc" in body
    assert "text/csv" in resp.content_type


def test_admin_bookings_view_status_and_csv_export(phase2_app):
    with phase2_app.app_context():
        admin, manager, _vendor, shop, _product, service = _seed_core_data()
        b1 = Booking(
            product_id=service.id,
            shop_id=shop.id,
            full_name="=HYPERLINK(\"http://evil\",\"Client\")",
            phone="0661000011",
            phone_digits="0661000011",
            booking_ip="10.0.0.5",
            note="Besoin urgent demain matin",
            status="pending",
        )
        db.session.add(b1)
        db.session.commit()
        admin_id, manager_id, booking_id = admin.id, manager.id, b1.id

    # Use isolated test clients per role (clean separate sessions/cookie jars)
    for uid in (manager_id, admin_id):
        role_client = phase2_app.test_client()
        _login(role_client, uid)
        page_resp = role_client.get("/admin/bookings")
        assert page_resp.status_code == 200
        html = page_resp.get_data(as_text=True)
        assert "Suivi des réservations de services" in html
        assert "0661000011" in html
        assert "Depannage Electrique" in html

    client = phase2_app.test_client()
    _login(client, manager_id)
    update_resp = client.post(
        f"/admin/bookings/{booking_id}/status",
        data={"status": "confirmed"},
        follow_redirects=False,
    )
    assert update_resp.status_code == 302

    with phase2_app.app_context():
        assert db.session.get(Booking, booking_id).status == "confirmed"

    csv_resp = client.get("/admin/bookings/export.csv")
    assert csv_resp.status_code == 200
    csv_text = csv_resp.get_data(as_text=True)
    assert "'=HYPERLINK" in csv_text
    assert "Depannage Electrique" in csv_text


def test_fraud_monitor_bookings_leads_and_manual_block_unblock(phase2_app):
    with phase2_app.app_context():
        _admin, manager, _vendor, shop, product, service = _seed_core_data()
        now = datetime.utcnow()

        # Suspicious booking + phone spike (threshold=3)
        for idx in range(3):
            db.session.add(
                Booking(
                    product_id=service.id,
                    shop_id=shop.id,
                    full_name="xx",
                    phone="0699887766",
                    phone_digits="0699887766",
                    booking_ip="172.16.0.9",
                    note="test spam",
                    status="pending",
                    created_at=now - timedelta(minutes=idx * 5),
                )
            )
        # ProductContactLead spike
        import json
        for idx in range(3):
            db.session.add(
                ProductContactLead(
                    source="product_whatsapp",
                    shop_id=shop.id,
                    client_name="Client WA",
                    client_phone="0655443322",
                    whatsapp_phone="0611223344",
                    product_summary_json=json.dumps([{"product_id": product.id, "product_name": product.name, "quantity": 1}]),
                    estimated_total=49900,
                    created_at=now - timedelta(minutes=idx * 4),
                )
            )
        db.session.commit()
        manager_id = manager.id

    client = phase2_app.test_client()
    _login(client, manager_id)

    resp = client.get("/admin/fraud?threshold=3&limit_1h=3&addr_min_len=4")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Contacts WhatsApp Produits" in html
    assert "Réservations Services" in html
    assert "0699887766" in html
    assert "0655443322" in html
    assert "172.16.0.9" in html
    assert "test spam" in html

    block_resp = client.post(
        "/admin/fraud/block",
        data={"kind": "phone", "value": "0655-443322", "reason": "Spam WhatsApp"},
        follow_redirects=False,
    )
    assert block_resp.status_code == 302

    with phase2_app.app_context():
        blocked = BlockedContact.query.filter_by(kind="phone", value="0655443322", is_active=True).first()
        assert blocked is not None
        blocked_id = blocked.id

    after_block_html = client.get("/admin/fraud").get_data(as_text=True)
    assert "Spam WhatsApp" in after_block_html

    unblock_resp = client.post(f"/admin/fraud/unblock/{blocked_id}", follow_redirects=False)
    assert unblock_resp.status_code == 302
    with phase2_app.app_context():
        assert db.session.get(BlockedContact, blocked_id).is_active is False


def test_promo_bulk_actions_and_csv_exports_rbac(phase2_app):
    with phase2_app.app_context():
        admin, manager, vendor, shop, product, _service = _seed_core_data()
        p1 = Promo(
            product_id=product.id,
            type="percentage",
            value=15.0,
            end_date=datetime.utcnow() + timedelta(days=5),
            status=Promo.STATUS_PENDING,
        )
        p2 = Promo(
            product_id=product.id,
            type="fixed",
            value=50.0,
            end_date=datetime.utcnow() + timedelta(days=5),
            status=Promo.STATUS_PENDING,
        )
        db.session.add_all([p1, p2])
        db.session.add(
            FinancialEntry(
                entry_type=ENTRY_TYPE_SUBSCRIPTION,
                amount_cents=15000,
                note="=Abonnement",
            )
        )
        db.session.add(
            FinancialEntry(
                entry_type=ENTRY_TYPE_RENTAL_COMMISSION,
                amount_cents=8000,
                note="Location outil",
            )
        )
        import json
        db.session.add(
            ProductContactLead(
                source="product_whatsapp",
                shop_id=shop.id,
                client_name="Client Export",
                client_phone="0612001122",
                whatsapp_phone="0611223344",
                product_summary_json=json.dumps([{"product_id": product.id, "product_name": product.name, "quantity": 2}]),
                estimated_total=99800,
            )
        )
        db.session.commit()
        admin_id, manager_id = admin.id, manager.id
        promo_ids = [str(p1.id), str(p2.id)]

    client = phase2_app.test_client()
    _login(client, manager_id)

    # Bulk reject then bulk approve
    bulk_reject = client.post(
        "/admin/promotions/bulk",
        data={"bulk_action": "reject", "promo_ids": [promo_ids[0]], "review_note": "Visuel flou", "status": "pending"},
        follow_redirects=False,
    )
    assert bulk_reject.status_code == 302
    with phase2_app.app_context():
        assert db.session.get(Promo, int(promo_ids[0])).status == Promo.STATUS_REJECTED
        assert db.session.get(Promo, int(promo_ids[0])).review_note == "Visuel flou"

    bulk_approve = client.post(
        "/admin/promotions/bulk",
        data={"bulk_action": "approve", "promo_ids": promo_ids, "status": "pending"},
        follow_redirects=False,
    )
    assert bulk_approve.status_code == 302
    with phase2_app.app_context():
        for pid in promo_ids:
            assert db.session.get(Promo, int(pid)).status == Promo.STATUS_APPROVED

    # CSV exports for manager: users CSV hides admin/manager!
    users_csv_mgr = client.get("/admin/users/export.csv").get_data(as_text=True)
    assert "vnd_phase2" in users_csv_mgr
    assert "'=CMD" in users_csv_mgr
    assert "adm_phase2" not in users_csv_mgr
    assert "mgr_phase2" not in users_csv_mgr

    finance_csv = client.get("/admin/finance/export.csv").get_data(as_text=True)
    assert "'=Abonnement" in finance_csv
    assert "Commission location" in finance_csv

    pc_csv = client.get("/admin/product-contacts/export.csv").get_data(as_text=True)
    assert "Client Export" in pc_csv
    assert "Perceuse Pro 18V" in pc_csv

    rec_csv = client.get("/admin/reconciliation/export.csv").get_data(as_text=True)
    assert "vnd_phase2" in rec_csv

    # Admin users CSV includes admin and manager
    adm_client = phase2_app.test_client()
    _login(adm_client, admin_id)
    users_csv_adm = adm_client.get("/admin/users/export.csv").get_data(as_text=True)
    assert "adm_phase2" in users_csv_adm
    assert "mgr_phase2" in users_csv_adm


def test_quick_search_dashboard_alerts_logs_summary_and_public_safety(phase2_app):
    with phase2_app.app_context():
        admin, manager, _vendor, shop, product, service = _seed_core_data()
        db.session.add(
            Promo(
                product_id=product.id,
                type="percentage",
                value=10.0,
                end_date=datetime.utcnow() + timedelta(days=3),
                status=Promo.STATUS_PENDING,
            )
        )
        db.session.add(
            Booking(
                product_id=service.id,
                shop_id=shop.id,
                full_name="Samira Test",
                phone="0644112233",
                phone_digits="0644112233",
                status="pending",
            )
        )
        db.session.add(
            AuditLog(
                user_id=admin.id,
                action="deletion_snapshot",
                entity_type="shop",
                entity_id=shop.id,
                changes={"label": "Ancienne Boutique", "reason": "Doublon"},
            )
        )
        db.session.commit()
        admin_id, manager_id = admin.id, manager.id

    pub_client = phase2_app.test_client()

    # Public route works safely without touching admin badge context processor
    pub_resp = pub_client.get("/")
    assert pub_resp.status_code == 200

    # Manager quick-search hides technical maintenance & admin accounts
    mgr_client = phase2_app.test_client()
    _login(mgr_client, manager_id)
    qs_mgr_resp = mgr_client.get("/admin/quick-search?q=adm_phase2")
    assert qs_mgr_resp.status_code == 200, (
        qs_mgr_resp.status_code,
        qs_mgr_resp.headers.get("Location"),
        qs_mgr_resp.get_data(as_text=True)[:400],
    )
    qs_mgr = qs_mgr_resp.get_json()
    assert qs_mgr["success"] is True
    assert all(u["name"] != "adm_phase2" for u in qs_mgr["users"])
    qs_mgr_maint = mgr_client.get("/admin/quick-search?q=maintenance").get_json()
    assert all("/admin/maintenance" not in p["url"] for p in qs_mgr_maint["pages"])
    qs_mgr_shop = mgr_client.get("/admin/quick-search?q=AtelierAtlas").get_json()
    assert any(s["name"] == "AtelierAtlas" for s in qs_mgr_shop["shops"])

    # Admin sees admin account & maintenance page
    adm_client = phase2_app.test_client()
    _login(adm_client, admin_id)
    qs_adm = adm_client.get("/admin/quick-search?q=adm_phase2").get_json()
    assert any(u["name"] == "Admin Phase 2" or u["name"] == "adm_phase2" for u in qs_adm["users"])
    qs_adm_maint = adm_client.get("/admin/quick-search?q=maintenance").get_json()
    assert any("/admin/maintenance" in p["url"] for p in qs_adm_maint["pages"])

    # Dashboard displays 5-pole sidebar badges, alerts & 7-day chart
    dash_html = adm_client.get("/admin/").get_data(as_text=True)
    assert "Pilotage" in dash_html
    assert "Vendeurs &amp; Clients" in dash_html or "Vendeurs & Clients" in dash_html
    assert "Activité des 7 derniers jours" in dash_html
    assert "promotion(s) en attente" in dash_html
    assert "reservation(s) de service en attente" in dash_html
    assert 'id="adminQuickSearchBtn"' in dash_html
    assert "Cliquez ou Ctrl+K" in dash_html
    assert "Astuce : cliquez ici ou faites" in dash_html

    # Logs page unifies human-readable summary & deletion_snapshot filter
    logs_html = adm_client.get("/admin/logs?audit_action=deletion_snapshot").get_data(as_text=True)
    assert "Détail lisible" in logs_html
    assert "Suppressions (1)" in logs_html
    assert "Archive de suppression" in logs_html
    assert "Ancienne Boutique" in logs_html
