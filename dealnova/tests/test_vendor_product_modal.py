"""Creation runs against disposable SQLite/uploads, with real routes and CSRF.

Run only this module when validating the vendor modal. The application factory
is imported inside the isolated environment, so the developer's .env is never
loaded by this fixture.
"""

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest


MODAL_HEADERS = {
    "X-Vendor-Modal": "product-create",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json",
}


@contextmanager
def isolated_vendor_application(directory: Path):
    """Shared by pytest and the optional localhost browser preview server."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / "vendor-modal.sqlite3"
    uploads = directory / "uploads"
    uploads.mkdir(exist_ok=True)
    with ExitStack() as stack:
        stack.enter_context(patch("dotenv.load_dotenv", return_value=False))
        stack.enter_context(patch.dict("os.environ", {
            "DATABASE_URL": "sqlite:///:memory:",
            "FLASK_ENV": "development", "CACHE_TYPE": "SimpleCache",
            "ANALYTICS_FLUSH_ENABLED": "0",
        }))
        from dealnova.app import create_app
        from dealnova.app.config import Config
        from dealnova.app.extensions import db
        from dealnova.app.models.category import Category
        from dealnova.app.models.shop import Shop
        from dealnova.app.models.user import User

        stack.enter_context(patch("dealnova.app.services.logging_service.logging_service.setup_logging"))

        class IsolatedConfig(Config):
            TESTING = True
            ENV = "development"
            SECRET_KEY = "vendor-modal-disposable-fixture"
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + database.as_posix()
            SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30}}
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            UPLOAD_FOLDER = str(uploads)
            CACHE_TYPE = "SimpleCache"
            CACHE_DEFAULT_TIMEOUT = 0
            ANALYTICS_FLUSH_ENABLED = False
            SESSION_COOKIE_SECURE = False
            REMEMBER_COOKIE_SECURE = False
            LANG_COOKIE_SECURE = False
            SECURITY_RATE_LIMIT_ENABLED = False
            SECURITY_HSTS_ENABLED = False
            PREFERRED_URL_SCHEME = "http"
            MAIL_SERVER = ""
            VENDOR_PUSH_VAPID_PUBLIC_KEY = ""
            VENDOR_PUSH_VAPID_PRIVATE_KEY = ""

        app = create_app(IsolatedConfig)
        with app.app_context():
            assert Path(db.engine.url.database).resolve() == database
            db.create_all()
            user = User(username="modal-vendor", email="modal-vendor@example.test",
                        role="vendor", is_active=True, password_hash="fixture-no-login",
                        subscription_expires_at=datetime.utcnow() + timedelta(days=365))
            db.session.add(user)
            db.session.flush()
            shop = Shop(name="Boutique de test", slug="modal-vendor-fixture", vendor_id=user.id,
                        contact_phone="+212600000000", address="Rabat", is_active=True,
                        primary_type="products", allowed_types_json='["products","services"]')
            physical = Category(name="Produits de test", slug="modal-products", category_type="products")
            service = Category(name="Services de test", slug="modal-services", category_type="services")
            db.session.add_all([shop, physical, service])
            db.session.commit()
            ids = SimpleNamespace(vendor=user.id, shop=shop.id, physical=physical.id, service=service.id)
        try:
            yield SimpleNamespace(app=app, db=db, ids=ids, uploads=uploads, database=database)
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()


@pytest.fixture()
def vendor_modal(tmp_path):
    with isolated_vendor_application(tmp_path) as fixture:
        fixture.client = fixture.app.test_client()
        with fixture.client.session_transaction() as storage:
            storage["_user_id"] = str(fixture.ids.vendor)
            storage["_fresh"] = True
        dashboard = fixture.client.get("/vendor/dashboard")
        assert dashboard.status_code == 200
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', dashboard.get_data(as_text=True))
        assert token, "Real dashboard must expose the CSRF token used by the modal"
        fixture.csrf = token.group(1)
        yield fixture


def _payload(fixture, **changes):
    values = {"name": "Article de test", "kind": "physical", "price": "25.50", "stock": "3",
              "category_id": str(fixture.ids.physical), "description": "Description de test",
              "csrf_token": fixture.csrf}
    values.update(changes)
    return values


def _post(fixture, **changes):
    return fixture.client.post("/vendor/product/new", data=_payload(fixture, **changes), headers=MODAL_HEADERS)


def _products(fixture):
    from dealnova.app.models.product import Product
    with fixture.app.app_context():
        return Product.query.count()


def test_classic_new_url_opens_dashboard_while_standalone_fallback_remains(vendor_modal):
    response = vendor_modal.client.get("/vendor/product/new")
    assert response.status_code in (302, 303)
    assert response.location.endswith("/vendor/dashboard?new=product")
    fallback = vendor_modal.client.get("/vendor/product/new?standalone=1")
    assert fallback.status_code == 200
    assert b'id="vendorCreateForm"' in fallback.data


def test_modal_get_returns_form_without_another_document(vendor_modal):
    response = vendor_modal.client.get("/vendor/product/new", headers=MODAL_HEADERS)
    assert response.status_code == 200
    assert response.is_json and response.json["success"] is True
    html = response.json["html"]
    assert 'id="vendorCreateForm"' in html
    assert '<html' not in html.lower() and '<body' not in html.lower()
    assert 'name="csrf_token"' in html
    assert "no-store" in response.headers["Cache-Control"]
    assert "X-Vendor-Modal" in response.headers["Vary"]


@pytest.mark.parametrize("changes,field", [
    ({"name": "   "}, "name"),
    ({"price": "not-a-price"}, "price"),
    ({"price": "-1"}, "price"),
    ({"price": "0"}, "price"),
    ({"price": "NaN"}, "price"),
    ({"price": "Infinity"}, "price"),
    ({"price": "0.001"}, "price"),
    ({"price": "0.005"}, "price"),
    ({"price": "1.234"}, "price"),
    ({"stock": "not-a-stock"}, "stock"),
    ({"stock": "-2"}, "stock"),
    ({"category_id": "999999"}, "category_id"),
])
def test_invalid_input_is_a_field_error_without_creation(vendor_modal, changes, field):
    response = _post(vendor_modal, **changes)
    assert response.status_code == 422
    assert response.is_json and response.json["success"] is False
    assert field in response.json["errors"]
    assert _products(vendor_modal) == 0


def test_kind_cannot_use_a_category_from_another_kind(vendor_modal):
    response = _post(vendor_modal, category_id=str(vendor_modal.ids.service))
    assert response.status_code == 422
    assert "category_id" in response.json["errors"]
    assert _products(vendor_modal) == 0


def test_physical_offer_creation_returns_record_and_writes_only_temp_uploads(vendor_modal):
    from PIL import Image
    from dealnova.app.models.product import Product
    image = BytesIO()
    Image.new("RGB", (80, 80), "green").save(image, format="PNG")
    image.seek(0)
    response = _post(vendor_modal, images=(image, "fixture.png"))
    assert response.status_code == 201
    assert response.json["success"] is True
    assert response.json["product"]["id"]
    with vendor_modal.app.app_context():
        product = vendor_modal.db.session.get(Product, response.json["product"]["id"])
        assert product.name == "Article de test"
        assert product.price_cents == 2550
        assert product.stock == 3 and product.kind == "physical"
        assert product.vendor_id == vendor_modal.ids.vendor and product.shop_id == vendor_modal.ids.shop
        assert product.image_file
        assert (vendor_modal.uploads / product.image_file).is_file()
    assert _products(vendor_modal) == 1


def test_service_creation_does_not_use_physical_stock(vendor_modal):
    from dealnova.app.models.product import Product
    response = _post(vendor_modal, kind="service", category_id=str(vendor_modal.ids.service), stock="999")
    assert response.status_code == 201
    with vendor_modal.app.app_context():
        product = vendor_modal.db.session.get(Product, response.json["product"]["id"])
        assert product.kind == "service" and product.stock == 0
        assert product.category_id == vendor_modal.ids.service


def test_price_with_trailing_zeroes_keeps_its_exact_cents(vendor_modal):
    from dealnova.app.models.product import Product
    response = _post(vendor_modal, price="1.2300")
    assert response.status_code == 201
    with vendor_modal.app.app_context():
        product = vendor_modal.db.session.get(Product, response.json["product"]["id"])
        assert product.price_cents == 123


def test_creation_keeps_real_csrf_protection(vendor_modal):
    response = _post(vendor_modal, csrf_token="expired-token")
    assert response.status_code == 400
    assert response.is_json and response.json.get("error") == "csrf"
    assert _products(vendor_modal) == 0


def test_shop_type_cannot_be_bypassed_by_posting_service_kind(vendor_modal):
    from dealnova.app.models.shop import Shop
    with vendor_modal.app.app_context():
        shop = vendor_modal.db.session.get(Shop, vendor_modal.ids.shop)
        shop.allowed_types_json = '["products"]'
        vendor_modal.db.session.commit()
    response = _post(vendor_modal, kind="service", category_id=str(vendor_modal.ids.service))
    assert response.status_code in (403, 422)
    assert _products(vendor_modal) == 0


def test_guest_fragment_request_is_explicit_session_error(vendor_modal):
    response = vendor_modal.app.test_client().get("/vendor/product/new", headers=MODAL_HEADERS)
    assert response.status_code == 401
    assert response.is_json and response.json["success"] is False
    assert _products(vendor_modal) == 0


def test_invalid_photo_does_not_create_offer_or_leave_files(vendor_modal):
    response = _post(vendor_modal, images=(BytesIO(b"not an image"), "invalid.png"))
    assert response.status_code == 422
    assert "images" in response.json["errors"]
    assert _products(vendor_modal) == 0
    assert not [file for file in vendor_modal.uploads.rglob("*") if file.is_file()]


def test_failed_commit_removes_only_new_media(vendor_modal):
    from PIL import Image
    existing = vendor_modal.uploads / "existing-file.txt"
    existing.write_text("preserved", encoding="utf-8")
    image = BytesIO()
    Image.new("RGB", (80, 80), "green").save(image, format="PNG")
    image.seek(0)
    with patch.object(vendor_modal.db.session, "commit", side_effect=RuntimeError("fixture database failure")):
        response = _post(vendor_modal, images=(image, "fixture.png"))
    assert response.status_code == 500
    assert response.is_json and response.json["success"] is False
    assert _products(vendor_modal) == 0
    assert [file for file in vendor_modal.uploads.rglob("*") if file.is_file()] == [existing]
    assert existing.read_text(encoding="utf-8") == "preserved"


def test_secondary_cache_failure_does_not_report_false_creation_failure(vendor_modal):
    with patch("dealnova.app.routes.vendor.bump_catalog_version", side_effect=RuntimeError("fixture cache failure")):
        response = _post(vendor_modal)
    assert response.status_code == 201
    assert response.json["success"] is True
    assert _products(vendor_modal) == 1
