"""Owner creation integration tests with isolated database and rental files."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import re
from unittest.mock import patch

import pytest

from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


MODAL_HEADERS = {"X-Vendor-Modal": "location-create", "X-Requested-With": "XMLHttpRequest",
                 "Accept": "application/json"}


@contextmanager
def isolated_owner_application(directory: Path, *, seed=False):
    """Rental helpers write through static_folder: redirect it before any upload."""
    with isolated_vendor_application(directory) as fixture:
        from dealnova.app.models.platform_settings import PlatformSettings
        from dealnova.app.models.rental import RentalListing, RentalMedia
        from dealnova.app.models.shop import Shop
        from dealnova.app.models.user import User

        fixture.source_static = Path(fixture.app.static_folder)
        fixture.static = Path(directory).resolve() / "static"
        fixture.static.mkdir()
        fixture.app.static_folder = str(fixture.static)
        with fixture.app.app_context():
            shop = fixture.db.session.get(Shop, fixture.ids.shop)
            shop.allowed_types_json = '["products","services","location"]'
            other = User(username="other-owner", email="other-owner@example.test", role="vendor",
                         is_active=True, password_hash="fixture-no-login")
            fixture.db.session.add(other)
            fixture.db.session.flush()
            foreign_shop = Shop(name="Autre boutique de test", slug="other-modal-owner", vendor_id=other.id,
                                primary_type="location", allowed_types_json='["location"]', is_active=True)
            fixture.db.session.add(foreign_shop)
            settings = PlatformSettings.get()
            settings.rental_success_commission_bps = 1250
            settings.rental_monthly_duration_days = 21
            settings.rental_daily_duration_days = 7
            fixture.db.session.flush()
            fixture.ids.foreign_shop = foreign_shop.id
            fixture.ids.foreign_owner = other.id
            if seed:
                from PIL import Image
                rental_dir = fixture.static / "uploads" / "rentals"
                rental_dir.mkdir(parents=True)
                Image.new("RGB", (400, 250), "#cbddce").save(rental_dir / "seed.webp", "WEBP")
                for index in range(25):
                    listing = RentalListing(
                        owner_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                        title=f"Appartement demonstration {index + 1:02d}", slug=f"owner-modal-seed-{index + 1}",
                        description="Annonce de demonstration uniquement.", city="Rabat" if index % 3 else "Sale",
                        area="Centre", listing_type="monthly" if index % 2 else "daily", property_type="apartment",
                        rent_cents=250000 + index * 100, status="reserved" if index % 5 == 0 else "active",
                        is_active=True, created_at=datetime.utcnow() - timedelta(minutes=index + 1),
                        expires_at=datetime.utcnow() + timedelta(days=20), owner_fee_cents=50000,
                        platform_commission_rate_bps=1250)
                    fixture.db.session.add(listing)
                    fixture.db.session.flush()
                    fixture.db.session.add(RentalMedia(listing_id=listing.id, kind="image", file_path="uploads/rentals/seed.webp"))
            fixture.db.session.commit()
        yield fixture


@pytest.fixture()
def owner_modal(tmp_path):
    with isolated_owner_application(tmp_path) as fixture:
        fixture.client = fixture.app.test_client()
        with fixture.client.session_transaction() as storage:
            storage["_user_id"] = str(fixture.ids.vendor)
            storage["_fresh"] = True
        # The shared seller shell supplies the real session CSRF token. Rendering
        # the owner list itself is covered by the browser journey below.
        response = fixture.client.get("/vendor/dashboard")
        assert response.status_code == 200
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
        assert token
        fixture.csrf = token.group(1)
        yield fixture


def _payload(fixture, **changes):
    values = {"title": "Appartement de test", "description": "Description de demonstration", "listing_type": "monthly",
              "property_type": "apartment", "city": "Rabat", "area": "Centre", "rent": "2500.50",
              "shop_id": str(fixture.ids.shop), "deposit_required": "0", "owner_fee": "500.25",
              "owner_fee_text": "Frais de test", "csrf_token": fixture.csrf}
    values.update(changes)
    return values


def _post(fixture, **changes):
    return fixture.client.post("/owner/location/new", data=_payload(fixture, **changes), headers=MODAL_HEADERS)


def _count(fixture):
    from dealnova.app.models.rental import RentalListing
    with fixture.app.app_context():
        return RentalListing.query.count()


def _image():
    from PIL import Image
    image = BytesIO()
    Image.new("RGB", (120, 90), "green").save(image, "PNG")
    image.seek(0)
    return image


def test_classic_url_redirects_to_owner_list_and_keeps_standalone_fallback(owner_modal):
    response = owner_modal.client.get("/owner/location/new")
    assert response.status_code == 303
    assert response.location.endswith("/owner/locations?new=location")
    fallback = owner_modal.client.get("/owner/location/new?standalone=1")
    assert fallback.status_code == 200
    assert b'name="title"' in fallback.data


def test_modal_fragment_is_private_form_without_another_document(owner_modal):
    response = owner_modal.client.get("/owner/location/new", headers=MODAL_HEADERS)
    assert response.status_code == 200 and response.json["success"] is True
    assert 'id="vendorCreateForm"' in response.json["html"]
    assert 'name="csrf_token"' in response.json["html"]
    assert "<body" not in response.json["html"].lower()
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("changes,field", [
    ({"title": "court"}, "title"), ({"title": "x" * 181}, "title"),
    ({"city": " "}, "city"), ({"city": "x" * 121}, "city"),
    ({"area": "x" * 121}, "area"), ({"listing_type": "weekly"}, "listing_type"),
    ({"property_type": "unknown"}, "property_type"),
    ({"rent": "-1"}, "rent"), ({"rent": "NaN"}, "rent"), ({"rent": "Infinity"}, "rent"),
    ({"rent": "1.234"}, "rent"), ({"rent": "21474836.48"}, "rent"),
    ({"deposit_required": "1", "deposit": ""}, "deposit"),
    ({"owner_fee": "-1"}, "owner_fee"), ({"owner_fee_text": "x" * 256}, "owner_fee_text"),
])
def test_invalid_fields_return_422_without_creating_listing(owner_modal, changes, field):
    response = _post(owner_modal, **changes)
    assert response.status_code == 422
    assert response.json["success"] is False
    assert field in response.json["errors"]
    assert _count(owner_modal) == 0


@pytest.mark.parametrize("listing_type,days", [("monthly", 21), ("daily", 7)])
def test_creation_preserves_money_deposit_commission_and_configured_duration(owner_modal, listing_type, days):
    from dealnova.app.models.rental import RentalListing
    response = _post(owner_modal, listing_type=listing_type, deposit_required="1", deposit="1500,25",
                     platform_commission_rate_bps="0", duration_days="999", rent="2500.5000")
    assert response.status_code == 201
    assert response.json["success"] is True
    with owner_modal.app.app_context():
        listing = owner_modal.db.session.get(RentalListing, response.json["listing"]["id"])
        assert listing.owner_id == owner_modal.ids.vendor and listing.shop_id == owner_modal.ids.shop
        assert listing.rent_cents == 250050 and listing.deposit_cents == 150025
        assert listing.deposit_required is True and listing.owner_fee_cents == 50025
        assert listing.platform_commission_rate_bps == 1250
        assert listing.platform_commission_mode == "success_commission"
        assert listing.platform_commission_fixed_cents == 0
        assert listing.status == "active" and listing.is_active is True
        assert listing.expires_at - listing.created_at == timedelta(days=days)
    assert _count(owner_modal) == 1


def test_zero_rent_and_optional_fee_follow_existing_business_rules(owner_modal):
    from dealnova.app.models.rental import RentalListing
    response = _post(owner_modal, rent="0", owner_fee="", deposit="9999", deposit_required="0")
    assert response.status_code == 201
    with owner_modal.app.app_context():
        listing = owner_modal.db.session.get(RentalListing, response.json["listing"]["id"])
        assert listing.rent_cents == 0 and listing.deposit_cents is None
        assert listing.owner_fee_cents is None and listing.deposit_required is False


def test_owner_cannot_create_an_announcement_in_another_shop(owner_modal):
    response = _post(owner_modal, shop_id=str(owner_modal.ids.foreign_shop))
    assert response.status_code in (403, 422)
    assert response.json["success"] is False
    assert _count(owner_modal) == 0


def test_shop_without_location_permission_cannot_bypass_the_guard(owner_modal):
    from dealnova.app.models.shop import Shop
    with owner_modal.app.app_context():
        shop = owner_modal.db.session.get(Shop, owner_modal.ids.shop)
        shop.allowed_types_json = '["products","services"]'
        owner_modal.db.session.commit()
    response = owner_modal.client.get("/owner/location/new", headers=MODAL_HEADERS)
    assert response.status_code == 403
    assert response.is_json and response.json["success"] is False


def test_guest_get_is_explicit_json_authentication_error(owner_modal):
    response = owner_modal.app.test_client().get("/owner/location/new", headers=MODAL_HEADERS)
    assert response.status_code == 401
    assert response.is_json and response.json["success"] is False


def test_admin_does_not_gain_owner_creation_by_posting_the_modal_header(owner_modal):
    from dealnova.app.models.user import User
    with owner_modal.app.app_context():
        user = owner_modal.db.session.get(User, owner_modal.ids.vendor)
        user.role = "admin"
        owner_modal.db.session.commit()
    response = owner_modal.client.get("/owner/location/new", headers=MODAL_HEADERS)
    assert response.status_code == 403
    assert response.is_json and response.json["success"] is False


def test_creation_keeps_real_csrf_protection(owner_modal):
    response = _post(owner_modal, csrf_token="expired-fixture")
    assert response.status_code == 400 and response.json.get("error") == "csrf"
    assert _count(owner_modal) == 0


def test_uploaded_photo_and_its_thumbnail_stay_only_in_temporary_static_folder(owner_modal):
    from dealnova.app.models.rental import RentalListing
    response = _post(owner_modal, images=(_image(), "fixture.png"))
    assert response.status_code == 201
    with owner_modal.app.app_context():
        listing = owner_modal.db.session.get(RentalListing, response.json["listing"]["id"])
        assert len(listing.media) == 1 and listing.media[0].kind == "image"
        stored = owner_modal.static / listing.media[0].file_path
        assert stored.is_file() and stored.resolve().is_relative_to(owner_modal.static.resolve())
        assert len(list((owner_modal.static / "uploads" / "rentals").glob("*.webp"))) == 2


def test_unreadable_photo_cleans_previous_new_photo_without_removing_existing_files(owner_modal):
    existing = owner_modal.static / "uploads" / "rentals" / "existing.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("preserve", encoding="utf-8")
    response = _post(owner_modal, images=[(_image(), "valid.png"), (BytesIO(b"not an image"), "invalid.png")])
    assert response.status_code == 422 and "images" in response.json["errors"]
    assert _count(owner_modal) == 0
    assert [file for file in owner_modal.static.rglob("*") if file.is_file()] == [existing]


def test_too_many_photos_are_rejected_before_any_file_is_written(owner_modal):
    response = _post(owner_modal, images=[(_image(), f"fixture-{index}.png") for index in range(5)])
    assert response.status_code == 422 and "images" in response.json["errors"]
    assert _count(owner_modal) == 0
    assert not [file for file in owner_modal.static.rglob("*") if file.is_file()]


def test_commit_failure_cleans_new_media_and_rolls_back_listing(owner_modal):
    with patch.object(owner_modal.db.session, "commit", side_effect=RuntimeError("fixture commit failure")):
        response = _post(owner_modal, images=(_image(), "fixture.png"))
    assert response.status_code == 500 and response.json["success"] is False
    assert _count(owner_modal) == 0
    assert not [file for file in owner_modal.static.rglob("*") if file.is_file()]


def test_audit_failure_after_commit_does_not_invite_a_duplicate_retry(owner_modal):
    with patch("dealnova.app.routes.rentals.log_access", side_effect=RuntimeError("fixture audit failure")):
        response = _post(owner_modal)
    assert response.status_code == 201 and response.json["success"] is True
    assert _count(owner_modal) == 1


@pytest.mark.parametrize("failure", ["unavailable", "invalid", "exception"])
def test_video_failure_rejects_creation_and_cleans_its_photo_instead_of_publishing_unreadable_media(owner_modal, failure):
    from types import SimpleNamespace
    with patch("dealnova.app.services.rentals.shutil.which", return_value=None if failure == "unavailable" else "ffmpeg-fixture"):
        with patch("dealnova.app.services.rentals.subprocess.run", return_value=SimpleNamespace(returncode=1),
                   side_effect=RuntimeError("fixture ffmpeg failure") if failure == "exception" else None):
            response = _post(owner_modal, images=(_image(), "fixture.png"),
                             video=(BytesIO(b"not a playable video"), "fixture.mp4"))
    assert response.status_code == 422
    assert "video" in response.json["errors"]
    assert _count(owner_modal) == 0
    assert not [file for file in owner_modal.static.rglob("*") if file.is_file()]


def test_legacy_video_service_keeps_its_existing_uncompressed_fallback(owner_modal):
    from werkzeug.datastructures import FileStorage
    from dealnova.app.services.rentals import save_rental_video
    video = FileStorage(stream=BytesIO(b"legacy fixture bytes"), filename="fixture.mp4", content_type="video/mp4")
    with owner_modal.app.app_context():
        with patch("dealnova.app.services.rentals.shutil.which", return_value=None):
            relative = save_rental_video(video)
    stored = owner_modal.static / relative
    assert stored.is_file() and stored.read_bytes() == b"legacy fixture bytes"
    assert stored.resolve().is_relative_to(owner_modal.static.resolve())


def test_mp4_publication_uses_distinct_input_and_output_and_keeps_final_media(owner_modal):
    from types import SimpleNamespace
    from dealnova.app.models.rental import RentalListing

    def convert(args, **_kwargs):
        source = Path(args[args.index("-i") + 1])
        output = Path(args[-1])
        assert source.resolve() != output.resolve()
        assert source.is_file()
        assert output.resolve().is_relative_to(owner_modal.static.resolve())
        output.write_bytes(b"converted video" if "-vcodec" in args else b"video poster")
        return SimpleNamespace(returncode=0)

    with patch("dealnova.app.services.rentals.shutil.which", return_value="ffmpeg-fixture"):
        with patch("dealnova.app.services.rentals.subprocess.run", side_effect=convert):
            response = _post(owner_modal, video=(BytesIO(b"uploaded video"), "fixture.mp4"))
    assert response.status_code == 201
    with owner_modal.app.app_context():
        listing = owner_modal.db.session.get(RentalListing, response.json["listing"]["id"])
        assert len(listing.media) == 1 and listing.media[0].kind == "video"
        final = owner_modal.static / listing.media[0].file_path
        assert final.read_bytes() == b"converted video"
        assert final.with_name(final.stem + "_poster.jpg").read_bytes() == b"video poster"
    assert not list(owner_modal.static.rglob("*_source.*"))
