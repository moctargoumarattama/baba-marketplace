"""Create/edit share a form; editing must never lose committed media on failure.

Every database and uploaded file is disposable. The imported fixture disables
dotenv before the app factory runs and redirects both static and uploads.
"""

from io import BytesIO
import json
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dealnova.tests.test_owner_location_modal import owner_modal, _image, _payload as rental_payload
from dealnova.tests.test_vendor_product_modal import _payload as product_payload


def _headers(kind, mode="edit"):
    return {"X-Vendor-Modal": f"{kind}-{mode}", "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json"}


def _files(fixture):
    return {str(file.resolve()): file.read_bytes()
            for root in (fixture.uploads, fixture.static)
            for file in root.rglob("*") if file.is_file()}


def _record(offer):
    from dealnova.app.models.product import Product
    from dealnova.app.models.rental import RentalListing

    with offer.fixture.app.app_context():
        model = Product if offer.kind == "product" else RentalListing
        item = offer.fixture.db.session.get(model, offer.id)
        if offer.kind == "product":
            return {"title": item.name, "amount": item.price_cents, "kind": item.kind,
                    "stock": item.stock, "is_active": item.is_active, "images": item.image_file,
                    "video": item.video_file, "count": model.query.count()}
        return {"title": item.title, "amount": item.rent_cents, "status": item.status,
                "created_at": item.created_at, "expires_at": item.expires_at,
                "images": [(row.id, row.kind, row.file_path) for row in item.media],
                "count": model.query.count()}


@pytest.fixture(params=["product", "location"])
def editable_offer(request, owner_modal):
    fixture = owner_modal
    kind = request.param
    payload = product_payload(fixture) if kind == "product" else rental_payload(fixture)
    base = "/vendor/product" if kind == "product" else "/owner/location"
    creation = fixture.client.post(base + "/new", headers=_headers(kind, "create"),
                                   data={**payload, "images": [(_image(), "first.png"), (_image(), "second.png")]})
    assert creation.status_code == 201, creation.get_data(as_text=True)
    item_id = creation.json["product" if kind == "product" else "listing"]["id"]
    from dealnova.app.models.product import Product
    from dealnova.app.models.rental import RentalListing, RentalMedia
    with fixture.app.app_context():
        model = Product if kind == "product" else RentalListing
        item = fixture.db.session.get(model, item_id)
        if kind == "product":
            originals = item.image_file.split("|")
            image_paths = [fixture.uploads / filename for filename in originals]
            item.video_file = "uploads/product_videos/original-fixture.mp4"
            video = fixture.uploads / "product_videos" / "original-fixture.mp4"
        else:
            originals = [str(row.id) for row in item.media if row.kind == "image"]
            image_paths = [fixture.static / row.file_path for row in item.media if row.kind == "image"]
            item.status = "reserved"
            video_relative = "uploads/rentals/original-fixture.mp4"
            fixture.db.session.add(RentalMedia(listing_id=item.id, kind="video", file_path=video_relative))
            video = fixture.static / video_relative
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"existing fixture video, never transcoded")
        fixture.db.session.commit()
    offer = SimpleNamespace(fixture=fixture, kind=kind, id=item_id, base=base,
                            url=f"{base}/{item_id}/edit", payload=payload,
                            originals=originals, image_paths=image_paths, video=video)
    offer.initial = _record(offer)
    offer.files = _files(fixture)
    return offer


def _post(offer, *, modal=True, **changes):
    return offer.fixture.client.post(offer.url + ("" if modal else "?standalone=1"),
                                     data={**offer.payload, **changes},
                                     headers=_headers(offer.kind) if modal else {})


def _config(html):
    match = re.search(r'<script[^>]*id="vpmFormConfig"[^>]*>(.*?)</script>', html, re.S)
    assert match, "The shared form exposes its existing media and mode"
    return json.loads(match.group(1))


def test_edit_get_uses_same_form_with_existing_values_and_private_fragment(editable_offer):
    offer = editable_offer
    response = offer.fixture.client.get(offer.url, headers=_headers(offer.kind))
    assert response.status_code == 200 and response.json["success"] is True
    html = response.json["html"]
    assert '<form' in html and 'id="vendorCreateForm"' in html
    assert '<body' not in html.lower()
    assert offer.initial["title"] in html
    assert "no-store" in response.headers["Cache-Control"]
    assert "X-Vendor-Modal" in response.headers["Vary"]
    config = _config(html)
    assert config["mode"] == "edit"
    assert {str(image["id"]) for image in config["existingImages"]} == set(offer.originals)
    assert config["existingVideo"]
    standalone = offer.fixture.client.get(offer.url + "?standalone=1")
    assert standalone.status_code == 200
    assert 'id="vendorCreateForm"' in standalone.get_data(as_text=True)
    assert _config(standalone.get_data(as_text=True)) == config
    redirect = offer.fixture.client.get(offer.url)
    assert redirect.status_code == 303
    page = "/vendor/dashboard" if offer.kind == "product" else "/owner/locations"
    assert redirect.location.endswith(f"{page}?edit_{offer.kind}={offer.id}")


def test_edit_guest_and_another_owner_cannot_load_or_change_the_offer(editable_offer):
    offer = editable_offer
    guest = offer.fixture.app.test_client()
    response = guest.get(offer.url, headers=_headers(offer.kind))
    assert response.status_code == 401 and response.is_json
    with offer.fixture.client.session_transaction() as storage:
        storage["_user_id"] = str(offer.fixture.ids.foreign_owner)
        storage["_fresh"] = True
    for response in (offer.fixture.client.get(offer.url, headers=_headers(offer.kind)), _post(offer)):
        assert response.status_code in (403, 404)
        assert response.is_json and response.json["success"] is False
    assert _record(offer) == offer.initial
    assert _files(offer.fixture) == offer.files


def test_edit_requires_real_csrf_and_keeps_record_on_rejection(editable_offer):
    offer = editable_offer
    response = _post(offer, csrf_token="invalid-fixture-token")
    assert response.status_code == 400 and response.json.get("error") == "csrf"
    assert _record(offer) == offer.initial


def test_successful_edit_changes_one_record_and_keeps_its_existing_media(editable_offer):
    offer = editable_offer
    changes = {"name": "Updated product fixture", "price": "30.25", "stock": "7"} if offer.kind == "product" else {
        "title": "Updated rental fixture", "rent": "3000.25", "deposit_required": "1", "deposit": "6000.50"}
    response = _post(offer, **changes)
    assert response.status_code == 200 and response.json["success"] is True
    updated = _record(offer)
    assert updated["count"] == offer.initial["count"]
    assert updated["title"] == changes.get("name", changes.get("title"))
    assert updated["amount"] == (3025 if offer.kind == "product" else 300025)
    assert updated["images"] == offer.initial["images"]
    if offer.kind == "location":
        assert updated["status"] == "reserved"
        assert updated["created_at"] == offer.initial["created_at"]
        assert updated["expires_at"] == offer.initial["expires_at"]
    assert _files(offer.fixture) == offer.files


@pytest.mark.parametrize("failure", ["invalid-field", "invalid-image", "commit"])
def test_failed_edit_does_not_remove_committed_media_or_leak_new_files(editable_offer, failure):
    offer = editable_offer
    changes = {"delete_images": [offer.originals[0]], "delete_video": "1",
               "images": [(_image(), "replacement.png")]}
    if failure == "invalid-field":
        changes["name" if offer.kind == "product" else "title"] = ""
    elif failure == "invalid-image":
        changes["images"].append((BytesIO(b"not a real image"), "broken.png"))
    if failure == "commit":
        with patch.object(offer.fixture.db.session, "commit", side_effect=RuntimeError("fixture commit failure")):
            response = _post(offer, **changes)
    else:
        response = _post(offer, **changes)
    assert response.status_code == (500 if failure == "commit" else 422), response.get_data(as_text=True)
    assert response.is_json and response.json["success"] is False
    assert _record(offer) == offer.initial
    assert _files(offer.fixture) == offer.files


def test_existing_and_new_photos_share_the_four_photo_limit(editable_offer):
    offer = editable_offer
    response = _post(offer, images=[(_image(), f"new-{i}.png") for i in range(3)])
    assert response.status_code == 422 and "images" in response.json["errors"]
    assert _record(offer) == offer.initial
    assert _files(offer.fixture) == offer.files


def test_explicit_photo_replacement_deletes_only_removed_photo_after_commit(editable_offer):
    offer = editable_offer
    response = _post(offer, delete_images=[offer.originals[0]], images=(_image(), "replacement.png"))
    assert response.status_code == 200 and response.json["success"] is True
    assert not offer.image_paths[0].exists()
    assert offer.image_paths[1].is_file()
    assert offer.video.is_file()
    record = _record(offer)
    images = record["images"].split("|") if offer.kind == "product" else [row for row in record["images"] if row[1] == "image"]
    assert len(images) == 2
    assert record["count"] == offer.initial["count"]


def test_video_removal_does_not_remove_other_media(editable_offer):
    offer = editable_offer
    response = _post(offer, delete_video="1")
    assert response.status_code == 200 and response.json["success"] is True
    assert not offer.video.exists()
    assert all(path.is_file() for path in offer.image_paths)
    record = _record(offer)
    if offer.kind == "product":
        assert record["video"] is None
    else:
        assert all(kind != "video" for _id, kind, _path in record["images"])


def test_unreadable_replacement_video_keeps_previous_video_and_photos(editable_offer):
    offer = editable_offer
    module = "dealnova.app.routes.vendor" if offer.kind == "product" else "dealnova.app.routes.rentals"
    service = "save_product_video" if offer.kind == "product" else "save_rental_video"
    with patch(f"{module}.{service}", side_effect=ValueError("Unreadable test video")):
        response = _post(offer, delete_images=[offer.originals[0]], delete_video="1",
                         images=(_image(), "new.png"), video=(BytesIO(b"invalid"), "invalid.mp4"))
    assert response.status_code == 422 and "video" in response.json["errors"]
    assert _record(offer) == offer.initial
    assert _files(offer.fixture) == offer.files


def test_standalone_validation_preserves_entered_values_and_renders_same_fields(editable_offer):
    offer = editable_offer
    title_field = "name" if offer.kind == "product" else "title"
    amount_field = "price" if offer.kind == "product" else "rent"
    response = _post(offer, modal=False, **{title_field: "Draft kept after error", amount_field: "-1"})
    assert response.status_code == 422
    assert not response.is_json
    html = response.get_data(as_text=True)
    assert 'id="vendorCreateForm"' in html
    assert "Draft kept after error" in html
    assert f'data-vpm-field-error="{amount_field}"' in html
    assert _record(offer) == offer.initial
    assert _files(offer.fixture) == offer.files
