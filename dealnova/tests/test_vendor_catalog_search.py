"""Real catalogue routes, disposable database, no application .env or media writes."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from flask import template_rendered
import pytest

from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


PARTIAL_HEADERS = {"X-Requested-With": "XMLHttpRequest", "X-Catalog-Partial": "1"}


@pytest.fixture(scope="module")
def catalog_application(tmp_path_factory):
    with isolated_vendor_application(tmp_path_factory.mktemp("vendor-catalog")) as fixture:
        from dealnova.app.models.category import Category
        from dealnova.app.models.product import Product
        from dealnova.app.models.shop import Shop
        from dealnova.app.models.user import User

        with fixture.app.app_context():
            db = fixture.db
            physical = db.session.get(Category, fixture.ids.physical)
            service = db.session.get(Category, fixture.ids.service)
            physical.name = "Épicerie fine"
            service.name = "Dépannage à domicile"
            outsider = User(username="catalog-outsider", email="catalog-outsider@example.test",
                            role="vendor", is_active=True, password_hash="test-only",
                            subscription_expires_at=datetime.utcnow() + timedelta(days=365))
            customer = User(username="catalog-customer", email="catalog-customer@example.test",
                            role="client", is_active=True, password_hash="test-only")
            foreign_category = Category(name="Catégorie étrangère", slug="foreign-catalog", category_type="products")
            db.session.add_all([outsider, customer, foreign_category])
            db.session.flush()
            foreign_shop = Shop(name="Autre boutique", slug="foreign-catalog", vendor_id=outsider.id,
                                is_active=True, primary_type="products", allowed_types_json='["products"]')
            db.session.add(foreign_shop)
            db.session.flush()

            def offer(name, **changes):
                data = dict(name=name, description="Article ordinaire", kind="physical", price=30,
                            price_cents_value=3000, stock=10, vendor_id=fixture.ids.vendor,
                            shop_id=fixture.ids.shop, category_id=physical.id, is_active=True,
                            image_file="fixture-placeholder.webp", created_at=datetime.utcnow())
                data.update(changes)
                value = Product(**data)
                db.session.add(value)
                db.session.flush()
                return value.id

            fixture.target = SimpleNamespace(
                coffee=offer("CAFÉ Équitable", description="Moulu à Rabat, livraison rapide",
                             stock=4, created_at=datetime.utcnow() - timedelta(days=10)),
                service=offer("Réparation électrique", description="Intervention atelier", kind="service",
                              stock=0, category_id=service.id, is_active=False),
                literal=offer("Offre 100%_ spéciale", description=r"Chemin a\b de démonstration"),
                single=offer("X", description=None),
                uncategorized=offer("Objet sans catégorie", category_id=None, description=None),
                outsider=outsider.id, customer=customer.id, foreign_category=foreign_category.id,
            )
            for index in range(25):
                offer(f"Article ordinaire {index:02d}", is_active=index % 5 != 0)
            fixture.target.foreign = offer("CAFÉ Équitable SECRET", vendor_id=outsider.id,
                                           shop_id=foreign_shop.id, category_id=foreign_category.id)
            db.session.commit()
        yield fixture


@pytest.fixture()
def catalog(catalog_application):
    fixture = catalog_application
    client = fixture.app.test_client()
    with client.session_transaction() as storage:
        storage["_user_id"] = str(fixture.ids.vendor)
        storage["_fresh"] = True
    return SimpleNamespace(**vars(fixture), client=client)


def _get(fixture, *, partial=False, **query):
    contexts = []

    def rendered(sender, template, context, **extra):
        if template.name in {"vendor/catalog.html", "vendor/partials/_catalog_results.html"}:
            contexts.append(dict(context))

    with template_rendered.connected_to(rendered, fixture.app):
        response = fixture.client.get("/vendor/catalog", query_string=query,
                                      headers=PARTIAL_HEADERS if partial else {})
    assert response.status_code == 200
    assert contexts
    context = contexts[-1]
    ids = [product.id for product in context["products"]]
    return response, context, ids


@pytest.mark.parametrize("query,target", [
    ("cafe", "coffee"), ("CAFÉ", "coffee"), ("Cafe\u0301", "coffee"),
    ("équitable", "coffee"), ("livraison rapide", "coffee"),
    ("cafe livraison epicerie", "coffee"), ("EPICERIE MOUlu rabat", "coffee"),
    ("depannage atelier", "service"), ("reparation ELECTRIQUE", "service"),
    ("x", "single"), ("100%_", "literal"), ("%", "literal"),
    ("_", "literal"), (r"a\b", "literal"),
])
def test_search_is_identical_for_full_page_and_live_response(catalog, query, target):
    expected = [getattr(catalog.target, target)]
    response, full, full_ids = _get(catalog, q=query)
    partial, live, live_ids = _get(catalog, partial=True, q=query)
    assert full_ids == live_ids == expected
    assert partial.json["total"] == 1
    assert live["pagination"].total == full["pagination"].total == 1
    assert partial.json["summary"] == {"total": 30, "active": 24, "inactive": 6,
                                        "physical": 29, "service": 1}


def test_search_finds_offer_beyond_first_page_without_loading_all_results(catalog):
    _, context, first_page = _get(catalog)
    assert len(first_page) == 24 and context["pagination"].total == 30
    assert catalog.target.coffee not in first_page
    _, _, ids = _get(catalog, q="cafe")
    assert ids == [catalog.target.coffee]


def test_multiple_words_are_required_even_when_they_span_different_fields(catalog):
    _, _, ids = _get(catalog, q="cafe introuvable")
    assert ids == []
    _, _, ids = _get(catalog, q="  ÉPICERIE\n\t équitable  ")
    assert ids == [catalog.target.coffee]


@pytest.mark.parametrize("prefix", ["", "#"])
def test_exact_product_reference_is_searchable(catalog, prefix):
    response, _, ids = _get(catalog, partial=True, q=f"{prefix}{catalog.target.coffee}")
    assert catalog.target.coffee in ids
    if prefix:
        assert ids == [catalog.target.coffee]
        assert response.json["total"] == 1
    _, _, ids = _get(catalog, q=f"{prefix}{catalog.target.coffee} cafe")
    assert ids == [catalog.target.coffee]


@pytest.mark.parametrize("query", ["#999999999999999999999", "%' OR 1=1 --", "cafe secret", "Article zzz"])
def test_nonmatching_input_and_injection_strings_do_not_broaden_results(catalog, query):
    response, _, ids = _get(catalog, partial=True, q=query)
    assert ids == [] and response.json["total"] == 0


@pytest.mark.parametrize("invalid_category", ["999999", "not-an-id", "-1", "foreign"])
def test_invalid_categories_are_cleared_consistently(catalog, invalid_category):
    value = catalog.target.foreign_category if invalid_category == "foreign" else invalid_category
    _, full, ids = _get(catalog, category_id=value)
    partial, live, live_ids = _get(catalog, partial=True, category_id=value)
    assert full["selected_category_id"] is live["selected_category_id"] is None
    assert partial.json["selected_category_id"] is None
    assert full["pagination"].total == partial.json["total"] == 30
    assert ids == live_ids


def test_categories_scope_and_pagination_remain_composable(catalog):
    response, _, ids = _get(catalog, partial=True, category_id=catalog.ids.service, q="atelier")
    assert ids == [catalog.target.service]
    assert response.json["selected_category_id"] == catalog.ids.service
    categories = response.json["categories"]
    assert {category["id"] for category in categories} == {catalog.ids.service, catalog.ids.physical}
    assert sum(category["count"] for category in categories) == 29
    response, context, ids = _get(catalog, partial=True, q="article", per_page=12, page=2)
    assert len(ids) == 12 and response.json["total"] == 25 and response.json["pages"] == 3
    assert context["pagination"].page == 2
    assert "q=article" in context["next_page_url"] and "page=3" in context["next_page_url"]


def test_dashboard_stock_links_and_legacy_filters_keep_their_meaning(catalog):
    _, context, ids = _get(catalog, q="cafe", stock="low", kind="physical", status="active", sort="oldest")
    assert ids == [catalog.target.coffee]
    assert context["selected_stock"] == "low"
    _, _, ids = _get(catalog, q="cafe", stock="out")
    assert ids == []
    _, _, ids = _get(catalog, status="inactive", kind="service")
    assert ids == [catalog.target.service]


def test_partial_refresh_recalculates_global_stats_and_category_options(catalog):
    from dealnova.app.models.category import Category
    from dealnova.app.models.product import Product
    with catalog.app.app_context():
        category = Category(name="Nouveauté temporaire", slug="catalog-refresh-fixture", category_type="products")
        catalog.db.session.add(category)
        catalog.db.session.flush()
        product = Product(name="Nouvelle offre", kind="physical", description="Test temporaire", price=40,
                          stock=1, is_active=True, vendor_id=catalog.ids.vendor, shop_id=catalog.ids.shop,
                          category_id=category.id)
        catalog.db.session.add(product)
        catalog.db.session.commit()
        category_id, product_id = category.id, product.id
    try:
        response, _, _ = _get(catalog, partial=True, q="introuvable")
        assert response.json["total"] == 0
        assert response.json["summary"]["total"] == 31
        assert response.json["summary"]["active"] == 25
        assert {"id": category_id, "name": "Nouveauté temporaire", "count": 1} in response.json["categories"]
    finally:
        with catalog.app.app_context():
            catalog.db.session.delete(catalog.db.session.get(Product, product_id))
            catalog.db.session.delete(catalog.db.session.get(Category, category_id))
            catalog.db.session.commit()


def test_foreign_vendor_sees_only_their_catalogue(catalog):
    with catalog.client.session_transaction() as storage:
        storage["_user_id"] = str(catalog.target.outsider)
    response, _, ids = _get(catalog, partial=True, q="cafe")
    assert ids == [catalog.target.foreign]
    assert response.json["summary"]["total"] == 1
    assert len(response.json["categories"]) == 1
    assert response.json["categories"][0]["id"] == catalog.target.foreign_category


@pytest.mark.parametrize("shop_type,expected_total,expected_kind", [
    ("products", 29, "physical"), ("services", 1, "service"),
])
def test_shop_type_permissions_scope_results_summary_and_categories(catalog, shop_type, expected_total, expected_kind):
    from dealnova.app.models.shop import Shop
    with catalog.app.app_context():
        shop = catalog.db.session.get(Shop, catalog.ids.shop)
        saved = (shop.primary_type, shop.allowed_types_json)
        shop.primary_type, shop.allowed_types_json = shop_type, f'["{shop_type}"]'
        catalog.db.session.commit()
    try:
        response, context, _ = _get(catalog, partial=True)
        assert response.json["total"] == response.json["summary"]["total"] == expected_total
        assert all(product.kind == expected_kind for product in context["products"])
        assert response.json["summary"][expected_kind] == expected_total
        assert len(response.json["categories"]) == 1
    finally:
        with catalog.app.app_context():
            shop = catalog.db.session.get(Shop, catalog.ids.shop)
            shop.primary_type, shop.allowed_types_json = saved
            catalog.db.session.commit()


def test_empty_catalogue_has_zero_summary_and_no_category_options(catalog):
    from dealnova.app.models.product import Product
    with catalog.client.session_transaction() as storage:
        storage["_user_id"] = str(catalog.target.outsider)
    with catalog.app.app_context():
        product = catalog.db.session.get(Product, catalog.target.foreign)
        product.vendor_id = None
        catalog.db.session.commit()
    try:
        response, _, ids = _get(catalog, partial=True)
        assert ids == [] and response.json["total"] == 0
        assert response.json["summary"] == {"total": 0, "active": 0, "inactive": 0, "physical": 0, "service": 0}
        assert response.json["categories"] == []
    finally:
        with catalog.app.app_context():
            product = catalog.db.session.get(Product, catalog.target.foreign)
            product.vendor_id = catalog.target.outsider
            catalog.db.session.commit()


@pytest.mark.parametrize("role", ["guest", "customer"])
def test_catalogue_requires_vendor_access(catalog, role):
    with catalog.client.session_transaction() as storage:
        storage.clear()
        if role == "customer":
            storage["_user_id"] = str(catalog.target.customer)
    response = catalog.client.get("/vendor/catalog", headers=PARTIAL_HEADERS)
    assert response.status_code in (302, 303)
    assert not response.is_json
