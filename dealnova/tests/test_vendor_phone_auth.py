import pytest
from unittest.mock import patch
from flask import url_for
from dealnova.app import create_app
from dealnova.app.extensions import db
from dealnova.app.models.user import User
from dealnova.app.models.shop import Shop
from dealnova.app.services.baba_whatsapp import normalize_whatsapp_number, build_vendor_welcome_message, send_whatsapp_message


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SERVER_NAME"] = "localhost"
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def test_normalize_whatsapp_number():
    assert normalize_whatsapp_number("0612345678") == "212612345678"
    assert normalize_whatsapp_number("0712345678") == "212712345678"
    assert normalize_whatsapp_number("+212 6 12 34 56 78") == "212612345678"
    assert normalize_whatsapp_number("06-12-34-56-78") == "212612345678"
    assert normalize_whatsapp_number("212612345678") == "212612345678"
    assert normalize_whatsapp_number("612345678") == "212612345678"
    assert normalize_whatsapp_number("") == ""


def test_build_vendor_welcome_message():
    msg = build_vendor_welcome_message(
        full_name="Youssef El Alami",
        shop_name="Épicerie Alami",
        phone="0612345678",
        login_url="https://www.babamarket.ma/login",
    )
    assert "Youssef El Alami" in msg
    assert "Épicerie Alami" in msg
    assert "0612345678" in msg
    assert "https://www.babamarket.ma/login" in msg
    assert "Baba Market" in msg


def test_send_whatsapp_message_handles_failure_gracefully(app):
    with app.app_context():
        # Port with nothing running to test connection error resilience
        res = send_whatsapp_message(
            phone="0612345678",
            message="Test message",
            gateway_url="http://127.0.0.1:59999/api/send",
            timeout=1,
        )
        assert res["sent"] is False
        assert res["phone"] == "212612345678"
        assert "wa_me_url" in res


def test_vendor_autonomous_registration_flow_no_email(app):
    import random
    test_phone = f"0699{random.randint(100000, 999999)}"
    client = app.test_client()

    # Mock the whatsapp gateway call so test doesn't depend on live external gateway
    with patch("dealnova.app.routes.auth.send_vendor_welcome_whatsapp") as mock_wa:
        mock_wa.return_value = {"sent": True, "method": "mock"}

        resp = client.post(
            "/vendor-access",
            data={
                "full_name": "Karim Bennani",
                "phone": test_phone,
                "city": "Rabat Agdal",
                "shop_name": "Tech Rabat",
                "shop_type": "products",
                "password": "Password1234!",
                "password_confirm": "Password1234!",
                "short_description": "Vente de matériel informatique",
            },
            follow_redirects=False,
        )
        # Should redirect directly to unified login
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")

        # Verify user and shop created in DB
        with app.app_context():
            user = User.query.filter_by(phone=test_phone).first()
            assert user is not None
            assert user.full_name == "Karim Bennani"
            assert user.role == "vendor"
            assert user.is_active is True
            assert user.check_password("Password1234!") is True

            shop = Shop.query.filter_by(vendor_id=user.id).first()
            assert shop is not None
            assert shop.name == "Tech Rabat"
            assert shop.is_active is True
            assert shop.primary_type == "products"

        # WhatsApp welcome was triggered with /login link
        mock_wa.assert_called_once()
        wa_args = mock_wa.call_args[1]
        assert wa_args["phone"] == test_phone
        assert wa_args["full_name"] == "Karim Bennani"
        assert wa_args["shop_name"] == "Tech Rabat"
        assert wa_args["login_url"].endswith("/login")


def test_vendor_login_with_phone_on_unified_page(app):
    phone_user = "0677112233"
    with app.app_context():
        user = User.query.filter_by(phone=phone_user).first()
        if not user:
            user = User(
                username="test_phone_vendor",
                email="vendor_0677112233@babamarket.ma",
                phone=phone_user,
                full_name="Fatima Zahra",
                role="vendor",
                is_active=True,
            )
            user.set_password("SecretPass123!")
            db.session.add(user)
            db.session.flush()

            shop = Shop(
                vendor_id=user.id,
                name="Boutique Fatima",
                slug="boutique-fatima-test",
                primary_type="products",
                is_active=True,
            )
            db.session.add(shop)
            db.session.commit()

    # 1. Login on unified /login with phone (0677112233)
    client1 = app.test_client()
    resp1 = client1.post(
        "/login",
        data={
            "email": "0677112233",
            "password": "SecretPass123!",
        },
        follow_redirects=False,
    )
    assert resp1.status_code == 302
    assert "/vendor/dashboard" in resp1.headers["Location"]

    # 2. Login on unified /login with international phone variation (+212 6 77 11 22 33)
    client2 = app.test_client()
    resp2 = client2.post(
        "/login",
        data={
            "email": "+212 6 77 11 22 33",
            "password": "SecretPass123!",
        },
        follow_redirects=False,
    )
    assert resp2.status_code == 302
    assert "/vendor/dashboard" in resp2.headers["Location"]

    # 3. Old /vendeur/login route redirects 301 to /login
    client_alias = app.test_client()
    resp_alias = client_alias.get("/vendeur/login", follow_redirects=False)
    assert resp_alias.status_code == 301
    assert resp_alias.headers["Location"].endswith("/login")

    # 4. Wrong password on unified /login fails
    client_bad = app.test_client()
    resp_bad = client_bad.post(
        "/login",
        data={
            "email": "0677112233",
            "password": "WrongPassword999",
        },
        follow_redirects=False,
    )
    assert resp_bad.status_code == 200
    assert "incorrect" in resp_bad.get_data(as_text=True).lower()


def test_admin_whatsapp_gateway_route_and_qr_rendering(app):
    from dealnova.app.services.baba_whatsapp import sanitize_whatsapp_qr_data_uri

    # Verify QR sanitizer blocks unsafe URIs and accepts valid PNG base64
    sample_qr = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    assert sanitize_whatsapp_qr_data_uri(sample_qr) == sample_qr
    assert sanitize_whatsapp_qr_data_uri("javascript:alert(1)") is None

    with app.app_context():
        admin_user = User.query.filter_by(username="wa_test_admin").first()
        if not admin_user:
            admin_user = User(
                username="wa_test_admin",
                email="wa_test_admin@babamarket.ma",
                role="admin",
                is_active=True,
            )
            admin_user.set_password("AdminPass123!")
            db.session.add(admin_user)

        manager_user = User.query.filter_by(username="wa_test_manager").first()
        if not manager_user:
            manager_user = User(
                username="wa_test_manager",
                email="wa_test_manager@babamarket.ma",
                role="manager",
                is_active=True,
            )
            manager_user.set_password("ManagerPass123!")
            db.session.add(manager_user)
        db.session.commit()
        admin_id = admin_user.id
        manager_id = manager_user.id

    # 1. Manager should be blocked from /admin/whatsapp-gateway
    mgr_client = app.test_client()
    with mgr_client.session_transaction() as sess:
        sess["_user_id"] = str(manager_id)
        sess["_fresh"] = True
    mgr_resp = mgr_client.get("/admin/whatsapp-gateway", follow_redirects=False)
    assert mgr_resp.status_code in (302, 403)

    # 2. Admin can access /admin/whatsapp-gateway when qr_ready and sees the QR image
    adm_client = app.test_client()
    with adm_client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    with patch("dealnova.app.routes.admin.get_whatsapp_gateway_status") as mock_status:
        mock_status.return_value = {
            "status": "qr_ready",
            "status_label": "En attente de scan",
            "qr": sample_qr,
            "reachable": True,
            "status_code": 200,
            "status_url": "http://127.0.0.1:3002/api/status",
            "checked_at": "18/10/2026 21:30:00 UTC",
            "error": None,
        }
        resp_qr = adm_client.get("/admin/whatsapp-gateway")
        assert resp_qr.status_code == 200
        html = resp_qr.get_data(as_text=True)
        assert "En attente de scan" in html
        assert sample_qr in html
        assert "Rafraîchir le statut" in html

        # JSON refresh check
        resp_json = adm_client.get("/admin/whatsapp-gateway?format=json")
        assert resp_json.status_code == 200
        payload = resp_json.get_json()
        assert payload["status"] == "qr_ready"
        assert payload["qr"] == sample_qr

