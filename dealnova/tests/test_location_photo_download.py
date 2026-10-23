"""Rental downloads use temporary uploads and an isolated in-memory database."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from PIL import Image, ImageChops
import pytest

from dealnova.app.extensions import db
from dealnova.app.models.rental import RentalListing, RentalMedia
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.routes import rentals
from dealnova.app.services import image_download


@contextmanager
def isolated_location_photos(directory):
    source = Path(__file__).resolve().parents[1] / "app"
    static = directory / "static"
    root = static / "uploads" / "rentals"
    root.mkdir(parents=True)
    app = Flask("location-photo-download-tests", static_folder=str(static), static_url_path="/static")
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECURITY_RATE_LIMIT_ENABLED=False)
    # Render the real detail template with a minimal shell, without unrelated app services.
    app.jinja_loader = ChoiceLoader([
        DictLoader({"base.html": '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{% block head %}{% endblock %}</head><body>{% block content %}{% endblock %}</body></html>'}),
        FileSystemLoader(str(source / "templates")),
    ])
    app.jinja_env.globals["app_static_version"] = "test"
    db.init_app(app)
    app.register_blueprint(rentals.bp)
    with app.app_context():
        assert db.engine.url.database == ":memory:"
        db.create_all()
        owner = User(username="rental-photo-vendor", email="rental-photo@example.test",
                     password_hash="test", role="vendor")
        db.session.add(owner)
        db.session.flush()
        shop = Shop(name="Locations photos", slug="locations-photos", vendor_id=owner.id,
                    is_active=True, primary_type="location", allowed_types_json='["location"]')
        db.session.add(shop)
        db.session.flush()
        listing = RentalListing(title="Appartement de test", slug="appartement-test-photo",
                                description="Description de la location.", city="Rabat", rent_cents=250000,
                                owner_id=owner.id, shop_id=shop.id, listing_type="monthly",
                                status="active", is_active=True, expires_at=datetime.utcnow() + timedelta(days=7))
        other = RentalListing(title="Autre appartement", slug="autre-appartement-photo",
                              description="Autre annonce.", city="Rabat", rent_cents=200000,
                              owner_id=owner.id, shop_id=shop.id, expires_at=datetime.utcnow() + timedelta(days=7))
        db.session.add_all([listing, other])
        db.session.flush()
        first = RentalMedia(listing_id=listing.id, kind="image", file_path="uploads/rentals/first.jpg")
        second = RentalMedia(listing_id=listing.id, kind="image", file_path="uploads/rentals/second.png")
        video = RentalMedia(listing_id=listing.id, kind="video", file_path="uploads/rentals/clip.mp4")
        foreign = RentalMedia(listing_id=other.id, kind="image", file_path="uploads/rentals/first.jpg")
        db.session.add_all([first, second, video, foreign])
        db.session.commit()
        Image.new("RGB", (720, 480), (150, 60, 30)).save(root / "first.jpg")
        Image.new("RGB", (720, 480), (12, 40, 150)).save(root / "second.png")
        try:
            yield SimpleNamespace(app=app, client=app.test_client(), root=root, listing=listing,
                                  shop=shop, first=first, second=second, video=video, foreign=foreign)
        finally:
            db.session.remove()
            db.drop_all()
            db.engine.dispose()


@pytest.fixture()
def photos(tmp_path):
    with isolated_location_photos(tmp_path) as fixture:
        yield fixture


def download_url(photos, media=None):
    return f"/location/{photos.listing.slug}/photo/{(media or photos.first).id}/download"


def test_selected_rental_photo_is_watermarked_and_originals_are_unchanged(photos):
    originals = {path.name: path.read_bytes() for path in photos.root.iterdir()}
    response = photos.client.get(download_url(photos, photos.second))
    assert response.status_code == 200 and response.mimetype == "image/jpeg"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert f"baba-market-location-{photos.listing.id}-photo-{photos.second.id}.jpg" in response.headers["Content-Disposition"]
    with Image.open(BytesIO(response.data)) as rendered:
        assert rendered.size == (720, 480) and rendered.mode == "RGB"
        corner = rendered.getpixel((0, 0))
        assert max(abs(a - b) for a, b in zip(corner, (12, 40, 150))) < 5
        difference = ImageChops.difference(rendered, Image.new("RGB", rendered.size, corner))
        assert difference.crop((100, 100, 620, 380)).getbbox() is not None
    assert {path.name: path.read_bytes() for path in photos.root.iterdir()} == originals


@pytest.mark.parametrize("state", ["inactive", "expired", "taken", "archived", "shop_inactive", "shop_disallowed"])
def test_download_respects_public_listing_access(photos, state):
    if state == "inactive":
        photos.listing.is_active = False
    elif state == "expired":
        photos.listing.expires_at = datetime.utcnow() - timedelta(seconds=1)
    elif state == "shop_inactive":
        photos.shop.is_active = False
    elif state == "shop_disallowed":
        photos.shop.primary_type = "products"
        photos.shop.allowed_types_json = '["products"]'
    else:
        photos.listing.status = state
    db.session.commit()
    assert photos.client.get(download_url(photos)).status_code == 404


def test_reserved_listing_photo_remains_public(photos):
    photos.listing.status = "reserved"
    db.session.commit()
    assert photos.client.get(download_url(photos)).status_code == 200


def test_videos_other_listings_and_missing_media_are_not_downloadable_as_photos(photos):
    assert photos.client.get(download_url(photos, photos.video)).status_code == 404
    assert photos.client.get(download_url(photos, photos.foreign)).status_code == 404
    assert photos.client.get(download_url(photos).replace(f"/{photos.first.id}/download", "/99999/download")).status_code == 404
    (photos.root / "first.jpg").unlink()
    assert photos.client.get(download_url(photos)).status_code == 404


@pytest.mark.parametrize("path", ["uploads/rentals/../private.png", "uploads/rentals/nested/first.jpg",
                                 "uploads/first.jpg", "/uploads/rentals/first.jpg", "https://example.test/first.jpg"])
def test_filename_cannot_escape_rental_uploads(photos, path):
    photos.first.file_path = path
    db.session.commit()
    assert photos.client.get(download_url(photos)).status_code == 404


def test_unreadable_and_oversized_sources_are_rejected(photos, monkeypatch):
    monkeypatch.setattr(image_download, "MAX_SOURCE_PIXELS", 10)
    assert photos.client.get(download_url(photos)).status_code == 422
    monkeypatch.setattr(image_download, "MAX_SOURCE_PIXELS", 40_000_000)
    (photos.root / "first.jpg").write_bytes(b"invalid image")
    assert photos.client.get(download_url(photos)).status_code == 422


def test_real_detail_template_links_each_photo_to_its_own_download(photos):
    response = photos.client.get(f"/location/{photos.listing.slug}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="listingPhotoDownload"' in html
    assert f'data-download-url="{download_url(photos)}"' in html
    assert f'data-download-url="{download_url(photos, photos.second)}"' in html
    assert f'data-download-url="{download_url(photos, photos.video)}"' not in html


def test_video_only_or_empty_gallery_has_no_photo_download(photos):
    db.session.delete(photos.first)
    db.session.delete(photos.second)
    db.session.commit()
    response = photos.client.get(f"/location/{photos.listing.slug}")
    assert response.status_code == 200 and 'id="listingPhotoDownload"' not in response.get_data(as_text=True)
    db.session.delete(photos.video)
    db.session.commit()
    response = photos.client.get(f"/location/{photos.listing.slug}")
    assert response.status_code == 200 and 'id="listingPhotoDownload"' not in response.get_data(as_text=True)
