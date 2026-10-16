from datetime import datetime, timedelta
from types import SimpleNamespace

from flask import Flask
import pytest

from dealnova.app.extensions import db
from dealnova.app.models.category import Category
from dealnova.app.models.product import Product
from dealnova.app.models.promo import Promo
from dealnova.app.models.rental import RentalListing, RentalMedia
from dealnova.app.models.shop import Shop
from dealnova.app.models.user import User
from dealnova.app.routes.api import bp
from dealnova.app.services.pricing import final_price_cents


@pytest.fixture()
def catalogue(tmp_path):
    app = Flask("public-catalog-tests")
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECURITY_RATE_LIMIT_ENABLED=False,
                      UPLOAD_FOLDER=str(tmp_path / "uploads"))
    db.init_app(app)
    app.register_blueprint(bp)
    for endpoint, rule in {
        "shop.product_detail": "/shop/product/<int:pid>", "booking.book": "/booking/<int:pid>",
        "rentals.location_detail": "/location/<slug>", "shops.shop_detail": "/shops/<shop_slug>",
    }.items():
        app.add_url_rule(rule, endpoint, lambda **kwargs: "")
    with app.app_context():
        # Never invoke create_app(): every connection here is the memory database.
        assert db.engine.url.database == ":memory:"
        db.create_all()
        owner = User(username="catalog-vendor", email="catalog@example.test", password_hash="test", role="vendor")
        db.session.add(owner)
        db.session.flush()
        food = Category(name="Produits", slug="produits", category_type="products")
        services = Category(name="Services", slug="services", category_type="services")
        shops = [Shop(name=name, slug=slug, vendor_id=owner.id, address=address, is_active=active,
                      allowed_types_json='["products", "services", "location"]')
                 for name, slug, address, active in (
                     ("Commerce Rabat", "rabat", "Agdal, Rabat", True),
                     ("Commerce Salé", "sale", "Centre, Salé", True),
                     ("Commerce caché", "cache", "Kénitra", False),
                 )]
        db.session.add_all([food, services, *shops])
        db.session.commit()
        yield SimpleNamespace(app=app, client=app.test_client(), food=food, services=services,
                              shop=shops[0], other_shop=shops[1], hidden_shop=shops[2], owner=owner)
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def product(catalogue, name="Article", **options):
    values = dict(name=name, price=100, stock=3, kind="physical", shop_id=catalogue.shop.id,
                  category_id=catalogue.food.id, vendor_id=catalogue.owner.id)
    values.update(options)
    entry = Product(**values)
    db.session.add(entry)
    db.session.flush()
    return entry


def rental(catalogue, title="Location", **options):
    values = dict(title=title, slug=title.lower().replace(" ", "-"), description="Logement public",
                  owner_id=catalogue.owner.id, shop_id=catalogue.shop.id, city="Rabat", area="Agdal",
                  rent_cents=350000, listing_type="monthly", property_type="apartment", status="active",
                  is_active=True, expires_at=datetime.utcnow() + timedelta(days=7))
    values.update(options)
    entry = RentalListing(**values)
    db.session.add(entry)
    db.session.flush()
    return entry


def promotion(entry, **options):
    values = dict(product_id=entry.id, type="percentage", value=25, status="approved",
                  end_date=datetime.utcnow() + timedelta(days=1))
    values.update(options)
    promo = Promo(**values)
    db.session.add(promo)
    db.session.flush()
    return promo


def get(catalogue, **filters):
    response = catalogue.client.get("/api/catalog", query_string=filters)
    assert response.status_code == 200, response.json
    return response.json


def test_catalogue_reaches_products_beyond_sixty_with_exact_sql_pagination(catalogue):
    for index in range(83):
        product(catalogue, f"Article {index:02}", price=index + 1)
    product(catalogue, "Inactif", is_active=False)
    product(catalogue, "Boutique cachée", shop_id=catalogue.hidden_shop.id)
    db.session.commit()

    first = get(catalogue, sort="low", per_page=12)
    last = get(catalogue, sort="low", page=7, per_page=12)
    found = get(catalogue, q="Article 82")

    assert first["pagination"] == dict(page=1, pages=7, total=83, per_page=12, has_prev=False, has_next=True)
    assert [item["final_price"] for item in first["items"]] == list(range(1, 13))
    assert [item["final_price"] for item in last["items"]] == list(range(73, 84))
    assert last["pagination"]["has_next"] is False
    assert len(found["items"]) == 1
    assert found["items"][0]["name"] == "Article 82"


def test_product_filters_apply_before_pagination_and_use_public_visibility(catalogue):
    wanted = product(catalogue, "Savon local", price=35)
    product(catalogue, "Savon épuisé", price=35, stock=0)
    product(catalogue, "Savon autre ville", price=35, shop_id=catalogue.other_shop.id)
    product(catalogue, "Autre catégorie", price=35, category_id=catalogue.services.id)
    product(catalogue, "Savon trop cher", price=200)
    product(catalogue, "Ancienne fausse location", kind="location")
    db.session.commit()

    result = get(catalogue, q="Savon", cat=catalogue.food.id, shop=catalogue.shop.id,
                 city="Rabat", min_price=30, max_price=40, stock=1)

    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == wanted.id
    assert result["items"][0]["available"] is True
    assert result["items"][0]["shop_name"] == "Commerce Rabat"


def test_services_have_booking_links_and_never_leak_into_products(catalogue):
    product(catalogue)
    service = product(catalogue, "Coiffure", kind="service", stock=0, category_id=catalogue.services.id)
    db.session.commit()

    result = get(catalogue, universe="services", stock=1)

    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["id"] == service.id
    assert item["item_type"] == item["kind"] == "service"
    assert item["booking_url"] == f"/booking/{service.id}"
    assert item["available"] is True
    assert all(item["kind"] == "physical" for item in get(catalogue)["items"])


def test_only_real_approved_discounts_are_promotions_and_price_filters_use_discount(catalogue):
    good = product(catalogue, "Promotion réelle")
    promotion(good, value=30)
    for name, options in (("En attente", {"status": "pending"}), ("Refusée", {"status": "rejected"}),
                          ("Expirée", {"end_date": datetime.utcnow() - timedelta(days=1)}),
                          ("Sans remise", {"value": 0})):
        promotion(product(catalogue, name), **options)
    db.session.commit()

    result = get(catalogue, universe="promotions", min_price=65, max_price=75)

    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == good.id
    assert result["items"][0]["price"] == 100
    assert result["items"][0]["final_price"] == 70
    assert result["items"][0]["has_promo"] is True


def test_nearest_promotion_and_cent_rounding_match_checkout(catalogue):
    entry = product(catalogue, price=0.03)
    nearest = promotion(entry, value=50)
    promotion(entry, value=100, end_date=datetime.utcnow() + timedelta(days=2))
    free = product(catalogue, "Remise plafonnée", price=10)
    promotion(free, value=150)
    expected = final_price_cents(entry, nearest) / 100
    db.session.commit()

    result = get(catalogue, universe="promotions", sort="low")

    assert [item["final_price"] for item in result["items"]] == [0, expected]
    assert get(catalogue, min_price=0.02, max_price=0.02)["items"][0]["id"] == entry.id


def test_rental_filters_aliases_media_and_visibility_use_real_listings(catalogue):
    wanted = rental(catalogue, "Studio Rabat", property_type="studio", rent_cents=250000)
    db.session.add(RentalMedia(listing_id=wanted.id, kind="image", file_path="uploads/rentals/studio.webp"))
    rental(catalogue, "Autre ville", city="Salé", shop_id=catalogue.other_shop.id)
    rental(catalogue, "Expirée", expires_at=datetime.utcnow() - timedelta(days=1))
    rental(catalogue, "Inactive", is_active=False)
    rental(catalogue, "Fermée", status="taken")
    rental(catalogue, "Boutique cachée", shop_id=catalogue.hidden_shop.id)
    db.session.commit()

    result = get(catalogue, universe="locations", city="Rabat", type="monthly", property_type="studio", min=2000, max=2600)

    assert result["pagination"]["total"] == 1
    item = result["items"][0]
    assert item["id"] == wanted.id
    assert item["item_type"] == item["kind"] == "location"
    assert item["image_url"] == "/static/uploads/rentals/studio.webp"
    assert item["url"] == "/location/studio-rabat"
    assert item["stock"] is None
    assert result["filters"]["listing_type"] == "monthly"
    assert result["filters"]["min_price"] == 2000


def test_search_unifies_sources_with_exact_total_and_price_order(catalogue):
    product(catalogue, "Commerce produit", price=10)
    product(catalogue, "Commerce service", kind="service", price=20)
    rental(catalogue, "Commerce location", rent_cents=3000)
    db.session.commit()

    result = get(catalogue, universe="search", q="Commerce", sort="low", per_page=2)
    second = get(catalogue, universe="search", q="Commerce", sort="low", per_page=2, page=2)
    third = get(catalogue, universe="search", q="Commerce", sort="low", per_page=2, page=3)

    assert result["pagination"]["total"] == 5  # Three offers and the two active shops.
    assert [item["item_type"] for item in result["items"]] == ["product", "service"]
    assert [item["item_type"] for item in second["items"]] == ["location", "shop"]
    assert third["items"][0]["item_type"] == "shop"
    assert third["items"][0]["price"] is None
    identities = [(item["item_type"], item["id"]) for page in (result, second, third) for item in page["items"]]
    assert len(set(identities)) == 5


def test_shop_filter_search_returns_its_offers_without_duplicating_the_shop(catalogue):
    product(catalogue)
    product(catalogue, "Service", kind="service")
    rental(catalogue)
    product(catalogue, "Autre boutique", shop_id=catalogue.other_shop.id)
    db.session.commit()

    result = get(catalogue, universe="search", shop=catalogue.shop.id)

    assert result["pagination"]["total"] == 3
    assert {item["item_type"] for item in result["items"]} == {"product", "service", "location"}
    assert all(item["shop_id"] == catalogue.shop.id for item in result["items"])


def test_shop_preview_bounds_loaded_offers_and_preserves_full_legacy_response(catalogue):
    for index in range(65):
        product(catalogue, f"Produit {index}")
    product(catalogue, "Inactif", is_active=False)
    db.session.commit()

    preview = catalogue.client.get(f"/api/shop/{catalogue.shop.slug}?preview=1")
    legacy = catalogue.client.get(f"/api/shop/{catalogue.shop.slug}")

    assert preview.status_code == legacy.status_code == 200
    assert len(preview.json["products"]) == 6
    assert preview.json["product_count"] == 65
    assert preview.json["products_preview"] is True
    assert len(legacy.json["products"]) == 65
    assert legacy.json["product_count"] == 65
    assert legacy.json["products_preview"] is False


def test_facets_match_universe_and_exclude_hidden_inventory(catalogue):
    product(catalogue)
    product(catalogue, "Service", kind="service", shop_id=catalogue.other_shop.id, category_id=catalogue.services.id)
    product(catalogue, "Caché", shop_id=catalogue.hidden_shop.id)
    rental(catalogue)
    db.session.commit()

    products = get(catalogue, q="aucun résultat")["facets"]
    services = get(catalogue, universe="services")["facets"]
    locations = get(catalogue, universe="locations")["facets"]

    assert products["categories"] == [{"id": catalogue.food.id, "name": "Produits"}]
    assert products["shops"] == [{"id": catalogue.shop.id, "name": "Commerce Rabat"}]
    assert products["cities"] == ["Rabat"]
    assert services["categories"] == [{"id": catalogue.services.id, "name": "Services"}]
    assert services["shops"] == [{"id": catalogue.other_shop.id, "name": "Commerce Salé"}]
    assert locations["categories"] == []
    assert locations["cities"] == ["Rabat"]


def test_shops_are_public_and_missing_prices_are_not_zero(catalogue):
    result = get(catalogue, universe="shops", city="Salé")

    assert result["pagination"]["total"] == 1
    item = result["items"][0]
    assert item["id"] == catalogue.other_shop.id
    assert item["price"] is item["final_price"] is None
    assert item["url"] == "/shops/sale"
    assert item["slug"] == "sale"


def test_limits_empty_results_and_out_of_range_pages_are_consistent(catalogue):
    empty = get(catalogue, page=999)
    assert empty["items"] == []
    assert empty["pagination"] == dict(page=1, pages=0, total=0, per_page=12, has_prev=False, has_next=False)
    for index in range(30):
        product(catalogue, f"Produit {index}")
    db.session.commit()
    result = get(catalogue, page=999, per_page=999)
    assert len(result["items"]) == 6
    assert result["pagination"] == dict(page=2, pages=2, total=30, per_page=24, has_prev=True, has_next=False)


@pytest.mark.parametrize("filters", [
    {"universe": "admin"}, {"sort": "drop table"}, {"cat": "-1"}, {"shop": "abc"},
    {"page": "0"}, {"page": "NaN"}, {"page": "99999999999999999999"}, {"per_page": "0"},
    {"min_price": "NaN"}, {"max_price": "Infinity"}, {"min_price": "-1"},
    {"min_price": "10", "max_price": "2"}, {"listing_type": "sale"},
    {"property_type": "castle"}, {"stock": "yes"}, {"promo": "-1"}, {"q": "a" * 161},
])
def test_invalid_parameters_return_actionable_json_errors(catalogue, filters):
    response = catalogue.client.get("/api/catalog", query_string=filters)

    assert response.status_code == 400
    assert response.json["success"] is False
    assert response.json["error"] == "invalid_filters"
    assert response.json["message"]


def test_literal_wildcards_and_unsafe_stored_images_are_handled_safely(catalogue):
    wanted = product(catalogue, "Remise 20%", image_file="../../secret.jpg")
    product(catalogue, "Article ordinaire")
    db.session.commit()

    result = get(catalogue, q="%")

    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == wanted.id
    assert result["items"][0]["image_url"] == "/static/img/placeholders/product.svg"
    assert get(catalogue, q="' OR 1=1 --")["pagination"]["total"] == 0
