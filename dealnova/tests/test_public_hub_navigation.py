from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask, jsonify, request
from flask import url_for

from dealnova.app.routes import cart as cart_routes
from dealnova.app.routes import shop as shop_routes
from dealnova.app.routes import shops as shops_routes
from dealnova.app.routes import rentals as rentals_routes


def test_shop_links_use_the_namespaced_url_to_avoid_root_route_collisions():
    app = Flask("shop-canonical-link-test")
    app.register_blueprint(shops_routes.bp)
    app.add_url_rule("/moctar", "legacy_login_shortcut", lambda: "login")
    with app.test_request_context("/"):
        assert url_for("shops.shop_detail", shop_slug="moctar") == "/shops/moctar"
        assert url_for("shops.shop_detail", shop_slug="local-shop") == "/shops/local-shop"


def test_rental_redirect_preserves_city_price_duration_and_page(navigation_app):
    navigation_app.register_blueprint(rentals_routes.bp)
    response = navigation_app.test_client().get("/locations", query_string={
        "city": "Rabat", "type": "monthly", "min": "2000", "max": "4000", "page": "3", "next": "https://example.test",
    })
    assert response.status_code == 302
    assert parse_qs(urlparse(response.location).query) == {
        "open": ["locations"], "city": ["Rabat"], "type": ["monthly"], "min": ["2000"], "max": ["4000"], "page": ["3"],
    }


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
    ("query", "expected"),
    [
        ({}, {"open": "products"}),
        ({"q": "  karité & savon  "}, {"open": "search", "q": "karité & savon"}),
        ({"kind": "service"}, {"open": "services", "kind": "service"}),
        ({"promo": "1"}, {"open": "promotions", "promo": "1"}),
        ({"open": "checkout", "q": "savon"}, {"open": "checkout", "q": "savon"}),
        ({"open": "services", "q": "coiffure"}, {"open": "services", "q": "coiffure"}),
        ({"open": "unknown", "next": "https://example.test"}, {"open": "products"}),
    ],
)
def test_catalogue_redirect_keeps_public_navigation_state(navigation_app, query, expected):
    response = navigation_app.test_client().get("/shop/", query_string=query)

    assert response.status_code == 302
    target = urlparse(response.location)
    assert target.path == "/"
    assert not target.netloc
    assert parse_qs(target.query) == {key: [value] for key, value in expected.items()}


@pytest.mark.parametrize("path", ["/shop/", "/shop/promotions"])
def test_catalogue_redirect_keeps_filters_and_detail_links(navigation_app, path):
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
        "pdetail": "7",
        "sdetail": "boutique-rabat",
        "slug": "boutique-rabat",
    }

    response = navigation_app.test_client().get(path, query_string=filters, follow_redirects=True)

    assert response.json == {"open": "promotions", **filters}

