"""Real public-inventory journeys; SQLite, uploads and AI replies are isolated."""

from datetime import datetime, timedelta
import json
from types import SimpleNamespace
import unicodedata
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


def _fold(value):
    return "".join(char for char in unicodedata.normalize("NFKD", str(value).casefold())
                   if not unicodedata.combining(char))


@pytest.fixture(scope="module")
def natural_catalog(tmp_path_factory):
    with isolated_vendor_application(tmp_path_factory.mktemp("assistant-natural")) as fixture:
        from dealnova.app.models.category import Category
        from dealnova.app.models.product import Product
        from dealnova.app.models.promo import Promo
        from dealnova.app.models.rental import RentalListing
        from dealnova.app.models.shop import Shop
        from dealnova.app.models.user import User

        fixture.app.config.update(GEMINI_API_KEY="", ANALYTICS_ENABLED=False,
                                  PUBLIC_BASE_URL="http://localhost")
        with fixture.app.app_context():
            shop = fixture.db.session.get(Shop, fixture.ids.shop)
            shop.name = "Les bonnes adresses"
            shop.address = "Rabat, Maroc"
            shop.set_allowed_types(["products", "services", "location"])
            categories = {
                "beauty": Category(name="Beauté", slug="natural-beauty", category_type="products"),
                "home": Category(name="Maison", slug="natural-home", category_type="products"),
                "hair": Category(name="Coiffure", slug="natural-hair", category_type="services"),
                "it": Category(name="Informatique", slug="natural-it", category_type="services"),
            }
            fixture.db.session.add_all(categories.values())
            hidden_vendor = User(username="natural-hidden", email="natural-hidden@example.test",
                                 role="vendor", is_active=True, password_hash="unused-fixture-password")
            fixture.db.session.add(hidden_vendor)
            fixture.db.session.flush()
            hidden_shop = Shop(name="Invisible", slug="natural-hidden", vendor_id=hidden_vendor.id,
                               is_active=False, address="Rabat", primary_type="products")
            fixture.db.session.add(hidden_shop)
            fixture.db.session.flush()

            def product(name, category, **changes):
                values = dict(name=name, description=name, kind="physical", price=100, stock=4,
                              category_id=categories[category].id, vendor_id=fixture.ids.vendor,
                              shop_id=shop.id, is_active=True)
                values.update(changes)
                return Product(**values)

            records = {
                "soap": product("Savon naturel très doux", "beauty", price=25),
                "soap_luxury": product("Savon doux prestige", "beauty", price=90),
                "lamp": product("Lampe pour la maison", "home", price=80),
                "computer": product("Ordinateur portable neuf", "home", price=2000),
                "hair_cheap": product("Coupe express", "hair", kind="service", stock=0, price=40),
                "hair_premium": product("Tresses longues", "hair", kind="service", stock=0, price=220),
                "repair": product("Dépannage ordinateur", "it", kind="service", stock=0, price=150),
                "promo": product("Table basse", "home", price=200),
                "expired_promo": product("Tapis anciennement soldé", "home", price=200),
                "pending_promo": product("Chaise promotion à valider", "home", price=200),
                "inactive": product("Savon doux retiré", "beauty", price=10, is_active=False),
                "hidden": product("Savon doux invisible", "beauty", price=5,
                                  shop_id=hidden_shop.id, vendor_id=hidden_vendor.id),
                "soldout": product("Savon doux en rupture", "beauty", price=15, stock=0),
            }
            fixture.db.session.add_all(records.values())
            fixture.db.session.flush()
            for name, status, days in (("promo", Promo.STATUS_APPROVED, 5),
                                       ("expired_promo", Promo.STATUS_APPROVED, -1),
                                       ("pending_promo", Promo.STATUS_PENDING, 5)):
                fixture.db.session.add(Promo(product_id=records[name].id, type="percentage", value=50,
                                             status=status, end_date=datetime.utcnow() + timedelta(days=days)))

            def rental(title, slug, **changes):
                values = dict(title=title, slug=slug, description="Logement disponible",
                              owner_id=fixture.ids.vendor, shop_id=shop.id, city="Rabat",
                              property_type="studio", listing_type="monthly", rent_cents=220000,
                              status="active", is_active=True,
                              expires_at=datetime.utcnow() + timedelta(days=7))
                values.update(changes)
                return RentalListing(**values)

            listings = {
                "studio_low": rental("Studio calme", "natural-studio-low"),
                "studio_mid": rental("Studio lumineux", "natural-studio-mid", rent_cents=280000),
                "studio_high": rental("Studio premium", "natural-studio-high", rent_cents=350000),
                "studio_other_city": rental("Studio proche gare", "natural-studio-sale", city="Salé", rent_cents=200000),
                "apartment": rental("Appartement familial", "natural-apartment", property_type="apartment", rent_cents=230000),
                "expired": rental("Studio expiré", "natural-studio-expired", rent_cents=100000,
                                  expires_at=datetime.utcnow() - timedelta(days=1)),
                "hidden": rental("Studio invisible", "natural-studio-hidden", rent_cents=100000,
                                 shop_id=hidden_shop.id, owner_id=hidden_vendor.id),
                "inactive": rental("Studio retiré", "natural-studio-inactive", rent_cents=100000, is_active=False),
            }
            fixture.db.session.add_all(listings.values())
            fixture.db.session.commit()
            fixture.records = SimpleNamespace(**{name: item.id for name, item in records.items()})
        yield fixture


@pytest.fixture()
def assistant(natural_catalog):
    fixture = SimpleNamespace(**vars(natural_catalog))
    fixture.client = fixture.app.test_client()
    # Missing keys and accidental remote calls cannot expose a developer key/network.
    with patch("requests.Session.post", side_effect=RuntimeError("No real network in assistant journeys")):
        yield fixture


def _message(fixture, **params):
    response = fixture.client.get("/api/assistant/message", query_string=params)
    assert response.status_code == 200
    assert response.json["ok"] is True
    result = response.json["response"]
    assert result.get("text")
    return result


def _titles(response):
    return {item["title"] for item in response.get("items", [])}


def _urls(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"url", "redirect_url", "href"} and isinstance(item, str):
                yield item
            else:
                yield from _urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from _urls(item)


def _params(response):
    return parse_qs(urlsplit(response["more"]["url"]).query)


def test_one_sentence_applies_city_property_and_budget_to_real_public_rentals(assistant):
    response = _message(assistant, message="un studio à Rabat moins de 3000 dh")
    assert _titles(response) == {"Studio calme", "Studio lumineux"}
    params = _params(response)
    assert params.get("city") == ["Rabat"]
    assert params.get("property_type") == ["studio"]
    assert float(params["max_price"][0]) == 3000


def test_followup_budget_preserves_previous_city_and_property_type(assistant):
    _message(assistant, message="un studio à Rabat moins de 3000 dh")
    response = _message(assistant, message="et moins de 2500")
    assert _titles(response) == {"Studio calme"}
    params = _params(response)
    assert params.get("city") == ["Rabat"]
    assert params.get("property_type") == ["studio"]
    assert float(params["max_price"][0]) == 2500


def test_typo_coifeur_matches_real_coiffure_category_and_cheapest_first(assistant):
    response = _message(assistant, message="coifeur pas cher")
    assert [item["title"] for item in response.get("items", [])] == ["Coupe express", "Tresses longues"]
    assert urlsplit(response["more"]["url"]).path == "/services"


def test_repair_request_returns_professional_service_instead_of_computer_for_sale(assistant):
    response = _message(assistant, message="quelqu un pour réparer mon ordinateur")
    assert _titles(response) == {"Dépannage ordinateur"}
    assert "Ordinateur portable neuf" not in _titles(response)
    assert urlsplit(response["more"]["url"]).path == "/services"


def test_separated_words_match_one_product_without_exact_phrase_requirement(assistant):
    response = _message(assistant, message="savon doux")
    assert "Savon naturel très doux" in _titles(response)
    assert not {"Savon doux retiré", "Savon doux invisible"} & _titles(response)


def test_promotion_request_only_returns_active_approved_real_discounts(assistant):
    response = _message(assistant, message="je veux voir les promotions")
    assert _titles(response) == {"Table basse"}
    assert urlsplit(response["more"]["url"]).path == "/promotions"
    assert "100" in str(response["items"][0])


@pytest.mark.parametrize("question,keywords,path", [
    ("est ce que je dois créer un compte pour acheter ?", ("invite", "sans compte"), None),
    ("comment passer une commande ?", ("panier", "commande"), "/cart"),
    ("comment je peux payer ?", ("paiement", "payer", "reglement"), None),
    ("où est mon panier ?", ("panier",), "/cart"),
    ("comment réserver un service ?", ("service", "rendez-vous", "reservation"), "/services"),
    ("comment contacter le propriétaire pour louer ?", ("proprietaire", "location"), "/locations"),
])
def test_basic_public_help_is_actionable_and_never_demands_a_client_account(assistant, question, keywords, path):
    response = _message(assistant, message=question)
    text = _fold(response["text"])
    assert any(word in text for word in keywords)
    assert "connectez-vous" not in text and "creez votre compte" not in text
    urls = list(_urls(response))
    assert not any("/login" in url or "/vendor-access" in url for url in urls)
    if path:
        assert any(urlsplit(url).path.rstrip("/") == path for url in urls)


def test_customer_can_explicitly_switch_universe_mid_conversation(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, message="finalement je cherche une location")
    assert response.get("items")
    assert urlsplit(response["more"]["url"]).path == "/locations"
    assert all("/location/" in item["url"] for item in response["items"])


def test_maison_without_rental_intent_remains_a_product_category(assistant):
    _message(assistant, action="find_products")
    response = _message(assistant, message="maison")
    assert "Lampe pour la maison" in _titles(response)
    assert urlsplit(response["more"]["url"]).path == "/produits"
    assert all("/shop/product/" in item["url"] for item in response.get("items", []))


def test_reserving_the_first_service_opens_real_booking_form_without_creating_a_booking(assistant):
    from dealnova.app.models.booking import Booking

    initial = _message(assistant, action="find_services")
    first = initial["items"][0]
    product_id = int(urlsplit(first["url"]).path.rsplit("/", 1)[-1])
    with assistant.app.app_context():
        bookings_before = Booking.query.count()
    response = _message(assistant, message="je veux réserver le premier")
    assert _titles(response) == {first["title"]}
    assert urlsplit(response["more"]["url"]).path == f"/booking/{product_id}"
    with assistant.app.app_context():
        assert Booking.query.count() == bookings_before


def test_contacting_owner_of_first_result_links_real_inquiry_without_claiming_reservation(assistant):
    initial = _message(assistant, message="un studio à Rabat moins de 3000 dh")
    first = initial["items"][0]
    listing_path = urlsplit(first["url"]).path
    response = _message(assistant, message="contacter le propriétaire du premier")
    assert _titles(response) == {first["title"]}
    assert urlsplit(response["more"]["url"]).path == listing_path + "/inquiry"
    assert not any(phrase in _fold(response["text"]) for phrase in (
        "reservation confirmee", "location confirmee", "vous avez reserve",
    ))


def test_seeing_first_result_displays_exactly_the_previous_first_offer(assistant):
    initial = _message(assistant, action="find_products")
    first = initial["items"][0]
    response = _message(assistant, message="voir le premier")
    assert len(response.get("items", [])) == 1
    assert response["items"][0]["title"] == first["title"]
    assert response["items"][0]["url"] == first["url"]


def test_public_help_does_not_erase_customer_search_before_next_refinement(assistant):
    _message(assistant, message="un studio à Rabat moins de 3000 dh")
    help_response = _message(assistant, message="comment passer une commande ?")
    assert "commande" in _fold(help_response["text"])
    response = _message(assistant, message="et moins de 2500")
    assert _titles(response) == {"Studio calme"}
    params = _params(response)
    assert params.get("city") == ["Rabat"]
    assert params.get("property_type") == ["studio"]
    assert float(params["max_price"][0]) == 2500


def test_result_reference_rechecks_visibility_after_offer_is_withdrawn(assistant):
    from dealnova.app.models.product import Product

    initial = _message(assistant, action="find_services")
    first = initial["items"][0]
    product_id = int(urlsplit(first["url"]).path.rsplit("/", 1)[-1])
    with assistant.app.app_context():
        product = assistant.db.session.get(Product, product_id)
        product.is_active = False
        assistant.db.session.commit()
    try:
        response = _message(assistant, message="je veux réserver le premier")
        assert first["title"] not in _titles(response)
        assert first["url"] not in set(_urls(response))
        assert not any(urlsplit(url).path == f"/booking/{product_id}" for url in _urls(response))
        assert "disponible" in _fold(response["text"])
    finally:
        with assistant.app.app_context():
            product = assistant.db.session.get(Product, product_id)
            product.is_active = True
            assistant.db.session.commit()


def test_budget_button_below_previous_price_range_does_not_leave_impossible_filters(assistant):
    initial = _message(assistant, message="produits entre 100 et 500 dh")
    assert initial.get("items")
    assert float(_params(initial)["min_price"][0]) == 100
    _message(assistant, action="catalog_filter_budget")
    response = _message(assistant, action="catalog_budget", value="50")
    assert "Savon naturel très doux" in _titles(response)
    params = _params(response)
    assert float(params["max_price"][0]) == 50
    assert not params.get("min_price") or float(params["min_price"][0]) <= 50


def _gemini_response(payload):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}
    return response


def _ai_reply(fixture, payload, state=None, message="Trouvez-moi un savon qui conviendrait à ma recherche"):
    from dealnova.app.assistant.engine import _reply_with_gemini

    state = state if state is not None else {"flow": None, "context": {}}
    with patch.dict(fixture.app.config, {"GEMINI_API_KEY": "fake-test-key", "GEMINI_MODEL": "gemini-test"}):
        with fixture.app.test_request_context():
            with patch("requests.Session.post", return_value=_gemini_response(payload)) as post:
                response = _reply_with_gemini(message, state)
    return response, post


def test_ai_interpretation_uses_actual_catalog_visibility_prices_and_trusted_urls(assistant):
    payload = {"text": "Résultats proposés", "search_query": "savon", "kind": "products",
               "is_off_topic": False, "action": None, "city": "Rabat", "max_price": 30,
               "sort": "low", "property_type": None,
               "items": [{"title": "Produit inventé", "url": "https://attacker.invalid/offer"}],
               "redirect_url": "https://attacker.invalid/checkout"}
    response, post = _ai_reply(assistant, payload)
    assert post.call_count == 1
    assert response and "Savon naturel très doux" in _titles(response)
    assert not {"Savon doux prestige", "Savon doux retiré", "Savon doux invisible", "Produit inventé"} & _titles(response)
    assert not any("attacker.invalid" in url for url in _urls(response))
    assert float(_params(response)["max_price"][0]) == 30
    assert all("/shop/product/" in item["url"] for item in response["items"])


def test_ai_receives_search_context_and_preserves_unmentioned_filters(assistant):
    state = {"flow": "catalog", "step": "search", "context": {
        "kind": "locations", "query": "", "city": "Rabat", "property_type": "studio", "budget": 3000,
    }}
    payload = {"text": "Voici les logements", "search_query": "", "kind": "locations",
               "is_off_topic": False, "action": None, "max_price": 2500}
    response, post = _ai_reply(assistant, payload, state=state, message="Le même type de logement mais un peu moins cher")
    request_payload = post.call_args.kwargs["json"]
    prompt = json.dumps(request_payload, ensure_ascii=False)
    assert "Rabat" in prompt and "studio" in prompt and "3000" in prompt
    assert response and _titles(response) == {"Studio calme"}
    assert _params(response).get("city") == ["Rabat"]
    assert _params(response).get("property_type") == ["studio"]


@pytest.mark.parametrize("invalid", [
    {"max_price": "NaN", "sort": "drop table product", "property_type": "palace"},
    {"search_query": {"sql": "secret"}, "city": {"nested": "Rabat"}},
    {"kind": "admin", "action": "https://attacker.invalid/action", "max_price": -100},
])
def test_invalid_ai_fields_do_not_broaden_saved_filters_or_create_actions(assistant, invalid):
    state = {"flow": "catalog", "step": "search", "context": {
        "kind": "products", "query": "savon", "city": "Rabat", "budget": 30,
    }}
    payload = {"text": "Résultats proposés", "search_query": "savon", "kind": "products",
               "is_off_topic": False, "action": None, **invalid}
    response, _ = _ai_reply(assistant, payload, state=state)
    assert state["context"].get("budget") == 30
    assert state["context"].get("city") == "Rabat"
    assert state["context"].get("kind") == "products"
    if response is not None:
        assert not {"Savon doux prestige", "Savon doux retiré", "Savon doux invisible"} & _titles(response)
        assert not any("attacker.invalid" in url for url in _urls(response))


def test_remote_ai_failure_still_allows_direct_public_catalog_search(assistant):
    with patch.dict(assistant.app.config, {"GEMINI_API_KEY": "fake-test-key"}):
        response = _message(assistant, message="savon doux")
    assert "Savon naturel très doux" in _titles(response)
    assert "Savon doux invisible" not in _titles(response)


def test_long_unsuccessful_search_gets_one_ai_interpretation_then_real_services(assistant):
    payload = {"text": "Je vous propose ces professionnels", "search_query": "coiffure", "kind": "services",
               "is_off_topic": False, "action": None}
    with patch.dict(assistant.app.config, {"GEMINI_API_KEY": "fake-test-key", "GEMINI_MODEL": "gemini-test"}):
        with patch("requests.Session.post", return_value=_gemini_response(payload)) as post:
            response = _message(assistant, message="je cherche une personne qui coupe les cheveux")
    assert post.call_count == 1
    assert _titles(response) == {"Coupe express", "Tresses longues"}
    assert urlsplit(response["more"]["url"]).path == "/services"


def test_successful_direct_search_never_waits_for_ai_even_when_configured(assistant):
    with patch.dict(assistant.app.config, {"GEMINI_API_KEY": "fake-test-key"}):
        with patch("requests.Session.post", side_effect=AssertionError("A direct hit needs no AI")) as post:
            response = _message(assistant, message="savon doux")
    assert post.call_count == 0
    assert "Savon naturel très doux" in _titles(response)


def test_long_search_with_offline_provider_returns_normally_after_at_most_one_attempt(assistant):
    import requests

    with patch.dict(assistant.app.config, {"GEMINI_API_KEY": "fake-test-key", "GEMINI_MODEL": "gemini-test"}):
        with patch("requests.Session.post", side_effect=requests.Timeout("simulated provider outage")) as post:
            response = _message(assistant, message="je cherche une personne qui coupe les cheveux")
    assert post.call_count <= 1
    assert response["text"]
    assert "simulated provider outage" not in response["text"]
    assert response.get("quick_replies")
