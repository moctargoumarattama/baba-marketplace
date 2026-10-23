"""Assistant journeys use disposable catalogue data and never an AI/network key."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


@pytest.fixture(scope="module")
def assistant_catalog(tmp_path_factory):
    with isolated_vendor_application(tmp_path_factory.mktemp("assistant-flows")) as fixture:
        from dealnova.app.models.category import Category
        from dealnova.app.models.product import Product
        from dealnova.app.models.promo import Promo
        from dealnova.app.models.rental import RentalListing
        from dealnova.app.models.shop import Shop
        from dealnova.app.models.user import User

        fixture.app.config.update(
            GEMINI_API_KEY="", ANALYTICS_ENABLED=False,
            PUBLIC_BASE_URL="http://localhost",
        )
        with fixture.app.app_context():
            shop = fixture.db.session.get(Shop, fixture.ids.shop)
            shop.name = "Marche des univers"
            shop.set_allowed_types(["products", "services", "location"])
            categories = {
                "home": Category(name="Maison", slug="assistant-maison", category_type="products"),
                "beauty": Category(name="Beauté", slug="assistant-beaute", category_type="products"),
                "it": Category(name="Informatique", slug="assistant-informatique", category_type="services"),
                "empty": Category(name="Categorie sans annonce", slug="assistant-empty", category_type="products"),
            }
            fixture.db.session.add_all(categories.values())
            hidden_vendor = User(username="assistant-hidden", email="assistant-hidden@example.test",
                                 role="vendor", is_active=True, password_hash="unused-test-password")
            fixture.db.session.add(hidden_vendor)
            fixture.db.session.flush()
            hidden_shop = Shop(name="Boutique invisible", slug="assistant-hidden", vendor_id=hidden_vendor.id,
                               primary_type="products", is_active=False)
            fixture.db.session.add(hidden_shop)
            fixture.db.session.flush()

            def product(name, category, **changes):
                values = dict(name=name, description=name, kind="physical", price=100, stock=3,
                              category_id=categories[category].id, vendor_id=fixture.ids.vendor,
                              shop_id=shop.id, is_active=True)
                values.update(changes)
                return Product(**values)

            records = {
                "home": product("Lampe Maison", "home", price=15),
                "beauty": product("Savon Beauté", "beauty", price=45),
                "luxury": product("Canape Maison prestige", "home", price=25001),
                "promo": product("Table Maison promotion", "home", price=500),
                "it": product("Assistance Informatique", "it", kind="service", price=120, stock=0),
                "soldout": product("Article en rupture", "home", stock=0),
                "inactive": product("Produit inactif", "home", is_active=False),
                "hidden": product("Produit boutique invisible", "home", shop_id=hidden_shop.id,
                                  vendor_id=hidden_vendor.id),
            }
            fixture.db.session.add_all(records.values())
            fixture.db.session.flush()
            fixture.db.session.add(Promo(product_id=records["promo"].id, type="percentage", value=50,
                                         status=Promo.STATUS_APPROVED,
                                         end_date=datetime.utcnow() + timedelta(days=7)))

            def rental(title, slug, **changes):
                values = dict(title=title, slug=slug, description=title,
                              owner_id=fixture.ids.vendor, shop_id=shop.id, city="Rabat",
                              rent_cents=250000, is_active=True, status="active",
                              expires_at=datetime.utcnow() + timedelta(days=7))
                values.update(changes)
                return RentalListing(**values)

            rentals = [rental("Maison a louer", "assistant-maison-active"),
                       rental("Maison reservee", "assistant-maison-reserved", status="reserved"),
                       rental("Maison expiree", "assistant-maison-expired",
                              expires_at=datetime.utcnow() - timedelta(days=1)),
                       rental("Maison boutique invisible", "assistant-maison-hidden",
                              shop_id=hidden_shop.id, owner_id=hidden_vendor.id)]
            fixture.db.session.add_all(rentals)
            fixture.db.session.commit()
            fixture.records = SimpleNamespace(**{name: item.id for name, item in records.items()})
            fixture.categories = SimpleNamespace(**{name: item.id for name, item in categories.items()})
        yield fixture


@pytest.fixture()
def assistant(assistant_catalog):
    fixture = SimpleNamespace(**vars(assistant_catalog))
    fixture.client = fixture.app.test_client()
    # Any unintended AI call fails before it could reach an external service.
    with patch("dealnova.app.assistant.engine._reply_with_gemini",
               side_effect=AssertionError("This deterministic journey must not call Gemini")):
        yield fixture


def _message(fixture, **params):
    response = fixture.client.get("/api/assistant/message", query_string=params)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["response"]["text"]
    return payload["response"]


def _titles(response):
    return {item["title"] for item in response.get("items", [])}


def _kind(fixture):
    from dealnova.app.assistant.engine import ASSISTANT_SESSION_KEY

    with fixture.client.session_transaction() as storage:
        return storage[ASSISTANT_SESSION_KEY]["context"].get("kind")


@pytest.mark.parametrize("action,kind,expected,forbidden", [
    ("find_products", "products", "Lampe Maison", "Assistance Informatique"),
    ("find_services", "services", "Assistance Informatique", "Lampe Maison"),
    ("find_locations", "locations", "Maison a louer", "Lampe Maison"),
    ("find_shops", "shops", "Marche des univers", "Boutique invisible"),
])
def test_entry_points_show_the_right_available_items_immediately(assistant, action, kind, expected, forbidden):
    response = _message(assistant, action=action)
    assert expected in _titles(response)
    assert forbidden not in _titles(response)
    assert response.get("quick_layout") != "menu"
    assert "budget maximum" not in response["text"].casefold()
    assert _kind(assistant) == kind


def test_product_categories_come_from_public_inventory_instead_of_generic_suggestions(assistant):
    response = _message(assistant, action="find_products")
    choices = {str(choice.get("value")): choice["label"]
               for choice in response.get("quick_replies", [])
               if choice.get("action") == "catalog_category"}
    assert choices[str(assistant.categories.home)] == "Articles pour la maison"
    assert choices[str(assistant.categories.beauty)] == "Produits de beauté"
    assert str(assistant.categories.it) not in choices
    assert str(assistant.categories.empty) not in choices
    assert not {"Cadeau", "Vêtements"} & set(choices.values())


def test_category_filter_stays_in_product_universe(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, action="catalog_category", value=str(assistant.categories.home))
    assert "Lampe Maison" in _titles(response)
    assert "Savon Beauté" not in _titles(response)
    assert "Maison a louer" not in _titles(response)
    assert _kind(assistant) == "products"


@pytest.mark.parametrize("query,expected", [("Maison", "Lampe Maison"), ("Beauté", "Savon Beauté")])
def test_ambiguous_product_queries_never_switch_to_service_or_rental(assistant, query, expected):
    _message(assistant, action="find_products")
    response = _message(assistant, action="catalog_query", value=query)
    assert expected in _titles(response)
    assert not {"Assistance Informatique", "Maison a louer"} & _titles(response)
    assert _kind(assistant) == "products"


def test_invalid_category_from_another_universe_is_not_applied(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, action="catalog_category", value=str(assistant.categories.it))
    assert "Assistance Informatique" not in _titles(response)
    assert _kind(assistant) == "products"
    followup = _message(assistant, action="catalog_query", value="Maison")
    assert "Lampe Maison" in _titles(followup)


def test_service_cards_open_the_detail_instead_of_starting_a_booking(assistant):
    response = _message(assistant, action="find_services")
    item = next(item for item in response["items"] if item["title"] == "Assistance Informatique")
    assert item["url"].endswith(f"/shop/product/{assistant.records.it}")
    assert "/book" not in item["url"]


def test_budget_is_optional_and_can_be_requested_after_results(assistant):
    initial = _message(assistant, action="find_products")
    assert "Lampe Maison" in _titles(initial)
    prompt = _message(assistant, action="catalog_filter_budget")
    assert any(choice.get("action") == "catalog_budget" for choice in prompt.get("quick_replies", []))
    response = _message(assistant, action="catalog_budget", value="300")
    assert "Table Maison promotion" in _titles(response)
    assert "Canape Maison prestige" not in _titles(response)
    assert _kind(assistant) == "products"


def test_promotion_final_price_is_used_for_budget_filter(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, action="catalog_budget", value="300")
    item = next(item for item in response["items"] if item["title"] == "Table Maison promotion")
    # Base price is 500 DH; the actual public price is 250 DH after promotion.
    assert "250" in str(item)
    below = _message(assistant, action="catalog_budget", value="249")
    assert "Table Maison promotion" not in _titles(below)


def test_small_budget_is_not_silently_raised_to_thirty_dirhams(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, action="catalog_budget", value="15")
    assert _titles(response) == {"Lampe Maison"}


def test_without_budget_does_not_hide_offers_above_twenty_thousand(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, action="catalog_budget", value="none")
    assert "Canape Maison prestige" in _titles(response)


def test_empty_search_keeps_chosen_universe_and_allows_query_without_budget(assistant):
    _message(assistant, action="find_services")
    response = _message(assistant, action="catalog_query", value="Maison inexistante xyz")
    assert not response.get("items")
    assert response.get("quick_layout") != "menu"
    assert _kind(assistant) == "services"
    followup = _message(assistant, message="Informatique")
    assert "Assistance Informatique" in _titles(followup)
    assert _kind(assistant) == "services"


def test_free_query_during_search_uses_the_same_universe_without_ai(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, message="Beauté")
    assert _titles(response) == {"Savon Beauté"}
    assert _kind(assistant) == "products"


@pytest.mark.parametrize("action,excluded", [
    ("find_products", {"Produit inactif", "Produit boutique invisible"}),
    ("find_locations", {"Maison expiree", "Maison boutique invisible"}),
    ("find_shops", {"Boutique invisible"}),
])
def test_assistant_respects_shared_public_visibility(assistant, action, excluded):
    response = _message(assistant, action=action)
    assert response.get("items")
    assert not excluded & _titles(response)


def test_fresh_first_message_discards_old_delivery_state(assistant):
    _message(assistant, action="help_delivery")
    response = _message(assistant, fresh="1", message="Je cherche une location")
    assert response.get("quick_layout") != "menu"
    assert "ville" not in response["text"].casefold()
    assert _kind(assistant) == "locations"


def test_welcome_payload_can_be_reused_without_resetting_search_state(assistant):
    from dealnova.app.assistant.engine import ASSISTANT_SESSION_KEY, assistant_welcome

    _message(assistant, action="find_services")
    with assistant.client.session_transaction() as storage:
        state = dict(storage[ASSISTANT_SESSION_KEY])
    with assistant.app.test_request_context():
        from flask import session

        session[ASSISTANT_SESSION_KEY] = state
        welcome = assistant_welcome()
        assert welcome.get("quick_layout") == "menu"
        assert session[ASSISTANT_SESSION_KEY] == state


@pytest.mark.parametrize("path,params", [
    ("/api/assistant/bootstrap", {}),
    ("/api/assistant/message", {"action": "start"}),
    ("/api/assistant/message", {"action": "reset"}),
])
def test_explicit_start_and_bootstrap_keep_the_main_menu(assistant, path, params):
    response = assistant.client.get(path, query_string=params)
    assert response.status_code == 200
    payload = response.get_json()["response"]
    assert payload["quick_layout"] == "menu"
    assert {"find_products", "find_services", "find_locations", "find_shops"} <= {
        choice["action"] for choice in payload["quick_replies"]
    }


@pytest.mark.parametrize("message,expected", [
    ("Je veux devenir vendeur", "vendeur"),
    ("Comment organiser une livraison", "livraison"),
])
def test_clear_vendor_and_delivery_requests_skip_gemini(assistant, message, expected):
    response = _message(assistant, message=message)
    assert expected in response["text"].casefold()


def test_catalog_actions_do_at_most_one_shared_catalog_search(assistant):
    from dealnova.app.assistant import engine

    actions = [dict(action="find_products"),
               dict(action="catalog_category", value=str(assistant.categories.home)),
               dict(action="catalog_query", value="Maison"),
               dict(action="catalog_budget", value="300"),
               dict(action="find_services"), dict(action="find_locations"),
               dict(action="find_shops")]
    with patch.object(engine, "build_public_catalog", wraps=engine.build_public_catalog) as build:
        for params in actions:
            previous_calls = build.call_count
            _message(assistant, **params)
            assert build.call_count - previous_calls <= 1, params


@pytest.mark.parametrize("query,expected,kind", [
    ("Je veux acheter un savon", "Savon Beauté", "products"),
    ("Je veux louer une maison", "Maison a louer", "locations"),
])
def test_simple_shopping_sentences_do_not_search_for_their_leading_verbs(assistant, query, expected, kind):
    response = _message(assistant, message=query)
    assert expected in _titles(response)
    assert _kind(assistant) == kind


@pytest.mark.parametrize("query", ["Je cherche la boutique de coiffure", "Je cherche une boutique de produits"])
def test_shop_activity_does_not_override_the_requested_entity(assistant, query):
    _message(assistant, message=query)
    assert _kind(assistant) == "shops"


def test_support_in_a_product_name_does_not_contact_an_adviser(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, message="support mural télévision")
    assert "handoff" not in response
    assert _kind(assistant) == "products"


def test_stock_and_reserved_status_are_not_presented_as_available(assistant):
    products = _message(assistant, action="find_products")
    soldout = next(item for item in products["items"] if item["title"] == "Article en rupture")
    assert "indisponible" in soldout["meta"].casefold()
    rentals = _message(assistant, action="find_locations")
    reserved = next(item for item in rentals["items"] if item["title"] == "Maison reservee")
    assert "réservée" in reserved["meta"].casefold()
