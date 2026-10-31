"""Tests unitaires et d'intégration pour l'automatisation promotionnelle WhatsApp."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from PIL import Image
import pytest

from dealnova.app import create_app
from dealnova.app.extensions import db
from dealnova.app.models.product import Product
from dealnova.app.models.promo import Promo
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.services import whatsapp_promo


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SERVER_NAME"] = "localhost"
    yield app



def _seed_catalog(app, tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)

    Image.new("RGB", (400, 400), (20, 140, 80)).save(upload_dir / "prod_promo.jpg")
    Image.new("RGB", (400, 400), (140, 80, 20)).save(upload_dir / "prod_std.jpg")
    Image.new("RGB", (400, 400), (80, 20, 140)).save(upload_dir / "prod_out.jpg")

    with app.app_context():
        vendor = User.query.filter_by(username="wa_promo_vendor").first()
        if not vendor:
            vendor = User(
                username="wa_promo_vendor",
                email="wa_promo_vendor@babamarket.ma",
                role="vendor",
                is_active=True,
            )
            vendor.set_password("VendorPass123!")
            db.session.add(vendor)
            db.session.flush()

        shop = Shop.query.filter_by(slug="wa-promo-shop").first()
        if not shop:
            shop = Shop(
                name="Boutique Atlas",
                slug="wa-promo-shop",
                vendor_id=vendor.id,
                is_active=True,
            )
            db.session.add(shop)
            db.session.flush()

        for existing in Product.query.filter_by(shop_id=shop.id).all():
            db.session.delete(existing)
        db.session.flush()

        p_promo = Product(
            name="Huile d'Argan Bio",
            description="Pressée à froid au Maroc",
            price=120.0,
            stock=10,
            kind="physical",
            shop_id=shop.id,
            vendor_id=vendor.id,
            is_active=True,
            image_file="prod_promo.jpg",
        )
        p_std = Product(
            name="Miel d'Eucalyptus",
            description="Pot de 500g",
            price=85.0,
            stock=5,
            kind="physical",
            shop_id=shop.id,
            vendor_id=vendor.id,
            is_active=True,
            image_file="prod_std.jpg",
        )
        p_out = Product(
            name="Produit Épuisé",
            price=50.0,
            stock=0,
            kind="physical",
            shop_id=shop.id,
            vendor_id=vendor.id,
            is_active=True,
            image_file="prod_out.jpg",
        )
        db.session.add_all([p_promo, p_std, p_out])
        db.session.flush()

        promo = Promo(
            product_id=p_promo.id,
            type="percentage",
            value=25.0,
            end_date=datetime.utcnow() + timedelta(days=3),
            status=Promo.STATUS_APPROVED,
        )
        db.session.add(promo)
        db.session.commit()
        return p_promo.id, p_std.id, p_out.id


def test_select_products_prioritizes_promos_and_respects_stock_and_cooldown(app, tmp_path):
    promo_id, std_id, out_id = _seed_catalog(app, tmp_path)

    with app.app_context():
        selected = whatsapp_promo.select_products(5, cooldown_days=7, promoted={})
        selected_ids = [p.id for p in selected]

        assert promo_id in selected_ids
        assert std_id in selected_ids
        assert out_id not in selected_ids
        # Active promo product must come before non-promo product
        assert selected_ids.index(promo_id) < selected_ids.index(std_id)

        # Cooldown excludes recently promoted product when alternatives exist
        today = whatsapp_promo._today()
        cooled = whatsapp_promo.select_products(
            1, cooldown_days=7, promoted={str(promo_id): today}
        )
        assert [p.id for p in cooled] == [std_id]


def test_generate_copy_with_gemini_and_url_sanitization(app, tmp_path):
    promo_id, _, _ = _seed_catalog(app, tmp_path)

    with app.app_context():
        app.config["GEMINI_API_KEY"] = "test-gemini-key"
        product = db.session.get(Product, promo_id)
        promo = whatsapp_promo.get_active_promos_for_products([promo_id]).get(promo_id)
        card = whatsapp_promo.build_product_card(product, promo)

        assert "90 DH au lieu de 120 DH" in card["price_line"]
        assert f"/shop/product/{promo_id}" in card["page_url"]

        fake_session = MagicMock()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"items":[{"id":'
                                    + str(promo_id)
                                    + ',"status":"🌿 Huile pure https://evil.example.com <script>",'
                                    '"message":"Profitez de notre huile bio sur www.spam.ma dès maintenant !"}]}'
                                )
                            }
                        ]
                    }
                }
            ]
        }
        fake_session.post.return_value = fake_resp

        copies, source = whatsapp_promo.generate_copy([card], session=fake_session)
        assert source == "gemini"
        assert "evil.example.com" not in copies[promo_id]["status"]
        assert "<" not in copies[promo_id]["status"]
        assert "www.spam.ma" not in copies[promo_id]["message"]

        caption = whatsapp_promo.compose_status_caption(card, copies[promo_id])
        assert "90 DH au lieu de 120 DH" in caption
        assert "utm_medium=status" in caption

        msg = whatsapp_promo.compose_message(card, copies[promo_id], "Youssef")
        assert "Bonjour Youssef" in msg
        assert whatsapp_promo.OPT_OUT_FOOTER in msg
        assert "utm_medium=message" in msg


def test_dry_run_and_live_execution_with_opt_out_and_kill_switch(app, tmp_path):
    _seed_catalog(app, tmp_path)

    with app.app_context():
        app.config["GEMINI_API_KEY"] = ""
        whatsapp_promo.save_settings({
            "enabled": False,
            "dry_run": False,
            "admin_phone": "0611223344",
            "recipients": whatsapp_promo.parse_recipients_text(
                "0655667788, Salma\n0711223344, Karim"
            ),
            "status_products": 2,
            "daily_message_limit": 10,
            "min_delay": 30,
            "max_delay": 45,
            "cooldown_days": 7,
        })

        # 1) Live run while kill-switch is OFF must abort immediately
        blocked = whatsapp_promo.run_daily_promo(force=True, dry_run=False)
        assert blocked["aborted"] == "disabled"
        assert blocked["messages_ok"] == 0

        # 2) Dry-run preview works even when kill-switch is OFF and sends nothing
        preview = whatsapp_promo.run_daily_promo(force=True, dry_run=True)
        assert preview["mode"] == "dry_run"
        assert preview["aborted"] is None
        assert len(preview["products"]) >= 2
        assert any(d["target"] == "status" for d in preview["details"])
        assert any(d["target"] == "212611223344" for d in preview["details"])

        # 3) Enable kill-switch and run live with mocked gateway
        whatsapp_promo.save_settings({
            **whatsapp_promo.get_settings(),
            "enabled": True,
        })
        delays = []

        def fake_gateway_post(path, payload):
            if path == "/api/promo/status":
                return 200, {"ok": True}
            if path == "/api/promo/send-media":
                if payload["phone"] == "212655667788":
                    return 409, {"error": "opted_out"}
                return 200, {"ok": True}
            return 500, {"error": "unexpected"}

        with (
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", side_effect=fake_gateway_post),
        ):
            live = whatsapp_promo.run_daily_promo(
                force=False,
                dry_run=False,
                sleep=lambda s: delays.append(s),
            )

        assert live["mode"] == "live"
        assert live["aborted"] is None
        assert live["statuses_ok"] >= 2
        assert live["messages_ok"] == 2  # admin + Karim
        assert live["skipped"] == 1      # Salma opted_out
        assert len(delays) >= 1

        # Salma must now be marked opted_out in persisted settings
        updated_recipients = {
            r["phone"]: r for r in whatsapp_promo.get_settings()["recipients"]
        }
        assert updated_recipients["212655667788"]["opted_out"] is True
        assert updated_recipients["212711223344"]["opted_out"] is False

        # 4) Second automatic run on the same day is blocked by daily lock
        second = whatsapp_promo.run_daily_promo(force=False, dry_run=False)
        assert second["aborted"] == "already_ran_today"


def test_admin_promo_routes_and_cli_commands(app, tmp_path):
    _seed_catalog(app, tmp_path)

    with app.app_context():
        admin_user = User.query.filter_by(username="wa_promo_admin").first()
        if not admin_user:
            admin_user = User(
                username="wa_promo_admin",
                email="wa_promo_admin@babamarket.ma",
                role="admin",
                is_active=True,
            )
            admin_user.set_password("AdminPass123!")
            db.session.add(admin_user)

        manager_user = User.query.filter_by(username="wa_promo_mgr").first()
        if not manager_user:
            manager_user = User(
                username="wa_promo_mgr",
                email="wa_promo_mgr@babamarket.ma",
                role="manager",
                is_active=True,
            )
            manager_user.set_password("ManagerPass123!")
            db.session.add(manager_user)
        db.session.commit()
        admin_id = admin_user.id
        manager_id = manager_user.id

    # Manager must be blocked (403/302)
    mgr_client = app.test_client()
    with mgr_client.session_transaction() as sess:
        sess["_user_id"] = str(manager_id)
        sess["_fresh"] = True
    assert mgr_client.post("/admin/whatsapp-gateway/promo/settings").status_code in (302, 403)
    assert mgr_client.post("/admin/whatsapp-gateway/promo/run").status_code in (302, 403)

    # Admin can save settings and trigger dry-run preview
    adm_client = app.test_client()
    with adm_client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    resp_save = adm_client.post(
        "/admin/whatsapp-gateway/promo/settings",
        json={
            "enabled": True,
            "dry_run": True,
            "admin_phone": "0612345678",
            "recipients_text": "0699887766, Nadia",
            "status_products": 3,
            "daily_message_limit": 15,
            "min_delay": 35,
            "max_delay": 75,
            "cooldown_days": 5,
        },
    )
    assert resp_save.status_code == 200
    saved = resp_save.get_json()["settings"]
    assert saved["enabled"] is True
    assert saved["admin_phone"] == "212612345678"
    assert saved["recipients"][0]["phone"] == "212699887766"
    assert saved["recipients"][0]["label"] == "Nadia"

    resp_run = adm_client.post(
        "/admin/whatsapp-gateway/promo/run",
        json={"mode": "dry_run"},
    )
    assert resp_run.status_code == 200
    assert resp_run.get_json()["summary"]["mode"] == "dry_run"

    # CLI test
    runner = app.test_cli_runner()
    cli_status = runner.invoke(args=["whatsapp-promo", "status"])
    assert cli_status.exit_code == 0
    assert '"admin_phone": "212612345678"' in cli_status.output

    cli_run = runner.invoke(args=["whatsapp-promo", "run", "--dry-run"])
    assert cli_run.exit_code == 0
    assert '"mode": "dry_run"' in cli_run.output
