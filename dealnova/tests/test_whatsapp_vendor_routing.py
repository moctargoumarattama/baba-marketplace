"""Vérifie que les commandes WhatsApp partent bien vers le vendeur (ou le support manager en repli)."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

from flask import Flask
import pytest

from dealnova.app.extensions import db
from dealnova.app.models.product import Product
from dealnova.app.models.promo import Promo
from dealnova.app.models.rental import RentalListing
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.routes import api, booking, cart as cart_routes
from dealnova.app.services import stories
from dealnova.app.services.support_whatsapp import support_whatsapp_number


@pytest.fixture()
def wa_app():
    app = Flask(
        "whatsapp-vendor-routing-tests",
        template_folder="../app/templates",
    )
    app.config.update(
        TESTING=True,
        SECRET_KEY="wa-routing-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECURITY_RATE_LIMIT_ENABLED=False,
        SUPPORT_WHATSAPP_NUMBER="+212 600 998 877",
        ADMIN_PHONE="+212770010264",
        DELIVERY_WHATSAPP_NUMBER="212602908954",
        RENTAL_VISIT_WHATSAPP_NUMBER="212611000222",
    )
    db.init_app(app)
    app.register_blueprint(api.bp)
    app.add_url_rule("/shop/product/<int:pid>", "shop.product_detail", lambda pid: "")
    app.add_url_rule(
        "/shop/product/<int:pid>/photo/<int:image_index>/download",
        "shop.download_product_photo",
        lambda pid, image_index: "",
    )
    app.add_url_rule("/shops/<shop_slug>", "shops.shop_detail", lambda shop_slug: "")
    app.add_url_rule("/location/<slug>", "rentals.location_detail", lambda slug: "")

    with app.app_context():
        assert db.engine.url.database == ":memory:"
        db.create_all()
        yield SimpleNamespace(app=app, client=app.test_client())
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _create_vendor_offer(
    *,
    username: str,
    user_phone: str | None,
    shop_name: str,
    shop_slug: str,
    shop_phone: str | None,
    product_name: str = "Article Test",
    kind: str = "physical",
    logo: str = "",
):
    vendor = User(
        username=username,
        email=f"{username}@example.test",
        phone=user_phone,
        password_hash="hash",
        role="vendor",
        is_active=True,
    )
    db.session.add(vendor)
    db.session.flush()

    shop = Shop(
        name=shop_name,
        slug=shop_slug,
        vendor_id=vendor.id,
        contact_phone=shop_phone,
        logo=logo,
        is_active=True,
        allowed_types_json='["products","services"]',
    )
    db.session.add(shop)
    db.session.flush()

    product = Product(
        name=product_name,
        description="Description test",
        price=120,
        stock=5 if kind == "physical" else 0,
        kind=kind,
        shop_id=shop.id,
        vendor_id=vendor.id,
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return vendor, shop, product


def _wa_target_and_text(wa_url: str) -> tuple[str, str]:
    parsed = urlparse(wa_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "wa.me"
    number = parsed.path.lstrip("/")
    text = unquote((parse_qs(parsed.query).get("text") or [""])[0])
    return number, text


@pytest.mark.parametrize(
    "kind,raw_phone,expected_wa",
    [
        ("physical", "0612345678", "212612345678"),
        ("service", "07-11-22-33-44", "212711223344"),
        ("physical", "0522112233", "212522112233"),
    ],
)
def test_product_detail_orders_route_to_vendor_shop_contact_phone(wa_app, kind, raw_phone, expected_wa):
    _, shop, product = _create_vendor_offer(
        username=f"v_{kind}_{expected_wa}",
        user_phone="0699999999",
        shop_name="Boutique Atlas",
        shop_slug=f"boutique-{kind}-{expected_wa}",
        shop_phone=raw_phone,
        product_name="Produit Vendeur",
        kind=kind,
    )

    resp = wa_app.client.get(f"/api/product/{product.id}")
    assert resp.status_code == 200
    payload = resp.json["product"]

    number, text = _wa_target_and_text(payload["whatsapp_order_url"])
    assert number == expected_wa
    assert payload["whatsapp_is_vendor"] is True
    assert "212602908954" not in payload["whatsapp_order_url"]
    assert "212600998877" not in payload["whatsapp_order_url"]
    assert shop.name in text
    assert product.name in text


def test_product_detail_uses_vendor_user_phone_when_shop_contact_missing(wa_app):
    _, _, product = _create_vendor_offer(
        username="v_user_fallback",
        user_phone="0798765432",
        shop_name="Boutique Médina",
        shop_slug="boutique-medina",
        shop_phone="",
        product_name="Article Sans ShopPhone",
    )

    resp = wa_app.client.get(f"/api/product/{product.id}")
    assert resp.status_code == 200
    payload = resp.json["product"]

    number, _ = _wa_target_and_text(payload["whatsapp_order_url"])
    assert number == "212798765432"
    assert payload["whatsapp_is_vendor"] is True
    assert payload["shop"]["contact_phone"] == "0798765432"


def test_product_detail_falls_back_to_support_manager_when_no_vendor_phone(wa_app):
    _, shop, product = _create_vendor_offer(
        username="v_no_phone",
        user_phone=None,
        shop_name="Boutique Sans Num",
        shop_slug="boutique-sans-num",
        shop_phone="",
        product_name="Produit Sans Téléphone",
    )

    resp = wa_app.client.get(f"/api/product/{product.id}")
    assert resp.status_code == 200
    payload = resp.json["product"]

    number, text = _wa_target_and_text(payload["whatsapp_order_url"])
    assert number == "212600998877"
    assert payload["whatsapp_is_vendor"] is False
    assert "212602908954" not in payload["whatsapp_order_url"]
    assert shop.name in text


def test_shop_detail_whatsapp_normalizes_vendor_phone_and_falls_back_to_support(wa_app):
    _, shop_ok, _ = _create_vendor_offer(
        username="v_shop_ok",
        user_phone="0600000000",
        shop_name="Boutique Norm",
        shop_slug="boutique-norm",
        shop_phone="06 44 55 66 77",
    )
    _, shop_empty, _ = _create_vendor_offer(
        username="v_shop_empty",
        user_phone="",
        shop_name="Boutique Vide",
        shop_slug="boutique-vide",
        shop_phone="",
    )

    resp_ok = wa_app.client.get(f"/api/shop/{shop_ok.slug}")
    assert resp_ok.status_code == 200
    num_ok, _ = _wa_target_and_text(resp_ok.json["shop"]["whatsapp_url"])
    assert num_ok == "212644556677"
    assert resp_ok.json["shop"]["whatsapp_is_vendor"] is True

    resp_empty = wa_app.client.get(f"/api/shop/{shop_empty.slug}")
    assert resp_empty.status_code == 200
    num_empty, text_empty = _wa_target_and_text(resp_empty.json["shop"]["whatsapp_url"])
    assert num_empty == "212600998877"
    assert resp_empty.json["shop"]["whatsapp_is_vendor"] is False
    assert "212602908954" not in resp_empty.json["shop"]["whatsapp_url"]
    assert shop_empty.name in text_empty


def test_stories_route_to_vendor_or_support_manager_never_hardcoded_fallback(wa_app):
    _, shop_with_phone, prod_with_phone = _create_vendor_offer(
        username="v_story_ok",
        user_phone="0611111111",
        shop_name="Story Shop",
        shop_slug="story-shop",
        shop_phone="0655443322",
        product_name="Produit Story",
        logo="logo.png",
    )
    _, _, prod_no_phone = _create_vendor_offer(
        username="v_story_none",
        user_phone=None,
        shop_name="Story Sans Tel",
        shop_slug="story-sans-tel",
        shop_phone=None,
        product_name="Produit Story Repli",
        logo="logo2.png",
    )
    promo = Promo(
        product_id=prod_with_phone.id,
        type="percentage",
        value=20,
        status="approved",
        end_date=datetime.utcnow() + timedelta(days=2),
    )
    db.session.add(promo)

    rental = RentalListing(
        owner_id=shop_with_phone.vendor_id,
        shop_id=shop_with_phone.id,
        title="Appartement Agdal",
        slug="appartement-agdal-story",
        description="Bel appartement",
        listing_type="monthly",
        property_type="apartment",
        city="Rabat",
        rent_cents=400000,
        status="active",
        is_active=True,
        expires_at=datetime.utcnow() + timedelta(days=10),
    )
    db.session.add(rental)
    db.session.commit()

    with wa_app.app.test_request_context("/"):
        story_ok = stories._format_product_story(prod_with_phone, is_24h=True)
        num_story_ok, _ = _wa_target_and_text(story_ok["whatsapp_url"])
        assert num_story_ok == "212655443322"

        promo_story = stories._format_promo_story(prod_with_phone, promo, is_24h=True)
        num_promo, _ = _wa_target_and_text(promo_story["whatsapp_url"])
        assert num_promo == "212655443322"

        story_fallback = stories._format_product_story(prod_no_phone, is_24h=True)
        num_fallback, fallback_msg = _wa_target_and_text(story_fallback["whatsapp_url"])
        assert num_fallback == "212600998877"
        assert "212771182279" not in story_fallback["whatsapp_url"]
        assert "Story Sans Tel" in fallback_msg

        rental_story = stories._format_rental_story(rental, None, is_24h=True)
        num_rental, _ = _wa_target_and_text(rental_story["whatsapp_url"])
        assert num_rental == "212611000222"
        assert "212771182279" not in rental_story["whatsapp_url"]

        pool = stories.build_homepage_stories_pool()
        by_id = {item["id"]: item for item in (pool["stories_24h"] + pool["stories_recent"])}
        assert f"shop_{shop_with_phone.id}" in by_id
        num_shop_story, _ = _wa_target_and_text(by_id[f"shop_{shop_with_phone.id}"]["whatsapp_url"])
        assert num_shop_story == "212655443322"
        assert all("212771182279" not in item["whatsapp_url"] for item in by_id.values())


def test_cart_and_booking_use_vendor_user_phone_and_booking_support_fallback(wa_app):
    vendor_only = SimpleNamespace(
        id=10,
        name="Boutique Compte Vendeur",
        contact_phone="",
        vendor=SimpleNamespace(phone="0688776655"),
    )
    prod_vendor = SimpleNamespace(id=100, name="Produit V", shop=vendor_only)
    checkout = cart_routes.prepare_vendor_whatsapp_checkout(
        [{"product": prod_vendor, "quantity": 1, "unit_price_cents": 5000}],
        {},
    )
    group = checkout["shop_groups"][0]
    assert group["phone_available"] is True
    assert _wa_target_and_text(group["whatsapp_url"])[0] == "212688776655"

    # Booking service: contact_phone -> vendor.phone -> support_whatsapp_number
    assert booking._whatsapp_number_from_shop(SimpleNamespace(shop=SimpleNamespace(contact_phone="0611223344"))) == "212611223344"
    assert booking._whatsapp_number_from_shop(SimpleNamespace(shop=vendor_only)) == "212688776655"
    assert booking._whatsapp_number_from_shop(SimpleNamespace(shop=SimpleNamespace(contact_phone=""))) == support_whatsapp_number()


def test_home_catalog_footer_targets_support_while_delivery_keeps_delivery_number(wa_app):
    from pathlib import Path
    from jinja2 import DictLoader, ChoiceLoader, FileSystemLoader
    from flask import render_template

    templates_dir = Path(__file__).resolve().parents[1] / "app" / "templates"
    app = wa_app.app
    app.jinja_loader = ChoiceLoader([
        DictLoader({"partials/_catalog_panel.html": "", "partials/_home_storefront.html": "",
                    "partials/_home_stories.html": "", "partials/_public_bottom_nav.html": "",
                    "partials/_support_issue_fab.html": "", "partials/_assistant_widget.html": ""}),
        FileSystemLoader(templates_dir),
    ])
    app.jinja_env.globals["url_for"] = lambda ep, **kw: f"/{ep}"
    app.jinja_env.globals.setdefault("csrf_token", lambda: "csrf-test")

    with app.test_request_context("/"):
        html = render_template(
            "home.html",
            t=lambda x: x,
            support_whatsapp_number=support_whatsapp_number,
            current_lang="fr",
            rtl_langs=[],
            current_user=SimpleNamespace(is_authenticated=False, role=None),
            app_static_version="test",
            pwa_session_scope="anon",
            cart_count=0,
            data=[],
            stories=[],
            delivery_loader_url="/delivery",
        )

    delivery_block = html.split('id="uDeliveryBody"', 1)[1].split('id="uModalFooter"', 1)[0]
    footer_block = html.split('id="uModalFooter"', 1)[1].split('</footer>', 1)[0]
    assert "https://wa.me/212602908954" in delivery_block
    assert "https://wa.me/212600998877" in footer_block
    assert "212602908954" not in footer_block
