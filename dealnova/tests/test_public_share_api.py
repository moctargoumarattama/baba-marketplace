from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from dealnova.app.models.product import Product
from dealnova.app.routes import api


@pytest.fixture()
def share_app(monkeypatch):
    app = Flask("public-share-api-tests")
    app.config.update(TESTING=True, SECRET_KEY="share-tests", SECURITY_RATE_LIMIT_ENABLED=False)
    app.register_blueprint(api.bp)
    app.add_url_rule("/shop/product/<int:pid>", "shop.product_detail", lambda pid: "")
    app.add_url_rule("/shops/<shop_slug>", "shops.shop_detail", lambda shop_slug: "")
    monkeypatch.setattr(api, "_active_promo_map", lambda _ids: {})
    return app


@pytest.mark.parametrize("kind,pid", [("physical", 101), ("service", 202)])
def test_product_and_service_api_share_their_public_page_not_the_api_or_home(share_app, monkeypatch, kind, pid):
    product = SimpleNamespace(id=pid, is_active=True, name="Offre de test", description="Description",
                              price_cents=2500, image_file="", shop=None, category=None, stock=4, kind=kind)
    query = Mock()
    query.get_or_404.return_value = product
    monkeypatch.setattr(api, "Product", SimpleNamespace(query=query))

    response = share_app.test_client().get(f"/api/product/{pid}", base_url="https://market.example.test")

    assert response.status_code == 200
    assert response.json["product"]["share_url"] == f"https://market.example.test/shop/product/{pid}"
    query.get_or_404.assert_called_once_with(pid)


@pytest.mark.parametrize("lookup", ["atelier-test", "7"])
def test_shop_api_always_shares_canonical_slug_even_when_loaded_by_id(share_app, monkeypatch, lookup):
    shop = SimpleNamespace(id=7, name="Atelier de test", slug="atelier-test", closed_until=None,
                           is_open=True, contact_phone="", logo="", banner="", description="",
                           address="Rabat", is_verified=False)
    shop_query = Mock()
    shop_query.filter_by.return_value = shop_query
    shop_query.first.return_value = shop
    monkeypatch.setattr(api, "Shop", SimpleNamespace(query=shop_query))
    product_query = Mock()
    for method in ("filter_by", "options", "order_by", "filter", "limit"):
        getattr(product_query, method).return_value = product_query
    product_query.all.return_value = []
    product_query.count.return_value = 0
    monkeypatch.setattr(api, "Product", SimpleNamespace(query=product_query, category=Product.category,
                                                       created_at=Product.created_at, id=Product.id, kind=Product.kind))

    response = share_app.test_client().get(f"/api/shop/{lookup}?preview=1", base_url="https://market.example.test")

    assert response.status_code == 200
    assert response.json["shop"]["share_url"] == "https://market.example.test/shops/atelier-test"
    assert response.json["products"] == []


@pytest.mark.parametrize("video_file,expected_url,expected_has_video", [
    ("demo.mp4", "/static/uploads/product_videos/demo.mp4", True),
    ("uploads/product_videos/custom.mp4", "/static/uploads/product_videos/custom.mp4", True),
    ("/static/videos/sample.mp4", "/static/videos/sample.mp4", True),
    ("", None, False),
    (None, None, False),
])
def test_product_api_returns_video_url_and_has_video(share_app, monkeypatch, video_file, expected_url, expected_has_video):
    product = SimpleNamespace(
        id=303, is_active=True, name="Produit avec vidéo", description="Description",
        price_cents=1500, image_file="", video_file=video_file, shop=None, category=None,
        stock=5, kind="physical"
    )
    query = Mock()
    query.get_or_404.return_value = product
    monkeypatch.setattr(api, "Product", SimpleNamespace(query=query))

    response = share_app.test_client().get("/api/product/303")

    assert response.status_code == 200
    data = response.json["product"]
    assert data["video_url"] == expected_url
    assert data["has_video"] is expected_has_video

