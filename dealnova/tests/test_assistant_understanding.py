"""The request parser is testable without an app, database or AI key."""
import importlib.util
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    "assistant_understanding_pure", Path(__file__).parents[1] / "app/assistant/understanding.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
parse_public_request = _module.parse_public_request


@pytest.mark.parametrize("message,expected", [
    ("je cherche un studio à Rabat à moins de 3000 dh", {"kind": "locations", "property_type": "studio", "city": "Rabat", "max_price": 3000, "query": ""}),
    ("un coifeur pas cher", {"kind": "services", "sort": "low", "query": "coiffure"}),
    ("quelqu'un pour réparer mon ordinateur", {"kind": "services", "query": "réparation ordinateur", "needs_ai": True}),
    ("Je cherche un téléphone à Salé pour 300 dh", {"city": "Salé", "query": "téléphone", "max_price": 300}),
    ("Un appartement par mois à Témara pour 3 000 DH", {"kind": "locations", "property_type": "apartment", "listing_type": "monthly", "city": "Témara", "max_price": 3000}),
    ("je veux plutôt un appartement", {"kind": "locations", "explicit_kind": True, "query": ""}),
    ("produits en promotion", {"kind": "products", "promo": True, "query": ""}),
    ("promotions", {"kind": "promotions", "promo": True}),
    ("support téléphone", {"query": "support téléphone"}),
    ("un plonbier à Kénitra", {"kind": "services", "city": "Kénitra", "query": "plomberie"}),
    ("pâtisserie sénégalaise", {"query": "pâtisserie sénégalaise"}),
    ("poisson salé", {"query": "poisson salé"}),
    ("produits pour la chambre", {"kind": "products", "query": "chambre"}),
    ("produits pour le studio", {"kind": "products", "query": "studio"}),
])
def test_extracts_simple_public_requests(message, expected):
    result = parse_public_request(message)
    for key, value in expected.items():
        assert result.get(key) == value, (key, result)


@pytest.mark.parametrize("message,expected", [
    ("juste à Salé", {"city": "Salé", "refinement": True}),
    ("moins cher", {"sort": "low", "refinement": True}),
    ("et pour 300dh", {"max_price": 300, "refinement": True}),
    ("max300dh", {"max_price": 300, "refinement": True}),
    ("sans limite", {"min_price": None, "max_price": None, "refinement": True}),
    ("300", {"max_price": 300, "refinement": True}),
    ("entre 100 et 500 DH", {"min_price": 100, "max_price": 500, "refinement": True}),
    ("en stock", {"stock": True, "refinement": True}),
])
def test_filters_do_not_replace_existing_keywords(message, expected):
    context = {"kind": "products", "query": "téléphone", "budget": 900}
    result = parse_public_request(message, context=context)
    assert result == expected
    assert context == {"kind": "products", "query": "téléphone", "budget": 900}


def test_home_category_does_not_become_a_rental_request():
    assert parse_public_request("maison", context={"kind": "products"}) == {"query": "maison"}
    assert parse_public_request("produits pour la maison")["kind"] == "products"
    assert parse_public_request("maison à louer")["kind"] == "locations"


@pytest.mark.parametrize("message,action", [
    ("contacter un conseiller", "handoff"),
    ("j'ai besoin d'aide", "handoff"),
    ("envoyer un colis", "help_delivery"),
    ("organiser une livraison", "help_delivery"),
    ("comment fonctionne la livraison ?", "help_delivery"),
    ("devenir vendeur", "become_vendor"),
    ("créer ma boutique", "become_vendor"),
    ("comment commander ?", "faq_order"),
    ("où est ma commande ?", "faq_order"),
    ("comment payer ?", "faq_payment"),
    ("faut-il créer un compte pour acheter ?", "faq_guest"),
    ("comment vider mon panier ?", "faq_cart"),
    ("comment réserver un service ?", "faq_booking"),
    ("comment louer un studio ?", "faq_rental"),
    ("menu principal", "start"),
])
def test_action_requests_do_not_search_products(message, action):
    assert parse_public_request(message) == {"action": action}


@pytest.mark.parametrize("message", ["", "   ", None])
def test_empty_request_has_no_guessed_fields(message):
    assert parse_public_request(message) == {}


@pytest.mark.parametrize("message", ["max -300 dh", "max 1000000001 dh", "max 999999999999999999 dh"])
def test_invalid_prices_are_not_applied(message):
    assert "max_price" not in parse_public_request(message)


def test_input_is_bounded_and_ordinary_numbers_stay_search_terms():
    result = parse_public_request("bonjour je cherche un iphone 15")
    assert "max_price" not in result
    assert result["query"] == "iphone 15"
    assert len(parse_public_request("abcdef " * 1000)["query"]) <= 160


def test_short_term_rentals_and_decimal_budget():
    result = parse_public_request("un studio par jour pour 250,50 dh")
    assert result["listing_type"] == "daily"
    assert result["max_price"] == 250.5


def test_only_high_confidence_spelling_changes_are_made():
    result = parse_public_request("Tchiep poisson braisé")
    assert result == {"query": "tchiep poisson braisé"}


def test_rental_store_type_does_not_become_a_shop_search():
    result = parse_public_request("je cherche un local commercial à louer à Rabat")
    assert result["kind"] == "locations"
    assert result["property_type"] == "store"
    assert result["query"] == ""


def test_explicit_negative_promotion_request():
    assert parse_public_request("pas en promotion", context={"kind": "products"}) == {
        "promo": False, "refinement": True}


@pytest.mark.parametrize("message", ["je cherche la boutique de coiffure", "un magasin de plomberie"])
def test_requested_shop_wins_over_its_service_speciality(message):
    assert parse_public_request(message)["kind"] == "shops"


def test_promotions_request_opens_universe_without_existing_catalogue():
    result = parse_public_request("je veux voir les promotions")
    assert result == {"kind": "promotions", "explicit_kind": True, "promo": True, "query": ""}


@pytest.mark.parametrize("message", ["en promotion", "promotions", "je veux voir les promotions"])
def test_promotions_refine_an_existing_product_search(message):
    assert parse_public_request(message, context={"kind": "products", "query": "téléphone"}) == {
        "promo": True, "refinement": True}


@pytest.mark.parametrize("message,kind", [
    ("je cherche des produits en promotion", "products"),
    ("je veux un service en promotion", "services"),
    ("je veux une location en promotion", "locations"),
])
def test_explicit_entity_request_has_priority_over_promotions(message, kind):
    assert parse_public_request(message)["kind"] == kind


@pytest.mark.parametrize("message,kind", [
    ("je cherche une boutique de produits", "shops"),
    ("une boutique de services", "shops"),
    ("les produits de la boutique", "products"),
    ("les produits du restaurant", "products"),
    ("un magasin à louer", "locations"),
])
def test_entity_requested_before_its_speciality_controls_kind(message, kind):
    assert parse_public_request(message)["kind"] == kind


def test_transition_words_do_not_become_search_filters():
    assert parse_public_request("finalement je cherche une location", context={"kind": "products"}) == {
        "kind": "locations", "explicit_kind": True, "query": ""}


def test_vague_low_price_request_asks_for_clarification_instead_of_searching_filler_words():
    result = parse_public_request(
        "je veux un truc simple avec un prix pas trop elever",
        context={"kind": "products", "query": "téléphone"},
    )
    assert result["conversation"] == "clarify"
    assert result["sort"] == "low"
    assert result["needs_ai"] is True
    assert not result.get("query")


def test_browse_and_conversation_repair_are_not_catalogue_keywords():
    assert parse_public_request("il y a quoi de disponible", context={"kind": "products"}) == {
        "conversation": "browse", "query": "", "stock": True}
    assert parse_public_request("mais répond correctement", context={"kind": "products"}) == {
        "conversation": "repair", "needs_ai": True}
