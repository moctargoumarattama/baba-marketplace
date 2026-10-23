"""Downloads use temporary photos and an in-memory database, never real uploads."""
from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

from flask import Flask
from PIL import Image, ImageChops
import pytest

from dealnova.app.extensions import db
from dealnova.app.models.product import Product
from dealnova.app.models.promo import Promo
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.routes import api, shop
from dealnova.app.services import image_download


@pytest.fixture()
def photos(tmp_path):
    app = Flask("product-photo-download-tests")
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECURITY_RATE_LIMIT_ENABLED=False,
                      UPLOAD_FOLDER=str(upload_root))
    db.init_app(app)
    app.register_blueprint(shop.bp, url_prefix="/shop")
    app.register_blueprint(api.bp)
    with app.app_context():
        assert db.engine.url.database == ":memory:"
        db.create_all()
        owner = User(username="photo-vendor", email="photo@example.test", password_hash="test", role="vendor")
        db.session.add(owner)
        db.session.flush()
        store = Shop(name="Photo shop", slug="photo-shop", vendor_id=owner.id, is_active=True)
        db.session.add(store)
        db.session.flush()
        product = Product(name="Produit photo", price=25, stock=2, kind="physical",
                          shop_id=store.id, vendor_id=owner.id, is_active=True,
                          image_file="first.jpg|second.png")
        db.session.add(product)
        db.session.commit()
        Image.new("RGB", (720, 480), (150, 60, 30)).save(upload_root / "first.jpg")
        Image.new("RGB", (720, 480), (12, 40, 150)).save(upload_root / "second.png")
        yield SimpleNamespace(app=app, client=app.test_client(), product=product, shop=store, root=upload_root)
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def download(photos, index=0):
    return photos.client.get(f"/shop/product/{photos.product.id}/photo/{index}/download")


def configure_offer(photos, kind, with_promotion):
    photos.product.kind = kind
    # Services remain public without physical stock.
    photos.product.stock = 0 if kind == "service" else 2
    photos.shop.set_allowed_types(["products", "services"])
    if with_promotion:
        db.session.add(Promo(product_id=photos.product.id, type="percentage", value=20,
                             status="approved", end_date=datetime.utcnow() + timedelta(days=1)))
    db.session.commit()


@pytest.mark.parametrize("kind,with_promotion", [
    ("physical", False), ("service", False), ("physical", True), ("service", True),
])
def test_selected_photo_download_is_watermarked_attachment_without_changing_originals(photos, kind, with_promotion):
    configure_offer(photos, kind, with_promotion)
    originals = {path.name: path.read_bytes() for path in photos.root.iterdir()}
    response = download(photos, 1)
    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert f"baba-market-produit-{photos.product.id}-photo-2.jpg" in response.headers["Content-Disposition"]
    with Image.open(BytesIO(response.data)) as rendered:
        assert rendered.size == (720, 480)
        assert rendered.mode == "RGB"
        assert max(abs(a - b) for a, b in zip(rendered.getpixel((0, 0)), (12, 40, 150))) < 5
        background = Image.new("RGB", rendered.size, rendered.getpixel((0, 0)))
        difference = ImageChops.difference(rendered, background)
        assert difference.crop((100, 100, 620, 380)).getbbox() is not None
    assert {path.name: path.read_bytes() for path in photos.root.iterdir()} == originals


@pytest.mark.parametrize("kind,with_promotion", [
    ("physical", False), ("service", False), ("physical", True), ("service", True),
])
def test_api_download_urls_align_with_photo_order_and_keep_display_images(photos, kind, with_promotion):
    configure_offer(photos, kind, with_promotion)
    response = photos.client.get(f"/api/product/{photos.product.id}")
    assert response.status_code == 200
    data = response.json["product"]
    assert data["kind"] == kind
    assert data["has_promo"] == with_promotion
    assert data["images"] == ["first.jpg", "second.png"]
    assert data["image_download_urls"] == [
        f"/shop/product/{photos.product.id}/photo/{index}/download" for index in range(2)
    ]


@pytest.mark.parametrize("hidden", ["product", "shop"])
def test_download_cannot_expose_non_public_offers(photos, hidden):
    getattr(photos, hidden).is_active = False
    db.session.commit()
    assert download(photos).status_code == 404


def test_missing_photo_and_out_of_range_indices_return_404(photos):
    assert download(photos, 2).status_code == 404
    assert download(photos, -1).status_code == 404
    (photos.root / "first.jpg").unlink()
    assert download(photos).status_code == 404


def test_database_filename_cannot_escape_the_upload_directory(photos):
    outside = photos.root.parent / "private.png"
    Image.new("RGB", (50, 50), "red").save(outside)
    original = outside.read_bytes()
    photos.product.image_file = "../private.png"
    db.session.commit()
    assert download(photos).status_code == 404
    assert outside.read_bytes() == original


def test_unreadable_or_oversized_source_is_rejected_without_writing(photos, monkeypatch):
    monkeypatch.setattr(image_download, "MAX_SOURCE_PIXELS", 10)
    assert download(photos).status_code == 422
    monkeypatch.setattr(image_download, "MAX_SOURCE_PIXELS", 40_000_000)
    (photos.root / "first.jpg").write_bytes(b"not an image")
    assert download(photos).status_code == 422


def test_exif_orientation_is_applied_and_private_metadata_is_not_downloaded(photos):
    photo = Image.new("RGB", (80, 120), (120, 80, 40))
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Private camera owner"
    photo.save(photos.root / "first.jpg", exif=exif)
    response = download(photos)
    assert response.status_code == 200
    with Image.open(BytesIO(response.data)) as rendered:
        assert rendered.size == (120, 80)
        assert not rendered.getexif()
