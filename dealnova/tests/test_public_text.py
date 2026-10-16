import pytest

from dealnova.app.services.public_text import clean_shop_description


@pytest.mark.parametrize("value", [
    "CSS",
    "  cSs  ",
    "xccccccccccccccc",
    " XCCCCCCCCCCCCCCC ",
    "SSSSSSSSSSSSS",
    "ssssssssssssss",
])
def test_reviewed_placeholder_descriptions_are_hidden(value):
    assert clean_shop_description(value) == ""


@pytest.mark.parametrize("value", [
    "Boutique officielle de vendeur@example.com",
    "  boutique officielle de Vendeur+local@shop.example.ma  ",
])
def test_exact_legacy_email_placeholder_is_hidden(value):
    assert clean_shop_description(value) == ""


@pytest.mark.parametrize("value", [
    "Produits frais et épices. Commandes par téléphone.",
    "  Tresses, nattes et soins capillaires.\nSur rendez-vous.  ",
    "CSS et création de sites pour les commerçants.",
    "SSSS",
    "Boutique officielle de vendeur@example.com : épices et céréales.",
    "Boutique officielle de notre coopérative.",
    "vendeur@example.com",
    "",
    "  ",
])
def test_merchant_descriptions_are_preserved_verbatim(value):
    assert clean_shop_description(value) == value


def test_missing_description_is_empty():
    assert clean_shop_description(None) == ""
