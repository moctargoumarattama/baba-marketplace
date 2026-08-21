from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.routes import cart as cart_routes


def _shop(shop_id, name, phone=""):
    return SimpleNamespace(id=shop_id, name=name, contact_phone=phone)


def _product(product_id, name, shop):
    return SimpleNamespace(id=product_id, name=name, shop=shop)


def _item(product, quantity, unit_price_cents):
    return {
        "product": product,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "line_total_cents": quantity * unit_price_cents,
    }


def test_group_cart_items_by_shop_keeps_each_shop_separate():
    shop_a = _shop(1, "Boutique A", "0612345678")
    shop_b = _shop(2, "Boutique B", "0712345678")
    shop_c = _shop(3, "Boutique C", "")
    items = [
        _item(_product(10, "Produit A1", shop_a), 2, 5000),
        _item(_product(20, "Produit B1", shop_b), 1, 12000),
        _item(_product(11, "Produit A2", shop_a), 3, 3000),
        _item(_product(30, "Produit C1", shop_c), 1, 2500),
    ]

    groups = cart_routes.group_cart_items_by_shop(items)

    assert [group["shop"].name for group in groups] == ["Boutique A", "Boutique B", "Boutique C"]
    by_shop = {group["shop"].id: group for group in groups}
    assert by_shop[1]["subtotal_cents"] == 19000
    assert by_shop[2]["subtotal_cents"] == 12000
    assert by_shop[3]["subtotal_cents"] == 2500
    assert [item["product"].name for item in by_shop[1]["items"]] == ["Produit A1", "Produit A2"]


def test_generate_shop_whatsapp_message_contains_only_that_shop_items():
    shop_a = _shop(1, "Boutique A", "0612345678")
    product_a = _product(10, "Produit A1", shop_a)
    product_b = _product(20, "Produit B1", _shop(2, "Boutique B", "0712345678"))
    client = {
        "name": "Nadia",
        "phone": "+212612345678",
        "address": "Agdal, Rabat",
    }

    message = cart_routes.generate_shop_whatsapp_message(
        shop_a,
        [_item(product_a, 2, 5000)],
        client,
    )

    assert "Boutique : Boutique A" in message
    assert "Produit A1 x2 - 100.00 MAD" in message
    assert product_b.name not in message
    assert "Total estimé : 100.00 MAD" in message
    assert "Client : Nadia" in message
    assert "Téléphone : +212612345678" in message
    assert "Adresse : Agdal, Rabat" in message


def test_generate_shop_whatsapp_message_omits_client_form_details():
    shop = _shop(1, "Boutique A", "0612345678")
    product = _product(10, "Produit A1", shop)

    message = cart_routes.generate_shop_whatsapp_message(
        shop,
        [_item(product, 2, 5000)],
        {},
    )

    assert "Produit A1 x2 - 100.00 MAD" in message
    assert "Client :" not in message
    assert "Telephone :" not in message
    assert "Téléphone :" not in message
    assert "Adresse :" not in message


def test_build_whatsapp_link_uses_shop_phone_and_url_encodes_message():
    message = "Bonjour, je souhaite commander Produit A."

    link = cart_routes.build_whatsapp_link("06 12-34 56 78", message)

    parsed = urlparse(link)
    assert parsed.scheme == "https"
    assert parsed.netloc == "wa.me"
    assert parsed.path == "/212612345678"
    assert unquote(parse_qs(parsed.query)["text"][0]) == message
    assert "212602908954" not in link


def test_prepare_vendor_whatsapp_checkout_disables_shop_without_phone():
    shop_with_phone = _shop(1, "Boutique A", "0612345678")
    shop_without_phone = _shop(2, "Boutique B", "")
    items = [
        _item(_product(10, "Produit A1", shop_with_phone), 1, 5000),
        _item(_product(20, "Produit B1", shop_without_phone), 1, 7000),
    ]
    client = {
        "name": "Nadia",
        "phone": "+212612345678",
        "address": "Agdal, Rabat",
    }

    checkout = cart_routes.prepare_vendor_whatsapp_checkout(items, client)

    assert checkout["total_cents"] == 12000
    by_shop = {group["shop"].id: group for group in checkout["shop_groups"]}
    assert by_shop[1]["phone_available"] is True
    assert by_shop[1]["whatsapp_url"].startswith("https://wa.me/212612345678?")
    assert by_shop[2]["phone_available"] is False
    assert by_shop[2]["whatsapp_url"] == ""


def test_prepare_vendor_whatsapp_checkout_snapshots_shop_identity_for_notifications():
    shop = _shop(1, "Boutique A", "0612345678")
    shop.vendor_id = 42
    items = [_item(_product(10, "Produit A1", shop), 1, 5000)]

    checkout = cart_routes.prepare_vendor_whatsapp_checkout(items, {})

    group = checkout["shop_groups"][0]
    assert group["shop_id"] == 1
    assert group["vendor_id"] == 42


def test_cart_data_cache_skips_lru_when_loading_relationships(monkeypatch):
    calls = []

    def fake_product_map(cart_dict, include_shop=False, include_category=False):
        calls.append((include_shop, include_category))
        return {1: SimpleNamespace(id=1)}

    monkeypatch.setattr(cart_routes, "_cart_product_map", fake_product_map)
    monkeypatch.setattr(cart_routes, "_active_promo_map", lambda product_ids: {})
    cart_routes._cart_cache.cache.clear()
    cart_routes._cart_cache.timestamps.clear()

    cart_routes._get_cached_cart_data({"1": 1}, include_shop=True)
    cart_routes._get_cached_cart_data({"1": 1}, include_shop=True)

    assert calls == [(True, False), (True, False)]


def test_checkout_source_has_no_client_form_gate():
    source = (ROOT / "app/routes/cart.py").read_text(encoding="utf-8-sig")
    start = source.index("def whatsapp_checkout(")
    next_route = source.find("\n@bp.route", start + 1)
    body = source[start: next_route if next_route != -1 else len(source)]

    assert not (ROOT / "app/templates/cart/checkout.html").exists()
    assert not (ROOT / "app/static/js/pages/checkout_page.js").exists()
    assert not (ROOT / "app/static/css/cart-checkout.css").exists()
    assert '"cart/checkout.html"' not in source
    assert 'request.form.get("full_name")' not in body
    assert 'request.form.get("phone")' not in body
    assert 'request.form.get("address")' not in body
    assert "location_link" not in body
    assert "Veuillez renseigner votre nom" not in body
    assert "Numero de telephone invalide" not in body


def test_cart_page_uses_direct_whatsapp_purchase_language():
    template = (ROOT / "app/templates/cart/cart.html").read_text(encoding="utf-8-sig")

    assert "Achat direct avec la boutique" in template
    assert "Vous allez discuter directement avec la boutique pour finaliser votre achat." in template
    assert "Commander sur WhatsApp" in template
    assert "Continuer mes achats" in template
    assert "commerçant" not in template
    assert "Commerçants" not in template
    assert "Boutiques" in template
    assert "vendeur" not in template.lower()
    assert "Mise en relation" not in template
    assert "Contacter les boutiques" not in template


def test_cart_page_avoids_duplicate_product_and_summary_prices():
    template = (ROOT / "app/templates/cart/cart.html").read_text(encoding="utf-8-sig")

    assert "product-subtotal" in template
    assert "product-price" not in template
    assert "prix_final(product)" not in template
    assert 'id="totalAmount"' in template
    assert 'id="subtotalAmount"' not in template
    assert ">Sous-total<" not in template
    assert template.count("Total produits estimé") == 1
    assert "Le paiement et la livraison se font directement avec la boutique." not in template


def test_cart_page_uses_compact_adaptive_item_layout():
    template = (ROOT / "app/templates/cart/cart.html").read_text(encoding="utf-8-sig")

    assert "cart-item-layout" in template
    assert "cart-item-media" in template
    assert "cart-item-info" in template
    assert "cart-item-actions" in template
    assert "cart-item-total" in template
    assert "grid-template-columns: 56px minmax(0, 1fr) auto;" in template
    assert "line-clamp" in template


def test_vendor_whatsapp_page_is_mobile_first_order_summary():
    template = (ROOT / "app/templates/cart/vendor_whatsapp_checkout.html").read_text(encoding="utf-8-sig")

    assert "Finalisez votre commande" in template
    assert "Suivez les étapes et ouvrez WhatsApp pour chaque boutique." in template
    assert "Produits :" in template
    assert "Total estimé" in template
    assert "Ouvrir WhatsApp" in template
    assert "contacter ce vendeur" in template
    assert "Étape" in template
    assert "Le paiement et la livraison se font directement avec la boutique." in template
    assert "Retour au panier" in template
    assert "Continuer mes achats" in template
    assert "<table" not in template
    assert "demande WhatsApp" not in template
    assert "commerçant" not in template
    assert "mise en relation" not in template.lower()


def test_vendor_whatsapp_page_tracks_each_shop_click_client_side():
    template = (ROOT / "app/templates/cart/vendor_whatsapp_checkout.html").read_text(encoding="utf-8-sig")

    assert "boutiques contactées" in template
    assert 'id="whatsappContactedCount"' in template
    assert 'id="whatsappTotalCount"' in template
    assert 'data-whatsapp-contact' in template
    assert 'data-contact-card' in template
    assert 'data-sent-label' in template
    assert "Message envoyé" in template
    assert "Envoyé" in template
    assert "event.preventDefault()" in template
    assert "aria-disabled" in template
    assert "merchant-card--sent" in template
