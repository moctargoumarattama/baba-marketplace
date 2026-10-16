from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
import pytest

from dealnova.app.extensions import db
from dealnova.app.models.product import Product
from dealnova.app.models.promo import Promo
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.routes.api import bp
from dealnova.app.services import cache as cache_service
from dealnova.app.services import home_selection


@pytest.fixture()
def selection_app(monkeypatch):
    app = Flask("home-selection-tests", template_folder=str(Path(__file__).resolve().parents[1] / "app/templates"))
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, CACHE_TYPE="SimpleCache",
                      SECURITY_RATE_LIMIT_ENABLED=False)
    db.init_app(app)
    cache_service.cache.init_app(app)
    monkeypatch.setattr(cache_service, "_get_catalog_version", lambda: 1)
    app.register_blueprint(bp)
    app.jinja_env.globals.update(t=lambda value: value, image_variant=lambda filename, size: filename)
    for endpoint, rule in (("shop.product_detail", "/shop/product/<int:pid>"),
                           ("booking.book", "/booking/<int:pid>")):
        app.add_url_rule(rule, endpoint, lambda **kwargs: "")
    with app.app_context():
        assert db.engine.url.database == ":memory:"
        db.create_all()
        owner = User(username="rotation", email="rotation@example.test", password_hash="test", role="vendor")
        db.session.add(owner)
        db.session.flush()
        shop = Shop(name="Public", slug="public", vendor_id=owner.id, is_active=True)
        hidden = Shop(name="Hidden", slug="hidden", vendor_id=owner.id, is_active=False)
        db.session.add_all([shop, hidden])
        db.session.commit()
        yield SimpleNamespace(app=app, shop=shop, hidden=hidden, owner=owner)
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def add_offer(context, kind="physical", **values):
    defaults = dict(name="Offer", kind=kind, price=100, stock=2, is_active=True,
                    shop_id=context.shop.id, vendor_id=context.owner.id)
    defaults.update(values)
    entry = Product(**defaults)
    db.session.add(entry)
    db.session.flush()
    return entry


def ids(selection, section="products"):
    return [item[0]["id"] for item in selection[section]]


@pytest.mark.parametrize("total", [0, 1, 3, 4, 5, 6, 8])
def test_rotation_is_bounded_unique_and_fair_for_small_catalogues(selection_app, total):
    expected = {add_offer(selection_app).id for _ in range(total)}
    db.session.commit()
    appearances = Counter()
    previous = None
    for slot in range(max(1, total)):
        current = ids(home_selection.build_home_selection(slot))
        assert len(current) == len(set(current)) == min(4, total)
        assert set(current) <= expected
        if total > 4 and previous is not None:
            assert set(current) != set(previous)
        appearances.update(current)
        previous = current
    assert set(appearances) == expected
    assert len(set(appearances.values())) <= 1


def test_both_sections_reach_every_offer_beyond_sixty_independently(selection_app):
    expected_products = {add_offer(selection_app).id for _ in range(83)}
    expected_services = {add_offer(selection_app, "service", stock=0).id for _ in range(9)}
    db.session.commit()
    seen_products, seen_services = set(), set()
    for slot in range(21):
        selected = home_selection.build_home_selection(slot)
        assert len(selected["products"]) == len(selected["services"]) == 4
        seen_products.update(ids(selected))
        seen_services.update(ids(selected, "services"))
    assert seen_products == expected_products
    assert seen_services == expected_services


def test_rotation_keeps_public_visibility_and_checkout_prices(selection_app):
    visible = add_offer(selection_app)
    add_offer(selection_app, is_active=False)
    add_offer(selection_app, shop_id=selection_app.hidden.id)
    add_offer(selection_app, "location")
    db.session.add(Promo(product_id=visible.id, type="percentage", value=25,
                         status="approved", end_date=datetime.utcnow() + timedelta(days=1)))
    db.session.commit()
    selected = home_selection.build_home_selection(99)
    assert ids(selected) == [visible.id]
    assert selected["products"][0][1] == 75
    assert selected["products"][0][0]["promo_active"] is True
    assert selected["services"] == []


def test_cache_is_stable_inside_slot_and_changes_at_the_thirty_minute_boundary(selection_app, monkeypatch):
    for _ in range(8):
        add_offer(selection_app)
    db.session.commit()
    clock = SimpleNamespace(now=100 * 1800 + 1)
    monkeypatch.setattr(home_selection, "time", SimpleNamespace(time=lambda: clock.now))
    first = home_selection.get_home_selection()
    assert first["refresh_after"] == 1799
    clock.now += 1798
    before_boundary = home_selection.get_home_selection()
    assert ids(before_boundary) == ids(first)
    assert before_boundary["refresh_after"] == 1
    clock.now += 1
    next_slot = home_selection.get_home_selection()
    assert set(ids(next_slot)).isdisjoint(ids(first))
    assert next_slot["refresh_after"] == 1800


def test_api_renders_four_safe_cards_and_keeps_booking_actions(selection_app):
    for index in range(5):
        add_offer(selection_app, name=f"<script>Product {index}</script>")
        add_offer(selection_app, "service", name=f"Service {index}", stock=0)
    db.session.commit()
    response = selection_app.app.test_client().get("/api/home-selection")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert 1 <= response.json["refresh_after"] <= 1800
    for kind in ("products", "services"):
        section = response.json["sections"][kind]
        assert section["count"] == section["html"].count('class="hub-product"') == 4
        assert "<script>" not in section["html"]
    assert "&lt;script&gt;" in response.json["sections"]["products"]["html"]
    assert "data-cart-add-btn" in response.json["sections"]["products"]["html"]
    assert "/booking/" in response.json["sections"]["services"]["html"]
    assert "data-cart-add-btn" not in response.json["sections"]["services"]["html"]
