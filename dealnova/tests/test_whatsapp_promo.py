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
        assert f"/p/{promo_id}" in card["page_url"]

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
        assert card["page_url"] in caption

        msg = whatsapp_promo.compose_message(card, copies[promo_id], "Youssef")
        assert "Bonjour Youssef" in msg
        assert card["page_url"] in msg
        assert "STOP" not in msg

        # Admin or generic test labels must be stripped for a natural friendly greeting
        msg_admin = whatsapp_promo.compose_message(card, copies[promo_id], "Admin")
        assert "Bonjour 👋" in msg_admin
        assert "Admin" not in msg_admin

        # Reassurance badges must be present in sales messages
        assert "Paiement à la livraison" in msg
        assert "Qualité vérifiée" in msg

        # Legacy dirty copies must be cleansed automatically
        legacy_dirty = {
            "direct_message": "Bonjour Client 👋\n\nFraises fraîches de saison.\n\n👉 Voir : https://site.ma?utm_source=abc\n\nRépondez STOP pour vous désinscrire."
        }
        cleaned_msg = whatsapp_promo.compose_message(card, legacy_dirty, "Admin")
        assert "Bonjour 👋" in cleaned_msg
        assert "Client" not in cleaned_msg
        assert "Admin" not in cleaned_msg
        assert "STOP" not in cleaned_msg
        assert "utm_source" not in cleaned_msg
        assert "Paiement à la livraison" in cleaned_msg


def test_dry_run_and_live_execution_with_opt_out_and_kill_switch(app, tmp_path):
    _seed_catalog(app, tmp_path)

    with app.app_context():
        app.config["GEMINI_API_KEY"] = ""
        # Réinitialisation de l'état log pour un test propre et déterministe
        whatsapp_promo.mutate_json_states(
            {whatsapp_promo.LOG_KEY: dict},
            lambda p: p.update({whatsapp_promo.LOG_KEY: {}})
        )
        groups = whatsapp_promo.parse_groups_text("https://chat.whatsapp.com/Ex12345, Groupe Test")
        whatsapp_promo.save_settings({
            "enabled": False,
            "dry_run": False,
            "admin_phone": "0611223344",
            "groups": groups,
            "status_products": 2,
            "daily_message_limit": 10,
            "min_delay": 30,
            "max_delay": 45,
            "cooldown_days": 7,
        })

        # 1) Live run while kill-switch is OFF must abort immediately
        blocked = whatsapp_promo.run_daily_promo(force=True, dry_run=False)
        assert blocked["aborted"] == "disabled"
        assert blocked["statuses_ok"] == 0
        assert blocked["groups_ok"] == 0

        # 2) Dry-run preview works even when kill-switch is OFF and sends nothing
        preview = whatsapp_promo.run_daily_promo(force=True, dry_run=True)
        assert preview["mode"] == "dry_run"
        assert preview["aborted"] is None
        assert len(preview["products"]) >= 2
        assert any(d["target"] == "status" for d in preview["details"])
        assert any("chat.whatsapp.com/Ex12345" in d["target"] for d in preview["details"])

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
        assert live["groups_ok"] >= 2
        assert len(delays) >= 1

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
        vendor_user = User.query.filter_by(username="wa_promo_vendor").first()
        if not vendor_user:
            vendor_user = User(
                username="wa_promo_vendor",
                email="wa_promo_vendor@babamarket.ma",
                role="vendor",
                is_active=True,
            )
            vendor_user.set_password("VendorPass123!")
            db.session.add(vendor_user)
        db.session.commit()
        admin_id = admin_user.id
        manager_id = manager_user.id
        vendor_id = vendor_user.id

    # Vendor (non-staff) must be blocked (403/302)
    vnd_client = app.test_client()
    with vnd_client.session_transaction() as sess:
        sess["_user_id"] = str(vendor_id)
        sess["_fresh"] = True
    assert vnd_client.post("/admin/whatsapp-gateway/promo/settings").status_code in (302, 403)
    assert vnd_client.post("/admin/whatsapp-gateway/promo/run").status_code in (302, 403)

    # Manager has full access to /admin/whatsapp-gateway and promo actions
    mgr_client = app.test_client()
    with mgr_client.session_transaction() as sess:
        sess["_user_id"] = str(manager_id)
        sess["_fresh"] = True
    assert mgr_client.get("/admin/whatsapp-gateway").status_code == 200
    assert mgr_client.post("/admin/whatsapp-gateway/promo/settings", json={"enabled": True, "dry_run": True}).status_code == 200
    assert mgr_client.post("/admin/whatsapp-gateway/promo/run", json={"mode": "dry_run"}).status_code == 200

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
            "groups_text": "https://chat.whatsapp.com/GroupeNadia, Nadia Groupe",
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
    assert saved["groups"][0]["target"] == "https://chat.whatsapp.com/GroupeNadia"
    assert saved["groups"][0]["label"] == "Nadia Groupe"

    resp_run = adm_client.post(
        "/admin/whatsapp-gateway/promo/run",
        json={"mode": "dry_run"},
    )
    assert resp_run.status_code == 200
    assert resp_run.get_json()["summary"]["mode"] == "dry_run"

    resp_page = adm_client.get("/admin/whatsapp-gateway")
    assert resp_page.status_code == 200
    page_html = resp_page.get_data(as_text=True)
    assert "Délais anti-ban" not in page_html
    assert 'type="hidden" name="min_delay"' in page_html
    assert "status_products" in page_html

    # CLI test
    runner = app.test_cli_runner()
    cli_status = runner.invoke(args=["whatsapp-promo", "status"])
    assert cli_status.exit_code == 0
    assert '"admin_phone": "212612345678"' in cli_status.output

    cli_run = runner.invoke(args=["whatsapp-promo", "run", "--dry-run"])
    assert cli_run.exit_code == 0
    assert '"mode": "dry_run"' in cli_run.output


def test_whatsapp_groups_and_granular_switches(app, tmp_path):
    _seed_catalog(app, tmp_path)

    with app.app_context():
        # 1. Test du parsing et de la sérialisation des groupes
        raw_text = """
        https://chat.whatsapp.com/AbCdEf12345, Groupe Ventes Casablanca
        120363028394829@g.us, Groupe VIP Rabat
        # Ligne de commentaire
        https://chat.whatsapp.com/XyZ67890, Groupe Bons Plans
        """
        groups = whatsapp_promo.parse_groups_text(raw_text)
        assert len(groups) == 3
        assert groups[0]["target"] == "https://chat.whatsapp.com/AbCdEf12345"
        assert groups[0]["label"] == "Groupe Ventes Casablanca"
        assert groups[1]["target"] == "120363028394829@g.us"
        assert groups[1]["label"] == "Groupe VIP Rabat"

        serialized = whatsapp_promo.groups_to_text(groups)
        assert "https://chat.whatsapp.com/AbCdEf12345, Groupe Ventes Casablanca" in serialized
        assert "120363028394829@g.us, Groupe VIP Rabat" in serialized

        # 2. Test composition de message pour groupe
        card = {
            "id": 99,
            "name": "Huile d'Argan Premium",
            "price_line": "💰 99 DH au lieu de 130 DH",
            "page_url": "https://babamarket.ma/shop/product/99",
            "shop": "Boutique Bio",
        }
        copy = {"group_message": "🔥 Offre spéciale membres du groupe ! Commandez directement en ligne."}
        group_msg = whatsapp_promo.compose_group_message(card, copy, "Groupe Ventes Casablanca")
        assert "Groupe Ventes Casablanca" in group_msg
        assert "Huile d'Argan Premium" in group_msg
        assert "99 DH au lieu de 130 DH" in group_msg
        assert card["page_url"] in group_msg

        # 3. Test de l'exécution avec interrupteurs granulaires
        whatsapp_promo.mutate_json_states(
            {whatsapp_promo.LOG_KEY: dict},
            lambda p: p.update({whatsapp_promo.LOG_KEY: {}})
        )
        whatsapp_promo.save_settings({
            "enabled": True,
            "dry_run": True,
            "status_enabled": False,     # Statut désactivé
            "groups_enabled": True,      # Groupes activés
            "direct_messages_enabled": False, # Privés désactivés
            "groups": groups,
            "recipients": whatsapp_promo.parse_recipients_text("0611223344, Test"),
            "status_products": 2,
            "daily_message_limit": 10,
            "min_delay": 20,
            "max_delay": 30,
            "cooldown_days": 7,
        })

        summary = whatsapp_promo.run_daily_promo(force=True, dry_run=True)
        assert summary["mode"] == "dry_run"
        assert summary["aborted"] is None

        # Statuts et messages directs ne doivent avoir aucun événement
        channels_present = {d.get("channel") for d in summary["details"]}
        assert "status" not in channels_present
        assert "direct" not in channels_present
        assert "group" in channels_present

        # Vérification du stockage de recent_logs et last_generated dans le log
        log_state = whatsapp_promo.get_log()
        assert "last_generated" in log_state
        assert "recent_logs" in log_state
        assert len(log_state["recent_logs"]) > 0
        assert any(l.get("channel") == "group" for l in log_state["recent_logs"])



def test_retry_mechanism_and_safeguards(app, tmp_path):
    """Vérifie que les retries fonctionnent avec garde-fous et que retry_failed_promos relance les échecs."""
    _seed_catalog(app, tmp_path)

    with app.app_context():
        card = {
            "id": 100,
            "name": "Produit Test",
            "shop": "Boutique",
            "price_line": "💰 50 DH",
            "image_url": "https://babamarket.ma/img.jpg",
            "page_url": "https://babamarket.ma/p/100",
        }

        # 1. Test send_promo_media_with_retry : succès à la 2ème tentative
        attempts_counter = 0

        def flaky_gateway_post(path, payload):
            nonlocal attempts_counter
            attempts_counter += 1
            if attempts_counter == 1:
                return 500, {"error": "transient_network_error"}
            return 200, {"ok": True}

        with (
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", side_effect=flaky_gateway_post),
            patch("dealnova.app.services.whatsapp_promo.sleep", return_value=None),
        ):
            res, reason, count = whatsapp_promo.send_promo_media_with_retry("212611223344", card, "Hello", max_attempts=3)
            assert res == "sent"
            assert reason == "ok"
            assert count == 2

        # 2. Test garde-fou : pas de retry sur opted_out
        def opt_out_gateway_post(path, payload):
            return 409, {"error": "opted_out"}

        with (
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", side_effect=opt_out_gateway_post),
            patch("dealnova.app.services.whatsapp_promo.sleep", return_value=None),
        ):
            res, reason, count = whatsapp_promo.send_promo_media_with_retry("212611223344", card, "Hello", max_attempts=3)
            assert res == "opted_out"
            assert count == 1  # Arrêt immédiat sans relance inutile

        # 3. Test retry_failed_promos : relance d'un message failed récent (< 2h)
        now_local = whatsapp_promo._local_now()
        today_str = now_local.date().isoformat()
        fresh_ts = (now_local - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
        fake_log = {
            "last_generated": {"items": [card], "date": today_str, "generated_at": fresh_ts},
            "recent_logs": [
                {
                    "timestamp": fresh_ts,
                    "channel": "direct",
                    "channel_label": "Message Privé",
                    "product_id": 100,
                    "product_name": "Produit Test",
                    "target": "212699887766",
                    "target_desc": "212699887766",
                    "text": "Offre spéciale",
                    "status": "failed",
                    "detail": "Erreur temporaire",
                    "attempts": 1,
                }
            ]
        }
        whatsapp_promo._record_run(
            fake_log,
            promoted_ids=[],
            sent_today=0,
            today=today_str,
            preview=False,
            last_generated=fake_log["last_generated"],
            new_recent_logs=fake_log["recent_logs"],
        )

        def success_gateway_post(path, payload):
            return 200, {"ok": True}

        with (
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", side_effect=success_gateway_post),
            patch("dealnova.app.services.whatsapp_promo.sleep", return_value=None),
        ):
            retry_summary = whatsapp_promo.retry_failed_promos(force=True)
            assert retry_summary["success"] is True
            assert retry_summary["retried"] == 1
            assert retry_summary["ok"] == 1
            assert retry_summary["failed"] == 0

            # Vérification de l'état mis à jour dans les logs
            updated_log = whatsapp_promo.get_log()
            first_log = updated_log["recent_logs"][0]
            assert first_log["status"] == "ok"
            assert "Statut publié avec succès" in first_log["detail"] or "Message remis avec succès" in first_log["detail"]


def test_enhancements_clicks_pinned_test_and_schedule(app, tmp_path):
    """Vérifie le suivi des clics, les produits coup de cœur épinglés, l'envoi test et l'heure programmée."""
    promo_id, extra_id, third_id = _seed_catalog(app, tmp_path)

    with app.app_context():
        # 1. Test du suivi des clics /p/<id>
        whatsapp_promo.record_link_click(promo_id)
        whatsapp_promo.record_link_click(promo_id)
        whatsapp_promo.record_link_click(extra_id)

        clicks = whatsapp_promo.get_today_clicks()
        assert clicks.get(str(promo_id)) == 2
        assert clicks.get(str(extra_id)) == 1
        assert clicks.get("_total") == 3

        # 2. Test sélection avec coup de cœur épinglé
        selected = whatsapp_promo.select_products(
            count=3,
            cooldown_days=7,
            pinned_ids=[extra_id],
        )
        assert len(selected) >= 1
        assert selected[0].id == extra_id  # Le produit épinglé est en première position !

        # 3. Test heure programmée et réglages
        st = whatsapp_promo.save_settings({
            "schedule_time": "18:00",
            "pinned_product_ids": [extra_id, promo_id],
        })
        assert st["schedule_time"] == "18:00"
        assert extra_id in st["pinned_product_ids"]

        # 4. Test envoi test à l'administrateur
        card = {
            "id": promo_id,
            "name": "Produit Test Admin",
            "price_line": "💰 50 DH",
            "page_url": f"https://babamarket.ma/p/{promo_id}",
            "image_url": "https://babamarket.ma/img.jpg",
            "shop": "Boutique",
        }
        whatsapp_promo.save_settings({
            **whatsapp_promo.get_settings(),
            "admin_phone": "212611223344",
        })

        def success_test_post(path, payload):
            return 200, {"ok": True}

        with (
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected", "phone": "212611223344"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", side_effect=success_test_post),
            patch("dealnova.app.services.whatsapp_promo.sleep", return_value=None),
        ):
            test_res = whatsapp_promo.send_test_to_admin(product_id=promo_id)
            assert test_res["success"] is True
            assert test_res["phone"] == "212611223344"

            # Vérification du tag Test dans les logs
            logs = whatsapp_promo.get_log().get("recent_logs", [])
            assert any(l.get("channel_label") == "Test Admin" for l in logs)


def test_image_base64_transmission_in_media_and_status(app, tmp_path):
    promo_id, _, _ = _seed_catalog(app, tmp_path)

    with app.app_context():
        product = db.session.get(Product, promo_id)
        card = whatsapp_promo.build_product_card(product)
        assert card["has_image"] is True
        assert card["image_base64"] != ""
        assert card["image_url"] != ""

        sent_payloads = []

        def capture_gateway_post(path, payload):
            sent_payloads.append((path, payload))
            return 200, {"ok": True}

        with patch("dealnova.app.services.whatsapp_promo._gateway_post", side_effect=capture_gateway_post):
            # Envoi média
            res, detail = whatsapp_promo.send_promo_media("212612345678", card, "Texte test")
            assert res == "sent"
            assert sent_payloads[0][0] == "/api/promo/send-media"
            assert sent_payloads[0][1]["has_image"] is True
            assert sent_payloads[0][1]["image_base64"] == card["image_base64"]

            # Envoi statut
            ok, reason = whatsapp_promo.post_status(card, "Légende", ["212612345678@s.whatsapp.net"])
            assert ok is True
            assert sent_payloads[1][0] == "/api/promo/status"
            assert sent_payloads[1][1]["has_image"] is True
            assert sent_payloads[1][1]["image_base64"] == card["image_base64"]



def test_two_hour_ttl_daily_history_reset_and_scheduled_window(app, tmp_path):
    """Vérifie :
    1) Les messages bloqués (failed/pending) de plus de 2h sont automatiquement vidés et jamais relancés.
    2) L'historique et suivi (recent_logs, runs, compteurs) de la veille se vident automatiquement le lendemain.
    3) Le planificateur (--scheduled) respecte la fenêtre stricte de 2h et ignore tout créneau expiré (> 2h).
    """
    _seed_catalog(app, tmp_path)

    with app.app_context():
        now_local = whatsapp_promo._local_now()
        today_str = now_local.date().isoformat()
        yesterday_str = (now_local.date() - timedelta(days=1)).isoformat()

        # A. Test vidage automatique de l'historique d'hier (J-1 -> J)
        whatsapp_promo._persist_json_state(whatsapp_promo.LOG_KEY, {
            "history_date": yesterday_str,
            "last_run_date": yesterday_str,
            "recent_logs": [
                {
                    "timestamp": f"{yesterday_str} 18:35:00",
                    "channel": "group",
                    "product_id": 1,
                    "target": "https://chat.whatsapp.com/Grp1",
                    "text": "Message bloqué hier",
                    "status": "failed",
                },
                {
                    "timestamp": f"{yesterday_str} 10:35:00",
                    "channel": "status",
                    "product_id": 2,
                    "target": "status",
                    "text": "Statut envoyé hier",
                    "status": "ok",
                },
            ],
            "runs": [{"started_at": f"{yesterday_str} 10:30:00", "mode": "live"}],
            "last_generated": {"date": yesterday_str, "items": [{"id": 1, "name": "Hier"}]},
            "clicks_by_date": {yesterday_str: {"_total": 9, "1": 9}},
            "sent_by_date": {yesterday_str: 8},
            "promoted": {"1": yesterday_str},
        })

        cleaned = whatsapp_promo.get_log()
        assert cleaned["history_date"] == today_str
        assert cleaned["recent_logs"] == []  # Historique et suivi entièrement vidés au changement de jour !
        assert cleaned["runs"] == []
        assert cleaned["last_generated"] == {}
        assert yesterday_str not in cleaned.get("clicks_by_date", {})
        assert cleaned["promoted"].get("1") == yesterday_str  # Anti-répétition préservée en coulisses

        # B. Test persistance max 2h le même jour : > 2h vidé, < 2h conservé, ok du jour conservé
        expired_ts = (now_local - timedelta(hours=2, minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        fresh_ts = (now_local - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        ok_ts = (now_local - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")

        # Si minuit rendrait expired_ts ou ok_ts sur hier, on fixe une heure de référence à 16h00 aujourd'hui
        ref_now = now_local.replace(hour=16, minute=0, second=0, microsecond=0)
        ref_today = ref_now.date().isoformat()
        expired_same_day = (ref_now - timedelta(hours=2, minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        fresh_same_day = (ref_now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
        ok_same_day = (ref_now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

        cleaned_2h, changed_2h = whatsapp_promo._clean_and_expire_log(
            {
                "history_date": ref_today,
                "recent_logs": [
                    {"timestamp": expired_same_day, "status": "failed", "product_id": 10, "target": "grp", "text": "Trop vieux"},
                    {"timestamp": expired_same_day, "status": "pending", "product_id": 11, "target": "grp", "text": "En attente >2h"},
                    {"timestamp": fresh_same_day, "status": "failed", "product_id": 12, "target": "grp", "text": "Récent <2h"},
                    {"timestamp": ok_same_day, "status": "ok", "product_id": 13, "target": "grp", "text": "Publié ce matin"},
                ],
            },
            now=ref_now,
        )
        assert changed_2h is True
        remaining_ids = [e["product_id"] for e in cleaned_2h["recent_logs"]]
        assert 10 not in remaining_ids  # Échec > 2h vidé !
        assert 11 not in remaining_ids  # Pending > 2h vidé !
        assert 12 in remaining_ids      # Échec < 2h encore dans la fenêtre de persistance
        assert 13 in remaining_ids      # Succès du jour conservé jusqu'à minuit

        # C. Test fenêtre stricte 2h dans run_scheduled_tick()
        whatsapp_promo._persist_json_state(whatsapp_promo.LOG_KEY, {"history_date": ref_today})
        whatsapp_promo.save_settings({
            "enabled": True,
            "dry_run": False,
            "schedule_time": "10:30",    # À 16h00 -> dépassé de 5h30 (> 2h) => NE DOIT PAS PARTIR !
            "schedule_time_2": "18:30",  # À 16h00 -> pas encore l'heure => NE DOIT PAS PARTIR !
            "groups": whatsapp_promo.parse_groups_text("https://chat.whatsapp.com/Test2h, Groupe 2h"),
        })
        with patch("dealnova.app.services.whatsapp_promo._local_now", return_value=ref_now):
            tick_expired = whatsapp_promo.run_scheduled_tick(sleep_fn=lambda _: None)
            assert tick_expired["status"] == "idle"

        # À 19h15 (45 min après 18:30 -> dans la fenêtre de 2h), l'envoi 2 s'exécute
        evening_now = now_local.replace(hour=19, minute=15, second=0, microsecond=0)
        with (
            patch("dealnova.app.services.whatsapp_promo._local_now", return_value=evening_now),
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", return_value=(200, {"ok": True})),
        ):
            tick_ok = whatsapp_promo.run_scheduled_tick(sleep_fn=lambda _: None)
            assert tick_ok["status"] == "executed"
            assert tick_ok["slot"] == "slot_2:18:30"

            # Un second tick 15 min plus tard sur le même créneau ne renvoie rien en double
            tick_dup = whatsapp_promo.run_scheduled_tick(sleep_fn=lambda _: None)
            assert tick_dup["status"] == "idle"


def test_ten_offers_mix_random_rotation_and_zero_same_day_repeat(app, tmp_path):
    """Vérifie :
    - Quotas par défaut : 5 produits + 3 services + 2 locations = 10 offres, 10 Statuts 24h, délais 45s-90s.
    - Migration automatique d'anciens réglages v1 -> v2.
    - Mélange aléatoire équitable entre produits en promo et produits standards (hors promo).
    - Zéro répétition le même jour entre l'envoi du Matin (10 offres) et l'envoi du Soir (10 nouvelles offres),
      avec repli sur les locations actives plus anciennes si < 24h est épuisé.
    """
    from dealnova.app.models.rental import RentalListing, RentalMedia

    upload_dir = tmp_path / "uploads"
    rentals_dir = upload_dir / "rentals"
    upload_dir.mkdir(exist_ok=True)
    rentals_dir.mkdir(exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)

    with app.app_context():
        app.config["GEMINI_API_KEY"] = ""

        # 1. Vérification de la migration v1 -> v2 et des nouveaux défauts
        whatsapp_promo._persist_json_state(whatsapp_promo.SETTINGS_KEY, {
            "enabled": True,
            "products_count": 3,
            "services_count": 3,
            "rentals_count": 2,
            "status_products": 2,
            "min_delay": 30,
            "max_delay": 90,
        })
        migrated = whatsapp_promo.get_settings()
        assert migrated["products_count"] == 5
        assert migrated["services_count"] == 3
        assert migrated["rentals_count"] == 2
        assert migrated["status_products"] == 12
        assert migrated["min_delay"] == 45
        assert migrated["max_delay"] == 90

        # Vérification unitaire du calcul dynamique des délais selon le nombre de groupes
        assert whatsapp_promo._compute_group_step_delay_range(45, 90, 1) == (45.0, 90.0)
        assert whatsapp_promo._compute_group_step_delay_range(45, 90, 3) == (15.0, 30.0)

        # 2. Création d'un catalogue riche : 12 produits (6 promos + 6 hors promo), 6 services, 4 locations (2 <24h + 2 anciennes)
        vendor = User.query.filter_by(username="wa_mix10_vendor").first()
        if not vendor:
            vendor = User(
                username="wa_mix10_vendor",
                email="wa_mix10_vendor@babamarket.ma",
                role="vendor",
                is_active=True,
            )
            vendor.set_password("VendorPass123!")
            db.session.add(vendor)
            db.session.flush()

        shop = Shop.query.filter_by(slug="wa-mix10-shop").first()
        if not shop:
            shop = Shop(name="Marché Mix 10", slug="wa-mix10-shop", vendor_id=vendor.id, is_active=True)
            db.session.add(shop)
            db.session.flush()

        # Nettoyer uniquement les entrées de cette boutique de test (sans toucher aux clés étrangères existantes)
        for old_r in RentalListing.query.filter_by(shop_id=shop.id).all():
            db.session.delete(old_r)
        for old_p in Product.query.filter_by(shop_id=shop.id).all():
            Promo.query.filter_by(product_id=old_p.id).delete()
            db.session.delete(old_p)
        db.session.flush()

        promo_prod_ids = set()
        regular_prod_ids = set()
        for i in range(12):
            img_name = f"phys_{i}.jpg"
            Image.new("RGB", (300, 300), (30 + i * 10, 100, 80)).save(upload_dir / img_name)
            p = Product(
                name=f"Produit Catalogue {i}",
                description="Qualité supérieure",
                price=100.0 + i,
                stock=10,
                kind="physical",
                shop_id=shop.id,
                vendor_id=vendor.id,
                is_active=True,
                image_file=img_name,
            )
            db.session.add(p)
            db.session.flush()
            if i < 6:
                promo_prod_ids.add(p.id)
                db.session.add(Promo(
                    product_id=p.id,
                    type="percentage",
                    value=15.0,
                    end_date=datetime.utcnow() + timedelta(days=5),
                    status=Promo.STATUS_APPROVED,
                ))
            else:
                regular_prod_ids.add(p.id)

        for i in range(6):
            img_name = f"serv_{i}.jpg"
            Image.new("RGB", (300, 300), (80, 60 + i * 20, 140)).save(upload_dir / img_name)
            s = Product(
                name=f"Service Pro {i}",
                description="Intervention rapide",
                price=150.0 + i * 10,
                stock=0,
                kind="service",
                shop_id=shop.id,
                vendor_id=vendor.id,
                is_active=True,
                image_file=img_name,
            )
            db.session.add(s)

        recent_rental_keys = set()
        older_rental_keys = set()
        for i in range(4):
            r_img = f"rent_{i}.jpg"
            Image.new("RGB", (320, 320), (120, 90, 40 + i * 30)).save(rentals_dir / r_img)
            created_dt = (
                datetime.utcnow() - timedelta(hours=3)
                if i < 2
                else datetime.utcnow() - timedelta(hours=72)
            )
            r = RentalListing(
                owner_id=vendor.id,
                shop_id=shop.id,
                title=f"Appartement Test {i}",
                slug=f"appartement-test-mix-{i}",
                description="Bel appartement lumineux",
                listing_type="monthly",
                property_type="apartment",
                city="Casablanca",
                area="Maarif",
                rent_cents=350000 + i * 10000,
                status="active",
                is_active=True,
                created_at=created_dt,
            )
            db.session.add(r)
            db.session.flush()
            db.session.add(RentalMedia(
                listing_id=r.id,
                kind="image",
                file_path=f"uploads/rentals/{r_img}",
            ))
            if i < 2:
                recent_rental_keys.add(f"rental_{r.id}")
            else:
                older_rental_keys.add(f"rental_{r.id}")

        db.session.commit()

        # Réinitialiser le log et configurer Matin avec 1 seul groupe (-> garde 45s-90s) et 12 Statuts/jour (6 matin + 6 soir)
        whatsapp_promo._persist_json_state(whatsapp_promo.LOG_KEY, {})
        whatsapp_promo.save_settings({
            "enabled": True,
            "dry_run": False,
            "status_enabled": True,
            "groups_enabled": True,
            "groups": whatsapp_promo.parse_groups_text("https://chat.whatsapp.com/GrpMix10, Groupe Unique"),
            "products_count": 5,
            "services_count": 3,
            "rentals_count": 2,
            "rental_max_age_hours": 24,
            "status_products": 12,
            "min_delay": 45,
            "max_delay": 90,
        })

        base_now = whatsapp_promo._local_now()
        morning_now = base_now.replace(hour=10, minute=35, second=0, microsecond=0)
        evening_now = base_now.replace(hour=18, minute=35, second=0, microsecond=0)
        morning_sleeps = []

        with (
            patch("dealnova.app.services.whatsapp_promo._rental_upload_roots", return_value=[rentals_dir.resolve()]),
            patch("dealnova.app.services.whatsapp_promo._local_now", return_value=morning_now),
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", return_value=(200, {"ok": True})),
        ):
            morning_run = whatsapp_promo.run_daily_promo(force=False, dry_run=False, sleep=lambda s: morning_sleeps.append(s))

        assert morning_run["aborted"] is None
        assert len(morning_run["products"]) == 10
        assert morning_run["statuses_ok"] == 6   # 6 Statuts le matin (sur 12 au total) !
        assert morning_run["groups_ok"] == 10
        # Les 9 derniers délais correspondent aux pauses entre les 10 messages de l'unique groupe : 45s à 90s conservés !
        morning_group_delays = morning_sleeps[-9:]
        assert len(morning_group_delays) == 9
        assert all(45.0 <= d <= 90.0 for d in morning_group_delays)

        m_phys = [it["id"] for it in morning_run["products"] if it["item_type"] == "physical"]
        m_serv = [it["id"] for it in morning_run["products"] if it["item_type"] == "service"]
        m_rent = [it["id"] for it in morning_run["products"] if it["item_type"] == "rental"]
        assert len(m_phys) == 5
        assert len(m_serv) == 3
        assert len(m_rent) == 2

        # Vérifie que les produits HORS PROMO passent aussi aléatoirement dès le 1er envoi (pas monopolisé par les 6 promos)
        assert any(pid in regular_prod_ids for pid in m_phys)
        assert any(pid in promo_prod_ids for pid in m_phys)
        # Vérifie que les 2 locations < 24h ont été prises en priorité le matin
        assert set(m_rent) == recent_rental_keys

        # Envoi du Soir (18h35) avec 3 GROUPES : alternance Round-Robin (G1 -> G2 -> G3) + délais répartis (15-30s) + 6 nouveaux Statuts (= 12 total)
        three_groups_text = "\n".join([
            "https://chat.whatsapp.com/GrpA, Groupe Casa",
            "https://chat.whatsapp.com/GrpB, Groupe Rabat",
            "https://chat.whatsapp.com/GrpC, Groupe Marrakech",
        ])
        whatsapp_promo.save_settings({
            **whatsapp_promo.get_settings(),
            "groups": whatsapp_promo.parse_groups_text(three_groups_text),
        })
        evening_sleeps = []

        with (
            patch("dealnova.app.services.whatsapp_promo._rental_upload_roots", return_value=[rentals_dir.resolve()]),
            patch("dealnova.app.services.whatsapp_promo._local_now", return_value=evening_now),
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", return_value=(200, {"ok": True})),
        ):
            evening_run = whatsapp_promo.run_daily_promo(force=False, dry_run=False, sleep=lambda s: evening_sleeps.append(s))

        assert evening_run["aborted"] is None
        assert len(evening_run["products"]) == 10
        assert evening_run["statuses_ok"] == 6   # 6 le matin + 6 le soir = 12 Statuts au total !
        assert evening_run["groups_ok"] == 30    # 10 offres x 3 groupes
        assert whatsapp_promo.get_log()["statuses_by_date"][morning_now.date().isoformat()] == 12

        # Vérification de l'alternance Round-Robin stricte : GrpA -> GrpB -> GrpC -> GrpA -> GrpB -> GrpC
        grp_targets_order = [d["target"] for d in evening_run["details"] if d["channel"] == "group"]
        assert grp_targets_order[:6] == [
            "https://chat.whatsapp.com/GrpA",
            "https://chat.whatsapp.com/GrpB",
            "https://chat.whatsapp.com/GrpC",
            "https://chat.whatsapp.com/GrpA",
            "https://chat.whatsapp.com/GrpB",
            "https://chat.whatsapp.com/GrpC",
        ]
        # Vérification de la répartition des délais sur les 3 groupes (15s à 30s entre chaque groupe => 45s-90s dans un même groupe)
        evening_group_delays = evening_sleeps[-29:]
        assert len(evening_group_delays) == 29
        assert all(15.0 <= d <= 30.0 for d in evening_group_delays)

        morning_ids = {str(it["id"]) for it in morning_run["products"]}
        evening_ids = {str(it["id"]) for it in evening_run["products"]}
        assert morning_ids.isdisjoint(evening_ids)  # ZÉRO répétition le même jour !

        # Les 2 locations du soir doivent être les 2 locations actives plus anciennes (repli <24h épuisé)
        e_rent = {it["id"] for it in evening_run["products"] if it["item_type"] == "rental"}
        assert e_rent == older_rental_keys
def test_wave_1_to_wave_2_auto_transition_and_reinforced_controls(app, tmp_path):
    """Vérifie :
    1) Affichage auto des 10 offres de la Vague 1 (Matin) à l'ouverture de /admin/whatsapp-gateway
       (avec complétion intelligente jusqu'à 10 offres même si une catégorie manque d'articles).
    2) Édition personnalisée d'une location ('rental_X'), recherche & épinglage multi-types,
       et conservation exacte du texte personnalisé lors de l'envoi réel.
    3) Dès que la Vague 1 (Matin) est envoyée, la Vague 2 (Soir) de 10 nouvelles offres prend
       automatiquement sa place dans la page sans doublon avec le matin.
    4) Tout changement de quotas dans l'Étape 3 adapte immédiatement les offres affichées à l'Étape 2.
    """
    from dealnova.app.models.rental import RentalListing, RentalMedia

    upload_dir = tmp_path / "uploads_wave_ui"
    upload_dir.mkdir(exist_ok=True)
    rentals_dir = tmp_path / "rentals_wave_ui"
    rentals_dir.mkdir(exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)

    with app.app_context():
        app.config["GEMINI_API_KEY"] = ""
        admin_user = User.query.filter_by(username="wa_wave_admin").first()
        if not admin_user:
            admin_user = User(
                username="wa_wave_admin",
                email="wa_wave_admin@babamarket.ma",
                role="admin",
                is_active=True,
            )
            admin_user.set_password("AdminWave123!")
            db.session.add(admin_user)

        vendor = User.query.filter_by(username="wa_wave_vendor").first()
        if not vendor:
            vendor = User(
                username="wa_wave_vendor",
                email="wa_wave_vendor@babamarket.ma",
                role="vendor",
                is_active=True,
            )
            vendor.set_password("VendorWave123!")
            db.session.add(vendor)
        db.session.flush()

        shop = Shop.query.filter_by(slug="wa-wave-shop").first()
        if not shop:
            shop = Shop(name="Boutique Vagues", slug="wa-wave-shop", vendor_id=vendor.id, is_active=True)
            db.session.add(shop)
            db.session.flush()

        # Nettoyer les anciennes lignes de cette boutique de test (idempotence entre runs) et désactiver le reste
        for old_r in RentalListing.query.filter_by(shop_id=shop.id).all():
            db.session.delete(old_r)
        for old_p in Product.query.filter_by(shop_id=shop.id).all():
            Promo.query.filter_by(product_id=old_p.id).delete()
            db.session.delete(old_p)
        db.session.flush()
        Product.query.update({Product.is_active: False})
        RentalListing.query.update({RentalListing.is_active: False})
        db.session.flush()

        # On crée 18 produits physiques, 3 services seulement (donc le soir il n'en restera plus et le backfill complétera à 10 !) et 3 locations
        for i in range(18):
            fn = f"wv_phys_{i}.jpg"
            Image.new("RGB", (300, 300), (40 + i * 8, 110, 90)).save(upload_dir / fn)
            db.session.add(Product(
                name=f"Article Vague {i}",
                description="Stock vérifié",
                price=90.0 + i,
                stock=8,
                kind="physical",
                shop_id=shop.id,
                vendor_id=vendor.id,
                is_active=True,
                image_file=fn,
            ))

        for i in range(3):
            fn = f"wv_serv_{i}.jpg"
            Image.new("RGB", (300, 300), (90, 70 + i * 25, 150)).save(upload_dir / fn)
            db.session.add(Product(
                name=f"Prestation Vague {i}",
                description="Service pro",
                price=200.0 + i * 15,
                stock=0,
                kind="service",
                shop_id=shop.id,
                vendor_id=vendor.id,
                is_active=True,
                image_file=fn,
            ))

        rental_keys = []
        for i in range(3):
            fn = f"wv_rent_{i}.jpg"
            Image.new("RGB", (320, 320), (130, 95, 50 + i * 30)).save(rentals_dir / fn)
            rl = RentalListing(
                owner_id=vendor.id,
                shop_id=shop.id,
                title=f"Studio Moderne {i}",
                slug=f"studio-moderne-vague-{i}",
                description="Proche tramway",
                listing_type="monthly",
                property_type="studio",
                city="Rabat",
                area="Agdal",
                rent_cents=280000 + i * 10000,
                status="active",
                is_active=True,
                created_at=datetime.utcnow() - timedelta(hours=2),
            )
            db.session.add(rl)
            db.session.flush()
            db.session.add(RentalMedia(
                listing_id=rl.id,
                kind="image",
                file_path=f"uploads/rentals/{fn}",
            ))
            rental_keys.append(f"rental_{rl.id}")

        db.session.commit()
        admin_id = admin_user.id

        # Réinitialiser le log et configurer 5 produits + 3 services + 2 locations = 10 offres/vague
        whatsapp_promo._persist_json_state(whatsapp_promo.LOG_KEY, {})
        whatsapp_promo.save_settings({
            "enabled": True,
            "dry_run": False,
            "status_enabled": True,
            "groups_enabled": True,
            "groups": whatsapp_promo.parse_groups_text("https://chat.whatsapp.com/GrpWave, Groupe Vague"),
            "products_count": 5,
            "services_count": 3,
            "rentals_count": 2,
            "rental_max_age_hours": 24,
            "status_products": 12,
            "min_delay": 45,
            "max_delay": 90,
            "schedule_time": "10:30",
            "schedule_time_2": "18:30",
        })

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    with patch("dealnova.app.services.whatsapp_promo._rental_upload_roots", return_value=[rentals_dir.resolve()]):
        # 1) Ouverture RAPIDE de /admin/whatsapp-gateway (zéro watermark CPU ni Gemini synchrone, miniatures /static/uploads/..., zéro ligne Délais anti-ban)
        with (
            patch("dealnova.app.services.image_download.watermarked_photo", side_effect=AssertionError("watermarked_photo ne doit jamais bloquer le chargement HTML !")),
            patch("dealnova.app.services.whatsapp_promo.generate_copy", side_effect=AssertionError("Gemini ne doit jamais bloquer le chargement HTML !")),
        ):
            r_get_1 = client.get("/admin/whatsapp-gateway")
        assert r_get_1.status_code == 200
        html_1 = r_get_1.get_data(as_text=True)
        assert "Vague 1 — Matin" in html_1
        assert "Délais anti-ban" not in html_1
        assert "/static/uploads/" in html_1
        assert '/photo/0/download"' not in html_1
        assert 'data-wave-number="1"' in html_1
        assert "#10/10" in html_1
        assert "6 en Statut 24h" in html_1

        with app.app_context():
            lg_morning = whatsapp_promo.get_log()["last_generated"]
            assert lg_morning["wave_number"] == 1
            assert len(lg_morning["items"]) == 10
            morning_wave_ids = [str(it["id"]) for it in lg_morning["items"]]
            target_rental_id = next(str(it["id"]) for it in lg_morning["items"] if it["item_type"] == "rental")

        # 2) Recherche multi-types (produits + services + locations) et édition personnalisée sur une Location ('rental_X')
        r_search = client.get("/admin/whatsapp-gateway/promo/search-products?q=Studio")
        assert r_search.status_code == 200
        found_items = r_search.get_json()["results"]
        assert any(str(x["id"]).startswith("rental_") and x["kind"] == "Location" for x in found_items)

        custom_status = "🏠 Studio Moderne exclusif à Rabat Agdal — Visite immédiate !"
        custom_group = "🔥 NOUVEAU LOGEMENT DISPONIBLE À RABAT AGDAL ! Contactez-nous vite sur Baba Market."
        r_edit = client.post(
            "/admin/whatsapp-gateway/promo/edit-copy",
            json={
                "product_id": target_rental_id,
                "status_caption": custom_status,
                "group_message": custom_group,
            },
        )
        assert r_edit.status_code == 200
        assert r_edit.get_json()["success"] is True

        # 3) Exécution LIVE de la Vague 1 (Matin) -> utilise exactement les 10 offres affichées + conserve le texte personnalisé
        sent_payloads = []

        def capture_gateway_post(path, payload):
            sent_payloads.append((path, payload))
            return 200, {"ok": True}

        with (
            app.app_context(),
            patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}),
            patch("dealnova.app.services.whatsapp_promo._gateway_post", side_effect=capture_gateway_post),
        ):
            live_w1 = whatsapp_promo.run_daily_promo(force=False, dry_run=False, sleep=lambda _s: None)

        assert live_w1["aborted"] is None
        assert [str(it["id"]) for it in live_w1["products"]] == morning_wave_ids
        assert any(custom_group in (p.get("caption") or "") for path, p in sent_payloads if path == "/api/promo/send-media")

        # 4) IMMÉDIATEMENT après l'envoi du matin, last_generated et la page sont mis à jour sur Vague 2 — Soir (10 nouvelles offres, même avec 0 service restant grâce au backfill !)
        with app.app_context():
            lg_evening = whatsapp_promo.get_log()["last_generated"]
            assert lg_evening["consumed"] is False
            assert lg_evening["wave_number"] == 2
            assert lg_evening["wave_title"] == "Vague 2 — Soir"
            assert len(lg_evening["items"]) == 10
            evening_wave_ids = {str(it["id"]) for it in lg_evening["items"]}
            assert evening_wave_ids.isdisjoint(set(morning_wave_ids))

        r_get_2 = client.get("/admin/whatsapp-gateway")
        assert r_get_2.status_code == 200
        html_2 = r_get_2.get_data(as_text=True)
        assert "Vague 2 — Soir" in html_2
        assert 'data-wave-number="2"' in html_2
        assert "#10/10" in html_2

        r_json_status = client.get("/admin/whatsapp-gateway?format=json")
        assert r_json_status.status_code == 200
        assert r_json_status.get_json()["promo_state"]["wave_number"] == 2

        # 5) Changement des quotas via Étape 3 (ex: 4 produits + 2 services + 1 location = 7 offres) -> adaptation immédiate du lot affiché !
        r_upd = client.post(
            "/admin/whatsapp-gateway/promo/settings",
            json={
                "enabled": True,
                "status_enabled": True,
                "groups_enabled": True,
                "products_count": 4,
                "services_count": 2,
                "rentals_count": 1,
                "status_products": 10,
                "min_delay": 45,
                "max_delay": 90,
                "schedule_time": "09:30",
                "schedule_time_2": "19:15",
            },
        )
        assert r_upd.status_code == 200
        upd_json = r_upd.get_json()
        assert upd_json["regenerated"] is True
        assert upd_json["settings"]["schedule_time"] == "09:30"
        assert upd_json["settings"]["schedule_time_2"] == "19:15"

        with app.app_context():
            lg_adapted = whatsapp_promo.get_log()["last_generated"]
            assert len(lg_adapted["items"]) == 7


def test_offer_photo_video_preview_and_short_rental_visit(app, tmp_path):
    """Vérifie :
    - Extraction de toutes les photos (gallery_urls), de la vidéo (video_url) et du lien direct (public_url)
      aussi bien pour un produit/service que pour une location immobilière, y compris par backfill sur un lot déjà en cache.
    - Rendu de la visionneuse native <dialog id="offerMediaDialog"> + boutons 'Voir photos (2)', 'Voir la vidéo' et 'Visiter l'annonce'.
    - Résolution propre du lien court /l/<id> vers /location/<slug> et respect de ?preview=1 (sans gonfler les clics WhatsApp).
    """
    from dealnova.app.models.rental import RentalListing, RentalMedia

    upload_dir = tmp_path / "uploads"
    rentals_dir = upload_dir / "rentals"
    videos_dir = upload_dir / "product_videos"
    upload_dir.mkdir(exist_ok=True)
    rentals_dir.mkdir(exist_ok=True)
    videos_dir.mkdir(exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        app.config["GEMINI_API_KEY"] = ""
        admin_user = User.query.filter_by(username="wa_media_admin").first()
        if not admin_user:
            admin_user = User(
                username="wa_media_admin",
                email="wa_media_admin@babamarket.ma",
                role="admin",
                is_active=True,
            )
            admin_user.set_password("AdminMedia123!")
            db.session.add(admin_user)

        vendor = User.query.filter_by(username="wa_media_vendor").first()
        if not vendor:
            vendor = User(
                username="wa_media_vendor",
                email="wa_media_vendor@babamarket.ma",
                role="vendor",
                is_active=True,
            )
            vendor.set_password("VendorMedia123!")
            db.session.add(vendor)
        db.session.flush()

        shop = Shop.query.filter_by(slug="wa-media-shop").first()
        if not shop:
            shop = Shop(name="Boutique Média", slug="wa-media-shop", vendor_id=vendor.id, is_active=True)
            db.session.add(shop)
            db.session.flush()

        for old_r in RentalListing.query.filter_by(shop_id=shop.id).all():
            db.session.delete(old_r)
        for old_p in Product.query.filter_by(shop_id=shop.id).all():
            db.session.delete(old_p)
        db.session.flush()

        Image.new("RGB", (300, 300), (20, 120, 90)).save(upload_dir / "p_gal_1.jpg")
        Image.new("RGB", (300, 300), (40, 140, 110)).save(upload_dir / "p_gal_2.jpg")
        (videos_dir / "demo_prod.mp4").write_bytes(b"fake-mp4")

        prod = Product(
            name="Robot Cuisine Vidéo",
            description="Avec 2 photos et 1 vidéo",
            price=450.0,
            stock=5,
            kind="physical",
            shop_id=shop.id,
            vendor_id=vendor.id,
            is_active=True,
            image_file="p_gal_1.jpg|p_gal_2.jpg",
            video_file="uploads/product_videos/demo_prod.mp4",
        )
        db.session.add(prod)

        Image.new("RGB", (320, 320), (90, 90, 180)).save(rentals_dir / "r_gal_1.jpg")
        Image.new("RGB", (320, 320), (110, 90, 180)).save(rentals_dir / "r_gal_2.jpg")
        (rentals_dir / "visite_appart.mp4").write_bytes(b"fake-rental-mp4")

        rent = RentalListing(
            owner_id=vendor.id,
            shop_id=shop.id,
            title="Studio Moderne Visite Vidéo",
            slug="studio-moderne-visite-video",
            description="Studio meublé calme",
            listing_type="monthly",
            property_type="studio",
            city="Rabat",
            area="Agdal",
            rent_cents=350000,
            status="active",
            is_active=True,
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.session.add(rent)
        db.session.flush()
        db.session.add(RentalMedia(listing_id=rent.id, kind="image", file_path="uploads/rentals/r_gal_1.jpg"))
        db.session.add(RentalMedia(listing_id=rent.id, kind="image", file_path="uploads/rentals/r_gal_2.jpg"))
        db.session.add(RentalMedia(listing_id=rent.id, kind="video", file_path="uploads/rentals/visite_appart.mp4"))
        db.session.commit()

        prod_id = prod.id
        rent_id = rent.id
        admin_id = admin_user.id

        p_card = whatsapp_promo.build_product_card(prod, include_base64=False)
        assert len(p_card["gallery_urls"]) == 2
        assert p_card["video_url"] == "/static/uploads/product_videos/demo_prod.mp4"
        assert p_card["public_url"] == f"/shop/product/{prod_id}"

        r_card = whatsapp_promo.build_rental_card(rent, include_base64=False)
        assert len(r_card["gallery_urls"]) == 2
        assert r_card["video_url"] == "/static/uploads/rentals/visite_appart.mp4"
        assert r_card["public_url"] == "/location/studio-moderne-visite-video"

        whatsapp_promo._persist_json_state(whatsapp_promo.LOG_KEY, {"history_date": whatsapp_promo._today()})
        whatsapp_promo.save_settings({
            "enabled": True,
            "status_enabled": True,
            "groups_enabled": True,
            "products_count": 1,
            "services_count": 0,
            "rentals_count": 1,
            "pinned_product_ids": [prod_id, f"rental_{rent_id}"],
        })

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    with patch("dealnova.app.services.whatsapp_promo.get_whatsapp_gateway_status", return_value={"status": "connected"}):
        resp = client.get("/admin/whatsapp-gateway")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="offerMediaDialog"' in html
        assert 'id="offerMediaVideo"' in html
        assert "Voir photos (2)" in html
        assert "Voir la vidéo" in html
        assert "Visiter l&#39;annonce" in html or "Visiter l'annonce" in html
        assert "/static/uploads/product_videos/demo_prod.mp4" in html
        assert "/static/uploads/rentals/visite_appart.mp4" in html
        assert f"/shop/product/{prod_id}" in html
        assert "/location/studio-moderne-visite-video" in html

    # Test du lien court /l/<id> -> redirige vers /location/<slug> (et ?preview=1 n'incrémente pas les clics)
    r_prev = client.get(f"/l/{rent_id}?preview=1", follow_redirects=False)
    assert r_prev.status_code == 302
    assert "/location/studio-moderne-visite-video" in r_prev.headers["Location"]
    with app.app_context():
        assert whatsapp_promo.get_today_clicks().get(f"rental_{rent_id}", 0) == 0

    r_real = client.get(f"/l/{rent_id}", follow_redirects=False)
    assert r_real.status_code == 302
    assert "/location/studio-moderne-visite-video" in r_real.headers["Location"]
    with app.app_context():
        assert whatsapp_promo.get_today_clicks().get(f"rental_{rent_id}", 0) == 1
