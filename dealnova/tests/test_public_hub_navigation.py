from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask, jsonify, request
from flask import url_for

from dealnova.app.routes import cart as cart_routes
from dealnova.app.routes import shop as shop_routes
from dealnova.app.routes import shops as shops_routes


def test_shop_links_use_the_namespaced_url_to_avoid_root_route_collisions():
    app = Flask("shop-canonical-link-test")
    app.register_blueprint(shops_routes.bp)
    app.add_url_rule("/moctar", "legacy_login_shortcut", lambda: "login")
    with app.test_request_context("/"):
        assert url_for("shops.shop_detail", shop_slug="moctar") == "/shops/moctar"
        assert url_for("shops.shop_detail", shop_slug="local-shop") == "/shops/local-shop"


@pytest.fixture()
def navigation_app():
    # Register actual route blueprints without starting the application or its DB.
    app = Flask("public-hub-navigation-tests")
    app.config.update(TESTING=True, SECRET_KEY="navigation-test-secret")
    app.register_blueprint(shop_routes.bp, url_prefix="/shop")
    app.register_blueprint(cart_routes.bp)

    @app.route("/")
    def landing():
        return jsonify(request.args.to_dict())

    # Production always registers these public document endpoints. Stub only
    # their responses while exercising the real legacy redirect behavior.
    for endpoint, path in {
        "public_catalog_pages.products": "/produits",
        "public_catalog_pages.services": "/services",
        "public_catalog_pages.promotions": "/promotions",
        "public_catalog_pages.search": "/recherche",
        "rentals.locations_home": "/locations",
        "shops.list_shops": "/shops",
    }.items():
        app.add_url_rule(path, endpoint=endpoint, view_func=landing)

    return app


@pytest.mark.parametrize(
    ("path", "expected_universe"),
    [("/cart/", "cart"), ("/cart/checkout", "checkout")],
)
@pytest.mark.parametrize("cart_items", [{}, {"7": 2}])
def test_cart_links_keep_the_intended_drawer(navigation_app, path, expected_universe, cart_items):
    client = navigation_app.test_client()
    with client.session_transaction() as session:
        session["cart_guest"] = cart_items

    response = client.get(path, follow_redirects=True)

    assert response.status_code == 200
    assert response.json == {"open": expected_universe}
    with client.session_transaction() as session:
        assert session["cart_guest"] == cart_items


@pytest.mark.parametrize(
    ("query", "status", "path", "expected"),
    [
        ({}, 301, "/produits", {}),
        ({"q": "  karité & savon  "}, 301, "/recherche", {"q": "karité & savon"}),
        ({"kind": "service"}, 301, "/services", {"kind": "service"}),
        ({"promo": "1"}, 301, "/promotions", {"promo": "1"}),
        ({"open": "checkout", "q": "savon"}, 302, "/", {"open": "checkout", "q": "savon"}),
        ({"open": "services", "q": "coiffure"}, 301, "/services", {"q": "coiffure"}),
        ({"open": "locations", "city": "Rabat"}, 301, "/locations", {"city": "Rabat"}),
        ({"open": "shops"}, 301, "/shops", {}),
        ({"open": "unknown", "next": "https://example.test"}, 301, "/produits", {}),
    ],
)
def test_catalogue_redirect_keeps_public_navigation_state(navigation_app, query, status, path, expected):
    response = navigation_app.test_client().get("/shop/", query_string=query)

    assert response.status_code == status
    target = urlparse(response.location)
    assert target.path == path
    assert not target.netloc
    assert parse_qs(target.query) == {key: [value] for key, value in expected.items()}


@pytest.mark.parametrize("path", ["/shop/", "/shop/promotions"])
def test_catalogue_redirect_keeps_filters_on_the_canonical_catalogue(navigation_app, path):
    filters = {
        "q": "savon",
        "cat": "3",
        "sort": "price_asc",
        "kind": "physical",
        "min_price": "10",
        "max_price": "250",
        "promo": "1",
        "stock": "1",
        "shop": "9",
        "page": "2",
    }

    response = navigation_app.test_client().get(path, query_string=filters)

    assert response.status_code == 301
    assert urlparse(response.location).path == "/promotions"
    assert parse_qs(urlparse(response.location).query) == {key: [value] for key, value in filters.items()}
    assert navigation_app.test_client().get(response.location).json == filters


@pytest.mark.parametrize("path", ["/shop/", "/shop/promotions"])
@pytest.mark.parametrize("details", [{"pdetail": "7"}, {"sdetail": "boutique-rabat"}, {"slug": "boutique-rabat"}])
def test_old_detail_links_still_open_the_popup_with_their_catalogue_filters(navigation_app, path, details):
    filters = {"q": "savon", "sort": "price_asc", "page": "2", "promo": "1", **details}
    response = navigation_app.test_client().get(path, query_string=filters)

    assert response.status_code == 302
    target = urlparse(response.location)
    assert target.path == "/" and not target.netloc
    assert parse_qs(target.query) == {key: [value] for key, value in {"open": "promotions", **filters}.items()}
    assert navigation_app.test_client().get(response.location).json == {"open": "promotions", **filters}

