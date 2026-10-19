from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, render_template, render_template_string


ROOT = Path(__file__).resolve().parents[1]


class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def attributes(self, tag):
        return [attrs for name, attrs in self.tags if name == tag]


def offer(pid, *, kind="physical", stock=3, promo=False, price=100, final=100, image=""):
    return ({
        "id": pid, "name": f"Offre {pid}", "kind": kind, "stock": stock,
        "promo_active": promo, "price": price, "image_file": image,
    }, final, 0)


@pytest.fixture()
def storefront():
    # Exercise Jinja output without initializing the production app or database.
    app = Flask("storefront-tests", template_folder=str(ROOT / "app/templates"))
    routes = {
        "landing": "/", "global_search": "/search",
        "public_catalog_pages.products": "/produits", "public_catalog_pages.services": "/services",
        "public_catalog_pages.promotions": "/promotions", "public_catalog_pages.search": "/recherche",
        "rentals.locations_home": "/locations",
        "api.public_catalog": "/api/catalog",
        "shop.product_detail": "/shop/product/<int:pid>",
        "booking.book": "/book/<int:pid>",
        "shops.list_shops": "/shops", "shops.shop_detail": "/shops/<shop_slug>",
        "auth.login": "/login", "auth.register": "/register", "auth.logout": "/logout",
        "auth.vendor_access": "/vendor-access", "auth.support_whatsapp": "/support/whatsapp",
        "auth.public_help": "/support/help",
        "admin_users.admin_dashboard": "/admin", "vendor.dashboard": "/vendor",
        "set_language_route": "/lang/<lang_code>",
    }
    for endpoint, rule in routes.items():
        app.add_url_rule(rule, endpoint=endpoint, view_func=lambda **kwargs: "")

    def render(*, products=None, services=None, promotions=None, shops=None, role=None, cards_only=False):
        with app.test_request_context("/"):
            renderer = render_template_string if cards_only else render_template
            template = (
                "{% from 'partials/_home_offer_card.html' import offer_card with context %}"
                "{% for item in offer_items %}{{ offer_card(item) }}{% endfor %}"
                if cards_only else "partials/_home_storefront.html"
            )
            return renderer(
                template,
                offer_items=(products or []) + (services or []),
                t=lambda text: text,
                image_variant=lambda filename, size: filename,
                csrf_token=lambda: "storefront-csrf-token",
                current_user=SimpleNamespace(
                    is_authenticated=role is not None, role=role, username="Utilisateur <test>",
                ),
                current_lang="fr", current_year=2026, app_static_version="test", cart_count=0,
                delivery_loader_url="/delivery/whatsapp",
                hub_items=SimpleNamespace(
                    products=products or [], services=services or [], promotions=promotions or [],
                ),
                featured_shops=shops or [],
            )

    return render


def test_guest_can_reach_vendor_login_without_customer_registration(storefront):
    page = Markup(storefront())
    links = {attrs.get("href") for attrs in page.attributes("a")}

    assert {"/login", "/vendor-access"} <= links
    assert "/register" not in links
    assert "/vendor" not in links
    assert not any(attrs.get("action") == "/logout" for attrs in page.attributes("form"))


@pytest.mark.parametrize("role", [None, "customer", "vendor", "admin", "manager"])
def test_footer_help_link_uses_the_public_help_page_for_every_role(storefront, role):
    page = Markup(storefront(role=role))

    assert any(attrs.get("href") == "/support/help" for attrs in page.attributes("a"))
    assert not any(attrs.get("href") == "/support/whatsapp" for attrs in page.attributes("a"))


def test_vendor_keeps_dashboard_and_protected_logout(storefront):
    source = storefront(role="vendor")
    page = Markup(source)

    assert any(attrs.get("href") == "/vendor" for attrs in page.attributes("a"))
    assert any(attrs.get("action") == "/logout" and attrs.get("method") == "post"
               for attrs in page.attributes("form"))
    assert any(attrs.get("name") == "csrf_token" and attrs.get("value") == "storefront-csrf-token"
               for attrs in page.attributes("input"))
    assert "Utilisateur &lt;test&gt;" in source
    assert not any(attrs.get("href") == "/login" for attrs in page.attributes("a"))


def test_stock_and_service_offers_keep_the_correct_actions(storefront):
    source = storefront(products=[offer(101), offer(102, stock=0)], services=[offer(103, kind="service")], cards_only=True)
    page = Markup(source)

    assert [attrs["data-cart-add-btn"] for attrs in page.attributes("button")
            if "data-cart-add-btn" in attrs] == ["101"]
    assert "Indisponible" in source
    assert any(attrs.get("href") == "/book/103" for attrs in page.attributes("a"))
    for pid in (101, 102, 103):
        assert any(attrs.get("href") == f"/shop/product/{pid}"
                   and attrs.get("data-open-product-detail") == str(pid)
                   for attrs in page.attributes("a"))


def test_promo_badge_and_struck_price_require_an_actual_discount(storefront):
    source = storefront(products=[
        offer(101, promo=False, final=80),
        offer(102, promo=True, final=100),
        offer(103, promo=True, final=75),
    ], cards_only=True)

    assert source.count('class="hub-offer-tag"') == 1
    assert source.count("<del>") == 1
    assert "<del>100.00 DH</del>" in source
    assert "75 <small>DH</small>" in source


def test_cover_uses_first_product_image_and_informative_alt(storefront):
    page = Markup(storefront(products=[offer(101, image="premiere.jpg|seconde.jpg")], cards_only=True))
    image = next(attrs for attrs in page.attributes("img") if attrs.get("alt") == "Offre 101")

    assert image["src"] == "/static/uploads/premiere.jpg"
    assert image["loading"] == "lazy"


def test_homepage_does_not_display_product_or_service_previews(storefront):
    source = storefront(products=[offer(101)], services=[offer(103, kind="service")])
    page = Markup(source)

    assert 'class="hub-empty"' not in source
    assert 'class="hub-product"' not in source
    assert 'id="hubPromotionsTitle"' not in source
    assert not any("data-home-offers" in attrs or "data-home-rotation-url" in attrs
                   for _, attrs in page.tags)
    assert not any("data-cart-add-btn" in attrs for attrs in page.attributes("button"))
    assert any(attrs.get("data-open-universe") == "shops" for attrs in page.attributes("a"))


def test_navigation_keeps_all_universes_and_unique_search_controls(storefront):
    page = Markup(storefront())
    ids = [attrs["id"] for _, attrs in page.tags if "id" in attrs]
    universes = {attrs["data-open-universe"] for _, attrs in page.tags if "data-open-universe" in attrs}

    assert len(ids) == len(set(ids))
    assert universes == {"products", "services", "locations", "shops", "delivery", "promotions", "search"}
    assert sum(attrs.get("id") == "homeSearchInput" for attrs in page.attributes("input")) == 1
    assert any(attrs.get("for") == "homeSearchInput" for attrs in page.attributes("label"))
    assert any(attrs.get("action") == "/search" and attrs.get("method") == "get"
               for attrs in page.attributes("form"))


def test_shops_are_accessible_from_the_category_without_a_homepage_list(storefront):
    source = storefront(shops=[{
        "name": "Commerce & voisinage", "slug": "commerce-rabat",
        "logo": "commerce-logo.webp", "banner": "commerce-banner.webp", "product_count": 7,
    }])
    page = Markup(source)

    assert not any("data-open-shop-detail" in attrs for attrs in page.attributes("a"))
    assert "hub-shops-grid" not in source
    assert "Commerce &amp; voisinage" not in source
    assert any(attrs.get("data-open-universe") == "shops" and attrs.get("class") == "hub-category"
               for attrs in page.attributes("a"))


def test_six_category_links_remain_crawlable_without_changing_popup_actions(storefront):
    page = Markup(storefront())
    cards = [attrs for attrs in page.attributes("a") if attrs.get("class") == "hub-category"]

    assert len(cards) == 6
    assert {attrs["data-open-universe"]: attrs["href"] for attrs in cards} == {
        "products": "/produits", "services": "/services", "locations": "/locations",
        "shops": "/shops", "delivery": "/?open=delivery", "promotions": "/promotions",
    }
