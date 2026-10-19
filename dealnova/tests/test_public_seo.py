"""Public SEO regression checks against a disposable database, never .env data."""

from datetime import datetime, timedelta
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pytest

from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


class Page(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.tags = []
        self.title = ""
        self._in_title = False
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def attrs(self, tag):
        return [attrs for name, attrs in self.tags if name == tag]

    def canonical(self):
        values = [attrs["href"] for attrs in self.attrs("link") if attrs.get("rel") == "canonical"]
        assert len(values) == 1, "A public document must declare one unambiguous canonical URL"
        return values[0]

    def description(self):
        return next(attrs["content"] for attrs in self.attrs("meta") if attrs.get("name") == "description")


@pytest.fixture(scope="module")
def public_seo(tmp_path_factory):
    with isolated_vendor_application(tmp_path_factory.mktemp("public-seo")) as fixture:
        from dealnova.app.models.product import Product
        from dealnova.app.models.rental import RentalListing
        from dealnova.app.models.shop import Shop
        from dealnova.app.models.user import User

        fixture.app.config["PUBLIC_BASE_URL"] = "https://www.babamarket.ma"
        fixture.app.config["ANALYTICS_ENABLED"] = False
        with fixture.app.app_context():
            shop = fixture.db.session.get(Shop, fixture.ids.shop)
            shop.set_allowed_types(["products", "services", "location"])
            hidden_vendor = User(username="hidden-vendor", email="hidden@example.test", role="vendor",
                                 is_active=True, password_hash="unused-test-password")
            fixture.db.session.add(hidden_vendor)
            fixture.db.session.flush()
            hidden_shop = Shop(name="Boutique masquee SEO", slug="hidden-seo", vendor_id=hidden_vendor.id,
                               is_active=False, primary_type="products")
            fixture.db.session.add(hidden_shop)
            fixture.db.session.flush()
            products = [Product(name=f"Article SEO {index:02}", description=f"Description article SEO {index:02}",
                                kind="physical", price=25 + index, stock=3, is_active=True,
                                category_id=fixture.ids.physical, vendor_id=fixture.ids.vendor, shop_id=shop.id)
                        for index in range(14)]
            service = Product(name="Service SEO coiffure", description="Prestation SEO avec rendez-vous",
                              kind="service", price=100, stock=0, is_active=True,
                              category_id=fixture.ids.service, vendor_id=fixture.ids.vendor, shop_id=shop.id)
            inactive = Product(name="Produit desactive SEO", kind="physical", price=30, is_active=False,
                               stock=1, vendor_id=fixture.ids.vendor, shop_id=shop.id)
            hidden = Product(name="Produit boutique masquee SEO", kind="physical", price=30, is_active=True,
                             stock=1, vendor_id=hidden_vendor.id, shop_id=hidden_shop.id)
            fixture.db.session.add_all([*products, service, inactive, hidden])
            fixture.db.session.flush()

            def rental(slug, **changes):
                values = dict(title=f"Location SEO {slug}", slug=slug, description="Logement SEO a Rabat",
                              owner_id=fixture.ids.vendor, shop_id=shop.id, city="Rabat", rent_cents=200000,
                              is_active=True, status="active", expires_at=datetime.utcnow() + timedelta(days=10))
                values.update(changes)
                return RentalListing(**values)

            rentals = [rental("active-seo"), rental("reserved-seo", status="reserved"),
                       rental("expired-seo", expires_at=datetime.utcnow() - timedelta(days=1)),
                       rental("inactive-seo", is_active=False), rental("archived-seo", status="archived"),
                       rental("hidden-shop-seo", shop_id=hidden_shop.id, owner_id=hidden_vendor.id)]
            fixture.db.session.add_all(rentals)
            fixture.db.session.commit()
            fixture.records = SimpleNamespace(product=products[0].id, service=service.id,
                                              inactive=inactive.id, hidden=hidden.id)
        fixture.client = fixture.app.test_client()
        yield fixture


def test_public_catalogs_are_distinct_indexable_documents(public_seo):
    documents = []
    for path, title_word in (("/produits", "Produits"), ("/services", "Services"), ("/locations", "Locations")):
        response = public_seo.client.get(path)
        assert response.status_code == 200
        page = Page(response)
        assert title_word.casefold() in page.title.casefold()
        assert "dealnova" not in page.title.casefold()
        assert page.description()
        assert urlparse(page.canonical()).path == path
        assert not urlparse(page.canonical()).query
        assert not any("noindex" in attrs.get("content", "").lower() for attrs in page.attrs("meta")
                       if attrs.get("name") == "robots")
        documents.append((page.title, page.description()))
    assert len({title for title, _ in documents}) == 3
    assert len({description for _, description in documents}) == 3


@pytest.mark.parametrize("record", ["product", "service"])
def test_offer_content_and_canonical_do_not_depend_on_googlebot(public_seo, record):
    path = f"/shop/product/{getattr(public_seo.records, record)}"
    pages = []
    for user_agent in ("Mozilla/5.0 Mobile Safari", "Googlebot/2.1 (+http://www.google.com/bot.html)"):
        response = public_seo.client.get(path, headers={"User-Agent": user_agent})
        assert response.status_code == 200 and response.mimetype == "text/html"
        page = Page(response)
        assert urlparse(page.canonical()).path == path
        assert "SEO" in page.title and page.description()
        assert not any("noindex" in attrs.get("content", "").lower() for attrs in page.attrs("meta")
                       if attrs.get("name") == "robots")
        pages.append((page.title, page.description(), page.canonical()))
    assert pages[0] == pages[1]


@pytest.mark.parametrize("record", ["inactive", "hidden"])
@pytest.mark.parametrize("user_agent", ["Mozilla/5.0", "Googlebot/2.1"])
def test_hidden_offers_are_not_public_even_when_id_is_known(public_seo, record, user_agent):
    response = public_seo.client.get(f"/shop/product/{getattr(public_seo.records, record)}",
                                     headers={"User-Agent": user_agent})
    assert response.status_code == 404


def test_catalog_html_contains_links_to_offers_and_following_pages(public_seo):
    response = public_seo.client.get("/produits")
    assert response.status_code == 200
    page = Page(response)
    links = [attrs["href"] for attrs in page.attrs("a") if attrs.get("href")]
    assert any(urlparse(link).path.startswith("/shop/product/") for link in links)
    following = next(link for link in links if urlparse(link).path == "/produits"
                     and parse_qs(urlparse(link).query).get("page") == ["2"])
    second = public_seo.client.get(following)
    assert second.status_code == 200
    assert parse_qs(urlparse(Page(second).canonical()).query).get("page") == ["2"]


def test_robots_and_sitemap_only_expose_valid_public_urls(public_seo):
    robots = public_seo.client.get("/robots.txt")
    assert robots.status_code == 200 and robots.mimetype == "text/plain"
    assert "Sitemap: https://www.babamarket.ma/sitemap.xml" in robots.get_data(as_text=True)
    response = public_seo.client.get("/sitemap.xml")
    assert response.status_code == 200
    document = ElementTree.fromstring(response.data)
    urls = [entry.text for entry in document.findall("{*}url/{*}loc")]
    assert len(urls) == len(set(urls))
    assert all(url.startswith("https://www.babamarket.ma/") for url in urls)
    paths = {urlparse(url).path for url in urls}
    assert {"/", "/produits", "/services", "/locations", "/shops"} <= paths
    assert not {"/shop/", "/shop/promotions", "/search", "/recherche"} & paths
    for record in ("product", "service"):
        assert f"/shop/product/{getattr(public_seo.records, record)}" in paths
    for record in ("inactive", "hidden"):
        assert f"/shop/product/{getattr(public_seo.records, record)}" not in paths
    assert {"/location/active-seo", "/location/reserved-seo"} <= paths
    assert not {f"/location/{slug}" for slug in
                ("expired-seo", "inactive-seo", "archived-seo", "hidden-shop-seo")} & paths
    assert "/shops/hidden-seo" not in paths


@pytest.mark.parametrize("legacy,expected", [
    ("/shop/", "/produits"), ("/shop/?kind=service", "/services"),
    ("/shop/?q=savon", "/recherche"), ("/shop/promotions", "/promotions"),
])
def test_legacy_catalogs_permanently_redirect_to_public_documents(public_seo, legacy, expected):
    response = public_seo.client.get(legacy)
    assert response.status_code == 301
    assert urlparse(response.location).path == expected
    assert public_seo.client.get(response.location).status_code == 200


def test_rental_partial_contract_keeps_working_for_existing_popups(public_seo):
    response = public_seo.client.get("/locations", headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "active-seo" in html
    assert "<!doctype html" not in html.lower()
    assert "expired-seo" not in html and "hidden-shop-seo" not in html


def test_rental_legacy_filters_normalize_to_one_canonical_shape(public_seo):
    response = public_seo.client.get("/locations?type=monthly&min=100&max=300")
    assert response.status_code == 200
    page = Page(response)
    canonical = urlparse(page.canonical())
    assert canonical.path == "/locations"
    filters = parse_qs(canonical.query)
    assert filters["listing_type"] == ["monthly"]
    assert float(filters["min_price"][0]) == 100
    assert float(filters["max_price"][0]) == 300
    assert not {"type", "min", "max"} & filters.keys()
    robots = next(attrs["content"] for attrs in page.attrs("meta") if attrs.get("name") == "robots")
    assert "noindex" in robots and "follow" in robots
    inputs = {attrs.get("name"): attrs.get("value") for attrs in page.attrs("input")}
    assert float(inputs["min_price"]) == 100
    assert float(inputs["max_price"]) == 300


@pytest.mark.parametrize("user_agent", [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Google-InspectionTool/1.0;)",
    "Mediapartners-Google",
])
def test_search_crawler_classification_preserves_public_access_and_private_guards(public_seo, user_agent):
    from flask import g

    headers = {"User-Agent": user_agent}
    with public_seo.app.test_client() as client:
        for path in ("/", "/produits", "/services", "/locations",
                     f"/shop/product/{public_seo.records.product}",
                     f"/shop/product/{public_seo.records.service}", "/robots.txt", "/sitemap.xml"):
            response = client.get(path, headers=headers)
            assert response.status_code == 200, path
            if path in ("/", "/produits", "/services"):
                assert g.is_bot_request is True
                assert g.analytics_visitor_id == "bot:crawler"
                assert not any(cookie.startswith("bm_vid=") for cookie in response.headers.getlist("Set-Cookie"))

        # A crawler name is an analytics label, never an authentication bypass.
        private = client.get("/vendor/dashboard", headers=headers)
        assert private.status_code == 302
        assert "/login" in urlparse(private.location).path
        assert client.get("/shop/product/2147483647", headers=headers).status_code == 404


@pytest.mark.parametrize("user_agent", ["Mozilla/5.0", "Googlebot/2.1", "Google-InspectionTool/1.0"])
@pytest.mark.parametrize("path", ["/products", "/products/"])
def test_english_products_url_preserves_filters_without_creating_another_catalog(public_seo, user_agent, path):
    query = {"q": "savon & huile", "page": "2", "_external": "https://example.test"}
    response = public_seo.client.get(path, query_string=query, headers={"User-Agent": user_agent})
    assert response.status_code == 301
    target = urlparse(response.location)
    assert not target.netloc
    assert target.path == "/produits"
    assert parse_qs(target.query) == {key: [value] for key, value in query.items()}
    assert public_seo.client.get(response.location, headers={"User-Agent": user_agent}).status_code == 200


@pytest.mark.parametrize("user_agent", ["Mozilla/5.0", "Googlebot/2.1", "Google-InspectionTool/1.0"])
def test_search_console_non_www_urls_have_working_public_redirect_chains(public_seo, user_agent):
    headers = {"User-Agent": user_agent}
    for path in ("/", "/products"):
        response = public_seo.client.get(path, base_url="https://babamarket.ma", headers=headers)
        assert response.status_code == 301
        assert response.location == "https://www.babamarket.ma" + path
        destination = public_seo.client.get(response.location, headers=headers)
        if path == "/products":
            assert destination.status_code == 301
            assert urlparse(destination.location).path == "/produits"
            destination = public_seo.client.get(destination.location, headers=headers)
        assert destination.status_code == 200
