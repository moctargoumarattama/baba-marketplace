"""Seller dashboard counters use disposable data and the same period on refresh."""

from datetime import datetime, timedelta
from unittest.mock import patch

from flask import template_rendered, url_for
import pytest

from dealnova.tests.test_owner_location_modal import isolated_owner_application


@pytest.fixture()
def seller_dashboard(tmp_path):
    with isolated_owner_application(tmp_path) as fixture:
        from dealnova.app.models.order import Order, OrderItem
        from dealnova.app.models.product import Product

        fixture.client = fixture.app.test_client()
        with fixture.client.session_transaction() as storage:
            storage["_user_id"] = str(fixture.ids.vendor)
            storage["_fresh"] = True
        with fixture.app.app_context():
            physical = Product(name="Dashboard item A", kind="physical", price=12.50, stock=2,
                               vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                               category_id=fixture.ids.physical)
            second = Product(name="Dashboard item B", kind="physical", price=30, stock=20,
                             vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                             category_id=fixture.ids.physical)
            service = Product(name="Dashboard service", kind="service", price=1000, stock=0,
                              vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                              category_id=fixture.ids.service)
            foreign = Product(name="Other seller item", kind="physical", price=1000, stock=0,
                              vendor_id=fixture.ids.foreign_owner, shop_id=fixture.ids.foreign_shop,
                              category_id=fixture.ids.physical)
            foreign_service = Product(name="Other seller service", kind="service", price=1000, stock=0,
                                      vendor_id=fixture.ids.foreign_owner, shop_id=fixture.ids.foreign_shop,
                                      category_id=fixture.ids.service)
            fixture.db.session.add_all([physical, second, service, foreign, foreign_service])
            fixture.db.session.flush()
            fixture.ids.product = physical.id
            fixture.ids.service_product = service.id
            fixture.ids.foreign_service_product = foreign_service.id
            now = datetime.utcnow()

            def order(at, *rows):
                record = Order(full_name="Synthetic customer", phone="0600000000", address="Test address",
                               city="Rabat", status="pending", total=sum(price * qty for _, price, qty in rows),
                               created_at=at)
                fixture.db.session.add(record)
                fixture.db.session.flush()
                for product, price, qty in rows:
                    fixture.db.session.add(OrderItem(order_id=record.id, product_id=product.id,
                                                     price=price, quantity=qty))

            order(now - timedelta(days=62), (physical, 1250, 2))
            order(now - timedelta(minutes=5), (physical, 2000, 1), (second, 1500, 2))
            order(now - timedelta(minutes=4), (second, 750, 2), (foreign, 100000, 1))
            order(now - timedelta(minutes=3), (service, 100000, 1))
            order(now - timedelta(minutes=2), (foreign, 100000, 1))
            fixture.db.session.commit()
        # Cache keys are user IDs; the disposable database restarts at ID 1.
        with patch("dealnova.app.routes.vendor.LIVE_ENDPOINT_MICROCACHE_TTL_SECONDS", 0):
            yield fixture


def _render_dashboard(fixture):
    contexts = []

    def record(sender, template, context, **extra):
        if template.name == "vendor/dashboard.html":
            contexts.append(dict(context))

    with template_rendered.connected_to(record, fixture.app):
        response = fixture.client.get("/vendor/dashboard")
    assert response.status_code == 200
    assert len(contexts) == 1
    return contexts[0]


def test_initial_and_live_totals_include_previous_month_without_other_sellers_or_services(seller_dashboard):
    initial = _render_dashboard(seller_dashboard)
    live = seller_dashboard.client.get("/vendor/stats/live")
    assert live.status_code == 200
    assert initial["total_orders"] == live.json["total_orders"] == 3
    assert initial["total_revenue"] == 90.0
    assert live.json["total_revenue"] == "90"
    assert initial["low_stock_total"] == live.json["low_stock"] == 1
    assert initial["total_products"] == 3


def test_service_only_seller_does_not_receive_physical_order_or_stock_counters(seller_dashboard):
    from dealnova.app.models.shop import Shop

    with seller_dashboard.app.app_context():
        shop = seller_dashboard.db.session.get(Shop, seller_dashboard.ids.shop)
        shop.primary_type = "services"
        shop.allowed_types_json = '["services"]'
        seller_dashboard.db.session.commit()
    initial = _render_dashboard(seller_dashboard)
    live = seller_dashboard.client.get("/vendor/stats/live")
    assert live.status_code == 200
    assert initial["allows_products"] is False
    assert initial["allows_services"] is True
    assert initial["total_orders"] == live.json["total_orders"] == 0
    assert initial["total_revenue"] == 0 and live.json["total_revenue"] == "0"
    assert initial["low_stock_total"] == live.json["low_stock"] == 0
    assert initial["total_products"] == 1


def test_other_seller_gets_only_their_share_of_mixed_orders(seller_dashboard):
    from dealnova.app.models.shop import Shop

    with seller_dashboard.app.app_context():
        foreign_shop = seller_dashboard.db.session.get(Shop, seller_dashboard.ids.foreign_shop)
        foreign_shop.primary_type = "products"
        foreign_shop.allowed_types_json = '["products"]'
        seller_dashboard.db.session.commit()
    with seller_dashboard.client.session_transaction() as storage:
        storage["_user_id"] = str(seller_dashboard.ids.foreign_owner)
    response = seller_dashboard.client.get("/vendor/stats/live")
    assert response.status_code == 200
    assert response.json["total_orders"] == 2
    assert response.json["total_revenue"] == "2000"
    assert response.json["low_stock"] == 1


def test_today_bookings_and_active_locations_remain_scoped_to_owner(seller_dashboard):
    from dealnova.app.models.booking import Booking
    from dealnova.app.models.rental import RentalListing

    now = datetime.utcnow()
    today = now.replace(hour=12, minute=0, second=0, microsecond=0)
    with seller_dashboard.app.app_context():
        for product_id, shop_id, at, status in [
            (seller_dashboard.ids.service_product, seller_dashboard.ids.shop, today, "pending"),
            (seller_dashboard.ids.service_product, seller_dashboard.ids.shop, today, "confirmed"),
            (seller_dashboard.ids.service_product, seller_dashboard.ids.shop, today, "cancelled"),
            (seller_dashboard.ids.service_product, seller_dashboard.ids.shop, today + timedelta(days=1), "pending"),
            (seller_dashboard.ids.foreign_service_product, seller_dashboard.ids.foreign_shop, today, "pending"),
        ]:
            seller_dashboard.db.session.add(Booking(product_id=product_id, shop_id=shop_id,
                                                    full_name="Synthetic booking", phone="0600000000",
                                                    scheduled_for=at, status=status))
        for index, (owner_id, shop_id, status, active) in enumerate([
            (seller_dashboard.ids.vendor, seller_dashboard.ids.shop, "active", True),
            (seller_dashboard.ids.vendor, seller_dashboard.ids.shop, "reserved", True),
            (seller_dashboard.ids.vendor, seller_dashboard.ids.shop, "taken", True),
            (seller_dashboard.ids.vendor, seller_dashboard.ids.shop, "active", False),
            (seller_dashboard.ids.foreign_owner, seller_dashboard.ids.foreign_shop, "active", True),
        ]):
            seller_dashboard.db.session.add(RentalListing(owner_id=owner_id, shop_id=shop_id,
                                                         title="Synthetic rental", slug=f"dashboard-test-{index}",
                                                         description="Test rental", city="Rabat", rent_cents=10000,
                                                         status=status, is_active=active,
                                                         expires_at=now + timedelta(days=10)))
        seller_dashboard.db.session.commit()
    initial = _render_dashboard(seller_dashboard)
    response = seller_dashboard.client.get("/vendor/dashboard/orders-live")
    assert response.status_code == 200
    assert initial["today_bookings_count"] == response.json["today_bookings"]["count"] == 2
    assert initial["today_locations_count"] == response.json["today_locations_count"] == 2


def test_live_stats_require_login(seller_dashboard):
    response = seller_dashboard.app.test_client().get("/vendor/stats/live")
    assert response.status_code == 302
    assert "/auth/login" in response.location or "/login" in response.location


def test_live_stats_reject_other_roles(seller_dashboard):
    from dealnova.app.models.user import User

    with seller_dashboard.app.app_context():
        user = seller_dashboard.db.session.get(User, seller_dashboard.ids.vendor)
        user.role = "manager"
        seller_dashboard.db.session.commit()
    response = seller_dashboard.client.get("/vendor/stats/live")
    # The vendor blueprint rejects this role before the stats view is invoked.
    assert response.status_code == 302
    with seller_dashboard.app.test_request_context():
        assert response.location == url_for("shop.home")
    assert not response.is_json
