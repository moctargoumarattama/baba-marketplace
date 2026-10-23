"""Assistant-only search keeps the public catalogue's visibility and prices."""
from datetime import datetime, timedelta

import pytest

from dealnova.app.extensions import db
from dealnova.app.services.public_catalog import (
    CatalogFilters, build_public_catalog, get_public_catalog_item, parse_catalog_filters,
)
from dealnova.tests.test_public_catalog import catalogue, product, promotion, rental


def _search(catalogue, *, smart=True, **values):
    with catalogue.app.test_request_context():
        return build_public_catalog(CatalogFilters(**values), smart_search=smart)


def test_smart_search_matches_distributed_words_accents_and_simple_plurals(catalogue):
    wanted = product(catalogue, "Crème artisanale", description="Beurre de karité naturel")
    product(catalogue, "Crème ordinaire", description="Sans beurre")
    db.session.commit()

    result = _search(catalogue, q="Je cherche des cremes karites")

    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == wanted.id
    assert _search(catalogue, q="creme karite", smart=False)["items"] == []


def test_smart_search_uses_category_without_duplicating_products(catalogue):
    catalogue.food.name = "Équipements ménagers"
    wanted = product(catalogue, "Réfrigérateur compact", description="Peu encombrant")
    product(catalogue, "Autre équipement")
    db.session.commit()

    result = _search(catalogue, q="refrigerateurs equipements")

    assert result["pagination"]["total"] == 1
    assert [item["id"] for item in result["items"]] == [wanted.id]
    assert _search(catalogue, q="equipements", smart=False)["items"] == []


@pytest.mark.parametrize("universe", ["products", "services"])
def test_smart_city_and_shop_terms_fold_accents_without_crossing_universes(catalogue, universe):
    kind = "service" if universe == "services" else "physical"
    wanted = product(catalogue, "Électricité locale", kind=kind, shop_id=catalogue.other_shop.id)
    product(catalogue, "Électricité autre ville", kind=kind)
    product(catalogue, "Électricité autre univers", kind="physical" if kind == "service" else "service",
            shop_id=catalogue.other_shop.id)
    db.session.commit()

    result = _search(catalogue, universe=universe, q="electricite commerce", city="Sale")

    assert [item["id"] for item in result["items"]] == [wanted.id]
    assert _search(catalogue, universe=universe, city="Sale", smart=False)["items"] == []


def test_smart_rental_search_combines_property_city_and_description(catalogue):
    wanted = rental(catalogue, "Logement lumineux", property_type="studio", city="Salé",
                    description="Situé près des écoles")
    rental(catalogue, "Autre logement", property_type="apartment", city="Salé", description="Près des écoles")
    db.session.commit()

    result = _search(catalogue, universe="locations", q="studios ecoles", city="Sale")

    assert [item["id"] for item in result["items"]] == [wanted.id]
    assert _search(catalogue, universe="locations", city="Sale", smart=False)["items"] == []


def test_smart_shop_search_requires_all_terms_across_public_fields(catalogue):
    catalogue.other_shop.description = "Spécialités africaines"
    catalogue.hidden_shop.description = "Spécialités africaines"
    db.session.commit()

    result = _search(catalogue, universe="shops", q="commerces specialites", city="Sale")

    assert [item["id"] for item in result["items"]] == [catalogue.other_shop.id]
    assert result["items"][0]["description"] == "Spécialités africaines"


def test_smart_search_pagination_still_has_exact_sql_total_and_discount_filter(catalogue):
    for index in range(19):
        entry = product(catalogue, f"Crème {index}", description="Karité local", price=100)
        promotion(entry, value=50)
    product(catalogue, "Crème invisible", description="Karité", is_active=False)
    product(catalogue, "Crème boutique invisible", description="Karité", shop_id=catalogue.hidden_shop.id)
    product(catalogue, "Crème plus chère", description="Karité", price=100)
    db.session.commit()

    result = _search(catalogue, q="cremes karites", max_price=60, per_page=5, page=4)

    assert result["pagination"] == dict(page=4, pages=4, total=19, per_page=5, has_next=False, has_prev=True)
    assert len(result["items"]) == 4
    assert all(item["final_price"] == 50 and item["has_promo"] for item in result["items"])


def test_inspector_returns_catalogue_price_type_description_and_booking(catalogue):
    article = product(catalogue, "Crème détaillée", description="Détails publics", price=120)
    promotion(article, value=25)
    service = product(catalogue, "Réparation", kind="service", stock=0, category_id=catalogue.services.id)
    home = rental(catalogue, "Studio détaillé", slug="studio-detaille")
    db.session.commit()

    with catalogue.app.test_request_context():
        listed = build_public_catalog(CatalogFilters(q="Crème détaillée"))["items"][0]
        assert get_public_catalog_item("product", article.id) == listed
        assert listed["final_price"] == 90
        assert listed["description"] == "Détails publics"
        assert get_public_catalog_item("service", service.id)["booking_url"] == f"/booking/{service.id}"
        assert get_public_catalog_item("location", home.id)["url"] == "/location/studio-detaille"
        assert get_public_catalog_item("shop", catalogue.shop.id)["name"] == catalogue.shop.name
        assert get_public_catalog_item("service", article.id) is None
        assert get_public_catalog_item("product", service.id) is None


def test_inspector_rejects_private_expired_deleted_and_wrong_type_items(catalogue):
    inactive = product(catalogue, is_active=False)
    hidden = product(catalogue, shop_id=catalogue.hidden_shop.id)
    legacy = product(catalogue, kind="location")
    expired = rental(catalogue, "Expirée", expires_at=datetime.utcnow() - timedelta(days=1))
    taken = rental(catalogue, "Déjà louée", status="taken")
    hidden_home = rental(catalogue, "Annonce cachée", shop_id=catalogue.hidden_shop.id)
    db.session.commit()

    with catalogue.app.test_request_context():
        for item_type, item_id in (("product", inactive.id), ("product", hidden.id), ("product", legacy.id),
                                   ("location", expired.id), ("location", taken.id), ("location", hidden_home.id),
                                   ("shop", catalogue.hidden_shop.id), ("product", 999999), ("admin", 1),
                                   ("product", -1), ("product", True), ("product", "1")):
            assert get_public_catalog_item(item_type, item_id) is None


def test_default_catalogue_keeps_phrase_search_filters_and_response_shape(catalogue):
    wanted = product(catalogue, "Beurre de karité", description="Crème")
    db.session.commit()

    with catalogue.app.test_request_context():
        filters = CatalogFilters(q="Beurre de karité")
        assert build_public_catalog(filters) == build_public_catalog(filters, smart_search=False)
        response = build_public_catalog(filters)
        assert set(response) == {"success", "items", "facets", "pagination", "filters"}
        assert response["items"][0]["id"] == wanted.id
        assert build_public_catalog(CatalogFilters(q="beurre karite"))["items"] == []


def test_shareable_smart_filter_matches_assistant_results_and_keeps_facets_independent(catalogue):
    wanted = product(catalogue, "Crème locale", description="Karité", shop_id=catalogue.other_shop.id)
    product(catalogue, "Savon ordinaire")
    db.session.commit()

    with catalogue.app.test_request_context():
        parsed = parse_catalog_filters({"q": "cremes karites", "city": "Sale", "smart": "1"})
        shared = build_public_catalog(parsed)
        assistant = build_public_catalog(CatalogFilters(q="cremes karites", city="Sale"), smart_search=True)
        ordinary = build_public_catalog(CatalogFilters())

    assert parsed.smart is True
    assert shared["items"] == assistant["items"]
    assert [item["id"] for item in shared["items"]] == [wanted.id]
    assert shared["facets"] == assistant["facets"] == ordinary["facets"]
    assert ordinary["pagination"]["total"] == 2
    response = catalogue.client.get("/api/catalog", query_string={"q": "cremes karites", "city": "Sale", "smart": "1"})
    assert response.status_code == 200
    assert response.json["items"] == shared["items"]


@pytest.mark.parametrize("raw,expected", [("1", True), ("true", True), ("0", False), ("false", False), ("", False)])
def test_smart_filter_uses_strict_boolean_values(raw, expected):
    assert parse_catalog_filters({"smart": raw}).smart is expected


@pytest.mark.parametrize("raw", ["yes", "2", "false OR 1=1"])
def test_invalid_smart_filter_is_rejected(catalogue, raw):
    response = catalogue.client.get("/api/catalog", query_string={"smart": raw})
    assert response.status_code == 400
    assert response.json["success"] is False
