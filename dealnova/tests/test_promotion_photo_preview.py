"""Promotion previews preserve the image while ordinary card covers stay compatible."""
import pytest

from dealnova.app.extensions import db
from dealnova.app.services import public_catalog
from dealnova.tests.test_public_catalog import catalogue, get, product, promotion


@pytest.mark.parametrize("kind,universe", [("physical", "products"), ("service", "services")])
def test_catalog_exposes_uncropped_preview_without_replacing_existing_cover(catalogue, monkeypatch, kind, universe):
    monkeypatch.setattr(public_catalog, "image_variant", lambda filename, size: f"{size}/{filename}")
    entry = product(catalogue, kind=kind, image_file="first.jpg|second.jpg")
    promotion(entry)
    db.session.commit()

    responses = [get(catalogue, universe=universe)]
    if kind == "physical":
        responses.append(get(catalogue, universe="promotions"))
    for response in responses:
        item = response["items"][0]
        assert item["image_url"] == "/static/uploads/thumb/first.jpg"
        assert item["image_preview_url"] == "/static/uploads/large/first.jpg"


def test_missing_photo_does_not_invent_a_preview(catalogue):
    product(catalogue, image_file="")
    db.session.commit()

    item = get(catalogue)["items"][0]
    assert item["image_url"] == item["image_preview_url"] == "/static/img/placeholders/product.svg"
