"""Following the assistant's catalogue link preserves search and pagination."""
from urllib.parse import parse_qs, urlparse

import pytest

from dealnova.tests.test_public_seo import Page
from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


@pytest.fixture(scope="module")
def shared_catalogue(tmp_path_factory):
    with isolated_vendor_application(tmp_path_factory.mktemp("assistant-shared-catalogue")) as fixture:
        from dealnova.app.models.product import Product
        from dealnova.app.models.shop import Shop

        fixture.app.config.update(ANALYTICS_ENABLED=False, GEMINI_API_KEY="", PUBLIC_BASE_URL="http://localhost")
        with fixture.app.app_context():
            fixture.db.session.get(Shop, fixture.ids.shop).address = "Centre, Salé"
            products = [Product(name=f"Crème locale {index:02}", description="Karité naturel",
                                price=25 + index, kind="physical", stock=2, is_active=True,
                                vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                                category_id=fixture.ids.physical) for index in range(15)]
            fixture.db.session.add_all(products)
            fixture.db.session.commit()
            fixture.product_ids = {entry.id for entry in products}
        fixture.client = fixture.app.test_client()
        yield fixture


def _offer_ids(page):
    prefix = "/shop/product/"
    return {int(urlparse(attrs["href"]).path[len(prefix):]) for attrs in page.attrs("a")
            if attrs.get("href") and urlparse(attrs["href"]).path.startswith(prefix)}


def test_shared_assistant_search_preserves_smart_mode_in_page_form_and_pagination(shared_catalogue):
    params = {"q": "cremes karites", "city": "Sale", "smart": "true"}
    response = shared_catalogue.client.get("/produits", query_string=params)
    assert response.status_code == 200
    page = Page(response)
    canonical = parse_qs(urlparse(page.canonical()).query)
    assert canonical["smart"] == ["1"]
    assert canonical["q"] == ["cremes karites"]
    assert any(attrs.get("name") == "smart" and attrs.get("type") == "hidden" and attrs.get("value") == "1"
               for attrs in page.attrs("input"))
    assert any(attrs.get("name") == "robots" and attrs.get("content") == "noindex,follow"
               for attrs in page.attrs("meta"))

    next_url = next(attrs["href"] for attrs in page.attrs("a") if attrs.get("rel") == "next")
    assert parse_qs(urlparse(next_url).query)["smart"] == ["1"]
    second = shared_catalogue.client.get(next_url)
    assert second.status_code == 200
    second_page = Page(second)
    assert len(_offer_ids(page)) == 12
    assert len(_offer_ids(second_page)) == 3
    assert _offer_ids(page) | _offer_ids(second_page) == shared_catalogue.product_ids
    assert parse_qs(urlparse(second_page.canonical()).query)["smart"] == ["1"]

    submitted = shared_catalogue.client.get("/produits", query_string={**params, "smart": "1", "sort": "low"})
    assert submitted.status_code == 200
    assert len(_offer_ids(Page(submitted))) == 12


def test_ordinary_catalogue_does_not_enable_smart_mode(shared_catalogue):
    plain = shared_catalogue.client.get("/produits", query_string={"q": "cremes karites", "city": "Sale"})
    assert plain.status_code == 200
    page = Page(plain)
    assert _offer_ids(page) == set()
    assert not any(attrs.get("name") == "smart" for attrs in page.attrs("input"))
    assert "smart" not in parse_qs(urlparse(page.canonical()).query)
