"""Half-hour discovery changes order without changing public visibility."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from dealnova.app.extensions import db
from dealnova.app.models.rental import RentalMedia
from dealnova.app.services import public_catalog
from dealnova.tests.test_public_catalog import catalogue, get, product, promotion, rental


def clock(monkeypatch, slot=1000, seconds=30):
    current = [slot * 1800 + seconds]
    monkeypatch.setattr(public_catalog, "time", SimpleNamespace(time=lambda: current[0]))
    return current


def ids(result):
    return [item["id"] for item in result["items"]]


@pytest.mark.parametrize("universe", ["products", "services", "promotions", "locations"])
def test_discovery_prioritizes_images_and_videos_without_hiding_plain_offers(catalogue, monkeypatch, universe):
    clock(monkeypatch)
    entries = []
    for index, media in enumerate(("image", "video", "", " ", "image")):
        if universe == "locations":
            entry = rental(catalogue, f"Location {index}")
            if media:
                db.session.add(RentalMedia(listing_id=entry.id,
                                           kind="video" if media == "video" else "image",
                                           file_path=f"cover.{media}" if media.strip() else "  "))
        else:
            entry = product(catalogue, f"Offre {index}", kind="service" if universe == "services" else "physical",
                            image_file="cover.jpg" if media == "image" else media if media != "video" else None,
                            video_file="movie.mp4" if media == "video" else None)
            if universe == "promotions":
                promotion(entry)
        entries.append(entry.id)
    db.session.commit()

    result = get(catalogue, universe=universe, sort="discover")

    assert set(ids(result)[:3]) == {entries[0], entries[1], entries[4]}
    assert set(ids(result)[3:]) == {entries[2], entries[3]}
    assert result["pagination"]["total"] == 5
    assert result["rotation"] == {"slot": 1000, "refresh_at": 1001 * 1800, "interval": 1800,
                                  "refresh_in": 1770}
    assert result["filters"]["rotation_slot"] == 1000


@pytest.mark.parametrize("media", [None, "photo.jpg"])
def test_rotation_is_stable_and_gives_every_offer_a_turn(catalogue, monkeypatch, media):
    current = clock(monkeypatch)
    entries = [product(catalogue, f"Article {index}", image_file=media) for index in range(5)]
    db.session.commit()

    first = get(catalogue, sort="discover")
    current[0] += 60
    assert ids(get(catalogue, sort="discover")) == ids(first)

    leaders = {ids(first)[0]}
    for slot in range(1001, 1005):
        current[0] = slot * 1800
        following = get(catalogue, sort="discover")
        assert ids(following) != ids(first)
        assert set(ids(following)) == {entry.id for entry in entries}
        leaders.add(ids(following)[0])
    assert leaders == {entry.id for entry in entries}


def test_pagination_keeps_its_slot_when_the_half_hour_changes(catalogue, monkeypatch):
    current = clock(monkeypatch, seconds=1799)
    for index in range(17):
        product(catalogue, f"Article {index}", image_file="photo.jpg" if index % 3 else None)
    db.session.commit()
    expected = [get(catalogue, sort="discover", per_page=6, page=page) for page in range(1, 4)]
    first = get(catalogue, sort="discover", per_page=6)
    assert first["rotation"]["refresh_in"] == 1

    current[0] += 2  # Page 2 is requested after the next half-hour starts.
    second = get(catalogue, sort="discover", rotation_slot=first["rotation"]["slot"], page=2, per_page=6)
    third = get(catalogue, sort="discover", rotation_slot=first["rotation"]["slot"], page=3, per_page=6)
    assert ids(first) + ids(second) + ids(third) == [item for result in expected for item in ids(result)]
    assert len(set(ids(first) + ids(second) + ids(third))) == 17
    assert second["rotation"]["refresh_in"] == 0
    assert second["rotation"]["slot"] == first["rotation"]["slot"]

    # A new visit has a fresh slot, even though the facets can remain cached.
    refreshed = get(catalogue, sort="discover", per_page=6)
    assert refreshed["rotation"]["slot"] == 1001
    assert ids(refreshed) != ids(first)
    assert refreshed["facets"] == first["facets"]


def test_full_batches_take_turns_without_repeating_cards(catalogue, monkeypatch):
    current = clock(monkeypatch)
    entries = [product(catalogue, f"Article {index}", image_file="photo.jpg") for index in range(24)]
    db.session.commit()

    first = get(catalogue, sort="discover", per_page=12)
    current[0] += 1800
    following = get(catalogue, sort="discover", per_page=12)

    assert len(ids(first)) == len(ids(following)) == 12
    assert set(ids(first)).isdisjoint(ids(following))
    assert set(ids(first) + ids(following)) == {entry.id for entry in entries}


def test_single_item_batches_still_give_small_catalogues_a_fair_turn(catalogue, monkeypatch):
    current = clock(monkeypatch)
    entries = [product(catalogue, f"Article {index}", image_file="photo.jpg") for index in range(5)]
    db.session.commit()

    seen = set()
    for slot in range(1000, 1005):
        current[0] = slot * 1800
        seen.update(ids(get(catalogue, sort="discover", per_page=1)))

    assert seen == {entry.id for entry in entries}


@pytest.mark.parametrize("sort", [None, "new", "low", "high"])
def test_explicit_price_and_newest_sorts_keep_their_existing_order(catalogue, monkeypatch, sort):
    clock(monkeypatch)
    older = product(catalogue, "Ancien avec photo", image_file="photo.jpg", price=200,
                    created_at=datetime.utcnow() - timedelta(days=2))
    newer = product(catalogue, "Nouveau sans photo", price=10, created_at=datetime.utcnow())
    db.session.commit()

    result = get(catalogue, **({"sort": sort} if sort else {}))

    assert ids(result) == ([older.id, newer.id] if sort == "high" else [newer.id, older.id])
    assert "rotation" not in result
    assert result["filters"]["rotation_slot"] is None


def test_discovery_preserves_product_filters_visibility_and_real_promotions(catalogue, monkeypatch):
    clock(monkeypatch)
    wanted = product(catalogue, "Savon public", price=40, image_file="photo.jpg")
    promotion(wanted)
    product(catalogue, "Savon caché", image_file="photo.jpg", is_active=False)
    product(catalogue, "Savon boutique cachée", image_file="photo.jpg", shop_id=catalogue.hidden_shop.id)
    product(catalogue, "Savon épuisé", image_file="photo.jpg", stock=0)
    service = product(catalogue, "Savon service", image_file="photo.jpg", kind="service")
    promotion(service)
    pending = product(catalogue, "Savon en attente", image_file="photo.jpg")
    promotion(pending, status="pending")
    expired = product(catalogue, "Savon promo expirée", image_file="photo.jpg")
    promotion(expired, end_date=datetime.utcnow() - timedelta(days=1))
    db.session.commit()

    result = get(catalogue, universe="promotions", sort="discover", stock=1,
                 q="Savon", shop=catalogue.shop.id, city="Rabat", min_price=29, max_price=31)

    assert ids(result) == [wanted.id]
    assert result["items"][0]["has_promo"] is True
    assert result["items"][0]["final_price"] == 30


def test_discovery_excludes_expired_and_hidden_rentals_with_media(catalogue, monkeypatch):
    clock(monkeypatch)
    visible = rental(catalogue, "Visible")
    entries = [visible, rental(catalogue, "Expired", expires_at=datetime.utcnow() - timedelta(days=1)),
               rental(catalogue, "Hidden", is_active=False), rental(catalogue, "Taken", status="taken"),
               rental(catalogue, "Hidden shop", shop_id=catalogue.hidden_shop.id)]
    db.session.add_all([RentalMedia(listing_id=entry.id, kind="image", file_path="photo.jpg") for entry in entries])
    db.session.commit()

    result = get(catalogue, universe="locations", sort="discover", property_type="apartment", city="Rabat")

    assert ids(result) == [visible.id]


@pytest.mark.parametrize("slot", ["-1", "0", "NaN", "1.5", "2147483648", "999999999999999999"])
def test_rotation_slot_is_validated(catalogue, slot):
    response = catalogue.client.get("/api/catalog", query_string={"sort": "discover", "rotation_slot": slot})
    assert response.status_code == 400
    assert response.json["error"] == "invalid_filters"


def test_empty_rotation_is_well_formed(catalogue, monkeypatch):
    clock(monkeypatch)
    result = get(catalogue, sort="discover")
    assert result["items"] == []
    assert result["pagination"]["total"] == 0
    assert result["rotation"]["slot"] == 1000


@pytest.mark.parametrize("kind", ["physical", "service"])
@pytest.mark.parametrize("path", ["offer.mp4", "product_videos/offer.mp4", "uploads/product_videos/offer.mp4",
                                 "/static/uploads/product_videos/offer.mp4", "static/uploads/product_videos/offer.mp4"])
def test_product_video_urls_are_normalized_for_public_cards(catalogue, monkeypatch, kind, path):
    clock(monkeypatch)
    product(catalogue, "Offre vidéo", kind=kind, video_file=path)
    db.session.commit()

    result = get(catalogue, universe="services" if kind == "service" else "products", sort="discover")

    assert result["items"][0]["video_url"] == "/static/uploads/product_videos/offer.mp4"


@pytest.mark.parametrize("path", ["../../secret.mp4", "/static/uploads/product_videos/../../secret.mp4",
                                 "//example.test/video.mp4", "https://example.test/video.mp4", "/static/app.py",
                                 "uploads/product_videos/%2e%2e.mp4", "video.mp4?source=bad", "video\x00.mp4"])
def test_unsafe_video_paths_are_not_exposed_by_public_cards(catalogue, monkeypatch, path):
    clock(monkeypatch)
    product(catalogue, "Offre vidéo", video_file=path)
    db.session.commit()

    result = get(catalogue, sort="discover")

    assert result["items"][0]["video_url"] == ""
