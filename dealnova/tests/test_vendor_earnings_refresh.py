"""Cashbook redesign keeps ownership, physical subtotals and receipt safety."""
from datetime import datetime, timedelta
import re
from unittest.mock import patch

from flask import template_rendered
import pytest

from dealnova.tests.test_owner_location_modal import isolated_owner_application

HEADERS = {"X-Requested-With": "fetch", "Accept": "application/json"}


@pytest.fixture()
def cashbook(tmp_path):
    with isolated_owner_application(tmp_path) as fixture:
        from dealnova.app.models.order import Order, OrderItem
        from dealnova.app.models.product import Product
        from dealnova.app.models.vendor_receipt import VendorReceipt
        with fixture.app.app_context():
            def product(name, owner=None, kind="physical"):
                record = Product(name=name, description="Description synthétique", kind=kind, price=12.5, stock=10,
                                 vendor_id=owner or fixture.ids.vendor,
                                 shop_id=fixture.ids.foreign_shop if owner else fixture.ids.shop,
                                 category_id=fixture.ids.service if kind == "service" else fixture.ids.physical)
                fixture.db.session.add(record)
                fixture.db.session.flush()
                return record
            rice = product("Riz de la boutique")
            target = product("Épices safran doré")
            basket = product("Panier local")
            service = product("Service confidentiel", kind="service")
            foreign = product("Produit étranger secret", owner=fixture.ids.foreign_owner)
            now = datetime.utcnow()
            fixture.ids.orders = []

            def order(lines, status="pending", created=None):
                record = Order(full_name="Client synthétique", phone="0600000000", address="Rabat",
                               city="Rabat", total=sum(price * qty for _, price, qty in lines),
                               status=status, created_at=created or now)
                fixture.db.session.add(record)
                fixture.db.session.flush()
                for entry, price, qty in lines:
                    fixture.db.session.add(OrderItem(order_id=record.id, product_id=entry.id, price=price, quantity=qty))
                return record

            for index in range(36):
                lines = [(target if index == 35 else rice, 1250, 2 if index == 0 else 1)]
                if index == 0:
                    lines += [(basket, 500, 1), (service, 20000, 1), (foreign, 99999, 1)]
                record = order(lines, created=now - timedelta(seconds=index))
                fixture.ids.orders.append(record.id)
                if index < 2:
                    fixture.db.session.add(VendorReceipt(vendor_id=fixture.ids.vendor, order_id=record.id, note="Espèces"))
            fixture.ids.target = fixture.ids.orders[-1]
            fixture.ids.foreign_order = order([(foreign, 99999, 1)]).id
            fixture.ids.service_order = order([(service, 20000, 1)]).id
            fixture.ids.excluded = [order([(rice, 50000, 1)], status=status).id
                                    for status in ("cancelled", "draft", "expired")]
            fixture.db.session.commit()
        fixture.client = fixture.app.test_client()
        with fixture.client.session_transaction() as storage:
            storage["_user_id"], storage["_fresh"] = str(fixture.ids.vendor), True
        initial = fixture.client.get("/vendor/earnings")
        assert initial.status_code == 200
        fixture.csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', initial.get_data(as_text=True)).group(1)
        yield fixture


def rendered(fixture, query=""):
    contexts = []
    def capture(sender, template, context, **extra):
        if template.name == "vendor/earnings.html":
            contexts.append(dict(context))
    with template_rendered.connected_to(capture, fixture.app):
        response = fixture.client.get("/vendor/earnings" + query)
    assert response.status_code == 200
    return response, contexts[0]


def receipt(fixture, order_id, **changes):
    values = {"csrf_token": fixture.csrf, "note": "Espèces"}
    values.update(changes)
    return fixture.client.post(f"/vendor/orders/receipt/{order_id}", data=values, headers=HEADERS)


def test_cashbook_pagination_totals_and_products_stay_scoped_to_physical_owner(cashbook):
    response, context = rendered(cashbook)
    assert context["pagination"].total == context["total_orders_count"] == 36
    assert len(context["orders"]) == 30 and context["pagination"].pages == 2
    assert context["total_confirmed"] == 4250 and context["total_pending"] == 42500
    html = response.get_data(as_text=True)
    assert "Service confidentiel" not in html and "Produit étranger secret" not in html
    assert context["allows_products"] is True and context["allows_location"] is True
    _, second = rendered(cashbook, "?page=2")
    assert cashbook.ids.target in [row.id for row in second["orders"]]


@pytest.mark.parametrize("query", ["safran dore", "SAFRAN", "épices doré"])
def test_server_search_reaches_orders_beyond_first_page_with_accents(cashbook, query):
    _, context = rendered(cashbook, "?q=" + query)
    assert [row.id for row in context["orders"]] == [cashbook.ids.target]
    assert context["total_pending"] == 1250 and context["total_orders_count"] == 1


def test_search_does_not_reduce_full_owned_subtotal_to_the_matching_product(cashbook):
    _, context = rendered(cashbook, "?q=riz")
    assert context["order_amount_map"][cashbook.ids.orders[0]] == 3000
    assert context["total_confirmed"] == 4250


def test_exact_order_reference_and_empty_search_keep_consistent_totals(cashbook):
    _, context = rendered(cashbook, "?q=%23" + str(cashbook.ids.target))
    assert [order.id for order in context["orders"]] == [cashbook.ids.target]
    _, empty = rendered(cashbook, "?q=introuvable%25_")
    assert not empty["orders"] and empty["total_orders_count"] == 0
    assert empty["total_confirmed"] == empty["total_pending"] == 0


def test_paid_filter_matches_list_and_totals(cashbook):
    _, context = rendered(cashbook, "?show=confirmed")
    assert context["total_orders_count"] == 2 and context["total_pending"] == 0
    assert context["total_confirmed"] == 4250 and len(context["orders"]) == 2
    _, pending = rendered(cashbook, "?show=pending")
    assert pending["total_orders_count"] == 34 and pending["total_confirmed"] == 0


def test_receipt_confirmation_is_explicit_and_idempotent(cashbook):
    from dealnova.app.models.vendor_receipt import VendorReceipt
    response = receipt(cashbook, cashbook.ids.target, note="Virement reçu")
    assert response.status_code == 200 and response.json["success"]
    assert response.json["already_confirmed"] is False
    response = receipt(cashbook, cashbook.ids.target, note="Autre note")
    assert response.status_code == 200 and response.json["already_confirmed"] is True
    with cashbook.app.app_context():
        records = VendorReceipt.query.filter_by(vendor_id=cashbook.ids.vendor, order_id=cashbook.ids.target).all()
        assert len(records) == 1 and records[0].note == "Virement reçu"


@pytest.mark.parametrize("attribute", ["foreign_order", "service_order"])
def test_receipt_rejects_foreign_or_service_only_order(cashbook, attribute):
    response = receipt(cashbook, getattr(cashbook.ids, attribute))
    assert response.status_code == 403 and response.json["success"] is False


def test_cancelled_draft_expired_and_oversized_note_never_create_receipt(cashbook):
    from dealnova.app.models.vendor_receipt import VendorReceipt
    for order_id in cashbook.ids.excluded:
        response = receipt(cashbook, order_id)
        assert response.status_code == 409 and response.json["success"] is False
    assert receipt(cashbook, cashbook.ids.target, note="x" * 256).status_code == 422
    with cashbook.app.app_context():
        assert VendorReceipt.query.count() == 2


def test_receipt_failure_returns_json_and_keeps_no_partial_save(cashbook):
    from dealnova.app.extensions import db
    from dealnova.app.models.vendor_receipt import VendorReceipt
    with patch.object(db.session, "commit", side_effect=RuntimeError("synthetic failure")):
        response = receipt(cashbook, cashbook.ids.target)
    assert response.status_code == 500 and response.json["success"] is False
    with cashbook.app.app_context():
        assert VendorReceipt.query.count() == 2


def test_real_csrf_and_native_post_redirect_are_preserved(cashbook):
    assert cashbook.client.post(f"/vendor/orders/receipt/{cashbook.ids.target}", data={"note": "Sans jeton"},
                               headers=HEADERS).status_code == 400
    response = cashbook.client.post(f"/vendor/orders/receipt/{cashbook.ids.target}",
                                   data={"csrf_token": cashbook.csrf, "note": "Sans JavaScript"})
    assert response.status_code == 303 and response.location.endswith("/vendor/earnings")
