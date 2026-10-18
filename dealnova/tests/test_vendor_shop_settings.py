"""Shop settings use disposable SQLite/uploads, with real ownership and CSRF."""

from io import BytesIO
import re
from unittest.mock import patch

import pytest

from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


HEADERS = {"X-BM-Shop-Modal": "1", "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}


@pytest.fixture()
def shop_settings(tmp_path):
    with isolated_vendor_application(tmp_path) as fixture:
        from dealnova.app.models.shop import Shop
        from dealnova.app.models.user import User
        with fixture.app.app_context():
            shop = fixture.db.session.get(Shop, fixture.ids.shop)
            shop.description = "Description initiale"
            shop.contact_email = "contact@example.test"
            shop.service_latitude, shop.service_longitude = 34.02, -6.83
            shop.service_location_note = "Ancien repere"
            other = User(username="other-shop-vendor", email="other-shop@example.test", role="vendor",
                         is_active=True, password_hash="fixture-no-login")
            fixture.db.session.add(other)
            fixture.db.session.flush()
            other_shop = Shop(name="Autre boutique", slug="other-settings-shop", vendor_id=other.id,
                              contact_phone="+212600000099", address="Sale", primary_type="products",
                              allowed_types_json='["products"]')
            fixture.db.session.add(other_shop)
            fixture.db.session.commit()
            fixture.ids.other_vendor, fixture.ids.other_shop = other.id, other_shop.id
        fixture.client = fixture.app.test_client()
        with fixture.client.session_transaction() as storage:
            storage["_user_id"], storage["_fresh"] = str(fixture.ids.vendor), True
        response = fixture.client.get("/vendor/dashboard")
        assert response.status_code == 200
        fixture.csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True)).group(1)
        yield fixture


def _values(fixture, **changes):
    values = {"description": "Nouvelle description", "contact_phone": "+212600000010", "address": "Rabat, Centre",
              "service_location_note": "Pres du marche", "service_latitude": "34.031", "service_longitude": "-6.841",
              "clear_exact_location": "0", "csrf_token": fixture.csrf}
    values.update(changes)
    return values


def _save(fixture, **changes):
    return fixture.client.post("/vendor/shop/edit", data=_values(fixture, **changes), headers=HEADERS)


def _snapshot(fixture, shop_id=None):
    from dealnova.app.models.shop import Shop
    with fixture.app.app_context():
        shop = fixture.db.session.get(Shop, shop_id or fixture.ids.shop)
        return {key: getattr(shop, key) for key in (
            "name", "slug", "description", "contact_phone", "contact_email", "address", "logo",
            "service_location_note", "service_latitude", "service_longitude", "is_active", "is_open",
        )}


def _image():
    from PIL import Image
    stream = BytesIO()
    Image.new("RGB", (120, 100), "green").save(stream, "PNG")
    stream.seek(0)
    return stream


def test_shop_edit_uses_one_form_for_modal_and_full_page(shop_settings):
    response = shop_settings.client.get("/vendor/shop/edit")
    assert response.status_code == 303 and response.location.endswith("/vendor/shop/manage?edit_shop=1")
    fragment = shop_settings.client.get("/vendor/shop/edit", headers=HEADERS)
    assert fragment.status_code == 200 and fragment.json["success"]
    assert 'name="description"' in fragment.json["html"]
    assert 'name="csrf_token"' in fragment.json["html"]
    assert "<body" not in fragment.json["html"]
    assert "no-store" in fragment.headers["Cache-Control"]
    assert "X-BM-Shop-Modal" in fragment.headers["Vary"]
    fallback = shop_settings.client.get(response.location)
    assert fallback.status_code == 200 and b'name="description"' in fallback.data


@pytest.mark.parametrize("changes,field", [
    ({"description": "x" * 5001}, "description"),
    ({"contact_phone": ""}, "contact_phone"),
    ({"contact_phone": "1" * 31}, "contact_phone"),
    ({"address": ""}, "address"), ({"address": "x" * 256}, "address"),
    ({"service_location_note": "x" * 256}, "service_location_note"),
    ({"service_latitude": "NaN"}, "service_latitude"),
    ({"service_latitude": "Infinity"}, "service_latitude"),
    ({"service_latitude": "91"}, "service_latitude"),
    ({"service_longitude": "-181"}, "service_latitude"),
    ({"service_longitude": ""}, "service_latitude"),
    ({"logo": (BytesIO(b"invalid"), "logo.svg")}, "logo"),
    ({"logo": (BytesIO(b"invalid"), "logo.png")}, "logo"),
])
def test_validation_is_atomic_and_returns_field_errors(shop_settings, changes, field):
    before = _snapshot(shop_settings)
    response = _save(shop_settings, **changes)
    assert response.status_code == 422 and response.json["success"] is False
    assert field in response.json["errors"]
    assert _snapshot(shop_settings) == before
    assert list(shop_settings.uploads.iterdir()) == []


def test_edit_saves_once_and_ignores_locked_fields_and_foreign_shop(shop_settings):
    foreign = _snapshot(shop_settings, shop_settings.ids.other_shop)
    before = _snapshot(shop_settings)
    response = _save(shop_settings, name="Hacked name", contact_email="other@example.test", slug="changed",
                     shop_id=str(shop_settings.ids.other_shop), vendor_id=str(shop_settings.ids.other_vendor))
    assert response.status_code == 200 and response.json["success"]
    assert response.json["shop"]["id"] == shop_settings.ids.shop and response.json["html"]
    after = _snapshot(shop_settings)
    assert after["description"] == "Nouvelle description" and after["address"] == "Rabat, Centre"
    assert after["service_latitude"] == 34.031 and after["service_longitude"] == -6.841
    for field in ("name", "slug", "contact_email", "is_open", "is_active"):
        assert after[field] == before[field]
    assert _snapshot(shop_settings, shop_settings.ids.other_shop) == foreign


def test_location_can_be_cleared_explicitly_or_preserved_when_omitted(shop_settings):
    response = _save(shop_settings, service_latitude="", service_longitude="")
    assert response.status_code == 200
    assert _snapshot(shop_settings)["service_latitude"] == 34.02
    response = _save(shop_settings, clear_exact_location="1")
    assert response.status_code == 200
    assert _snapshot(shop_settings)["service_latitude"] is None
    assert _snapshot(shop_settings)["service_longitude"] is None


def test_logo_is_replaced_and_cleaned_only_after_commit(shop_settings):
    response = _save(shop_settings, logo=(_image(), "logo.png"))
    assert response.status_code == 200
    original = _snapshot(shop_settings)["logo"]
    assert (shop_settings.uploads / original).is_file()
    response = _save(shop_settings, logo=(_image(), "new-logo.png"))
    assert response.status_code == 200
    replacement = _snapshot(shop_settings)["logo"]
    assert replacement != original and (shop_settings.uploads / replacement).is_file()
    assert not (shop_settings.uploads / original).exists()
    assert not (shop_settings.uploads / (original.removesuffix(".webp") + "_300.webp")).exists()
    response = _save(shop_settings, remove_logo="on")
    assert response.status_code == 200 and _snapshot(shop_settings)["logo"] is None
    assert list(shop_settings.uploads.iterdir()) == []


def test_failed_commit_preserves_old_logo_and_cleans_new_files(shop_settings):
    assert _save(shop_settings, logo=(_image(), "logo.png")).status_code == 200
    before, existing = _snapshot(shop_settings), set(shop_settings.uploads.iterdir())
    with patch.object(shop_settings.db.session, "commit", side_effect=RuntimeError("synthetic DB failure")):
        response = _save(shop_settings, logo=(_image(), "new-logo.png"))
    assert response.status_code == 500 and response.json["success"] is False
    assert _snapshot(shop_settings) == before
    assert set(shop_settings.uploads.iterdir()) == existing


def test_replacing_shared_logo_keeps_other_shops_file(shop_settings):
    from dealnova.app.models.shop import Shop
    assert _save(shop_settings, logo=(_image(), "logo.png")).status_code == 200
    original = _snapshot(shop_settings)["logo"]
    with shop_settings.app.app_context():
        shop_settings.db.session.get(Shop, shop_settings.ids.other_shop).logo = original
        shop_settings.db.session.commit()
    assert _save(shop_settings, remove_logo="1").status_code == 200
    assert (shop_settings.uploads / original).is_file()
    assert _snapshot(shop_settings, shop_settings.ids.other_shop)["logo"] == original


def test_location_only_shop_keeps_contact_optional_and_cannot_add_pickup_gps(shop_settings):
    from dealnova.app.models.shop import Shop
    with shop_settings.app.app_context():
        shop = shop_settings.db.session.get(Shop, shop_settings.ids.shop)
        shop.primary_type, shop.allowed_types_json = "location", '["location"]'
        shop.service_latitude, shop.service_longitude = None, None
        shop_settings.db.session.commit()
    response = _save(shop_settings, address="", contact_phone="", service_latitude="", service_longitude="")
    assert response.status_code == 200
    assert _snapshot(shop_settings)["address"] == ""
    response = _save(shop_settings)
    assert response.status_code == 422 and "service_latitude" in response.json["errors"]


def test_post_commit_audit_or_cache_failure_does_not_report_failed_save(shop_settings):
    with patch("dealnova.app.routes.vendor.bump_catalog_version", side_effect=RuntimeError("cache down")), \
            patch("dealnova.app.routes.vendor.log_access", side_effect=RuntimeError("audit down")):
        response = _save(shop_settings)
    assert response.status_code == 200 and response.json["success"]
    assert _snapshot(shop_settings)["description"] == "Nouvelle description"


def test_no_javascript_error_keeps_text_and_uses_same_form(shop_settings):
    response = shop_settings.client.post("/vendor/shop/edit", data=_values(shop_settings, contact_phone=""))
    assert response.status_code == 422
    assert b'name="description"' in response.data and b'Nouvelle description' in response.data
    assert _snapshot(shop_settings)["description"] == "Description initiale"
    response = shop_settings.client.post("/vendor/shop/edit", data=_values(shop_settings))
    assert response.status_code == 303 and response.location.endswith("/vendor/shop/manage")


def _request_change(fixture, **changes):
    values = {"request_type": "shop_name", "requested_value": "Nouveau nom souhaite",
              "reason": "Changement du nom commercial", "csrf_token": fixture.csrf}
    values.update(changes)
    return fixture.client.post("/vendor/shop/change-request", data=values, headers=HEADERS)


def test_change_request_is_not_direct_edit_and_duplicate_is_rejected(shop_settings):
    from dealnova.app.models.vendor_change_request import VendorChangeRequest
    before = _snapshot(shop_settings)
    with patch("dealnova.app.routes.vendor.notify_admin_vendor_change_request") as notify:
        response = _request_change(shop_settings)
    assert response.status_code == 200 and response.json["success"]
    assert response.json["request_id"] and notify.call_count == 1
    assert _snapshot(shop_settings)["name"] == before["name"]
    second = _request_change(shop_settings)
    assert second.status_code == 422 and "request_type" in second.json["errors"]
    with shop_settings.app.app_context():
        assert VendorChangeRequest.query.filter_by(vendor_id=shop_settings.ids.vendor).count() == 1


def test_email_request_keeps_locked_email_and_survives_notification_failure(shop_settings):
    from dealnova.app.models.vendor_change_request import VendorChangeRequest
    before = _snapshot(shop_settings)
    with patch("dealnova.app.routes.vendor.notify_admin_vendor_change_request", side_effect=RuntimeError("push unavailable")), \
            patch("dealnova.app.routes.vendor.log_access", side_effect=RuntimeError("audit unavailable")):
        response = _request_change(shop_settings, request_type="account_email", requested_value="  New@Example.Test  ")
    assert response.status_code == 200 and response.json["success"]
    assert _snapshot(shop_settings)["contact_email"] == before["contact_email"]
    with shop_settings.app.app_context():
        entry = shop_settings.db.session.get(VendorChangeRequest, response.json["request_id"])
        assert entry.requested_value == "new@example.test" and entry.status == "pending"


@pytest.mark.parametrize("changes,field", [
    ({"request_type": "password"}, "request_type"), ({"reason": "court"}, "reason"),
    ({"reason": "x" * 1001}, "reason"), ({"requested_value": "ab"}, "requested_value"),
    ({"request_type": "account_email", "requested_value": "invalid"}, "requested_value"),
    ({"request_type": "account_email", "requested_value": "other-shop@example.test"}, "requested_value"),
])
def test_change_request_validates_type_value_and_reason(shop_settings, changes, field):
    response = _request_change(shop_settings, **changes)
    assert response.status_code == 422 and field in response.json["errors"]


def test_visibility_sets_desired_state_and_keeps_open_state_separate(shop_settings):
    before = _snapshot(shop_settings)
    for target in ("0", "0", "1", "1"):
        response = shop_settings.client.post("/vendor/shop/toggle", headers=HEADERS,
                                             data={"is_active": target, "csrf_token": shop_settings.csrf})
        assert response.status_code == 200 and response.json["is_active"] == (target == "1")
        assert _snapshot(shop_settings)["is_active"] == (target == "1")
        assert _snapshot(shop_settings)["is_open"] == before["is_open"]


def test_invalid_legacy_location_does_not_partially_overwrite_address(shop_settings):
    before = _snapshot(shop_settings)
    response = shop_settings.client.post("/vendor/shop/service-location", headers=HEADERS, data={
        "service_address": "Changed address", "service_latitude": "bad", "service_longitude": "1",
        "service_location_note": "Changed note", "csrf_token": shop_settings.csrf,
    })
    assert response.status_code == 422
    assert _snapshot(shop_settings) == before


def test_modal_requires_authenticated_vendor_and_real_csrf(shop_settings):
    guest = shop_settings.app.test_client()
    response = guest.get("/vendor/shop/edit", headers=HEADERS)
    assert response.status_code == 401 and response.json["redirect_url"]
    response = shop_settings.client.post("/vendor/shop/edit", headers=HEADERS, data={"address": "Rabat"})
    assert response.status_code == 400
    from dealnova.app.models.user import User
    with shop_settings.app.app_context():
        shop_settings.db.session.get(User, shop_settings.ids.vendor).role = "admin"
        shop_settings.db.session.commit()
    # Exercise a different authenticated role; customers intentionally stay guests.
    with shop_settings.client.session_transaction() as storage:
        storage["_user_id"], storage["_fresh"] = str(shop_settings.ids.vendor), True
    response = shop_settings.client.get("/vendor/shop/edit", headers=HEADERS)
    assert response.status_code == 403 and response.json["success"] is False
