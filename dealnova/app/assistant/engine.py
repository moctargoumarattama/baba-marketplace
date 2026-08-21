from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from flask import current_app, session, url_for
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, load_only

from ..models.category import Category, normalize_category_type
from ..models.product import Product
from ..models.rental import RentalListing
from ..models.shop import Shop
from ..services.cache import get_categories
from ..services.marketplace_feed import search_public_locations, search_public_products
from ..services.pricing import cents_to_money, final_price_cents, get_active_promos_for_products
from ..services.support_whatsapp import build_support_whatsapp_url

ASSISTANT_SESSION_KEY = "assistant_state_v2"
DEFAULT_MAX_BUDGET_DH = 20000

CATALOG_KIND_PRODUCTS = "products"
CATALOG_KIND_SERVICES = "services"
CATALOG_KIND_LOCATIONS = "locations"
FLOW_CATALOG = "catalog"
FLOW_DELIVERY = "delivery"
FLOW_SHOPS = "shops"
STEP_DELIVERY_AWAIT_CITY = "await_city"
STEP_DELIVERY_AWAIT_HANDOFF_CONFIRMATION = "await_handoff_confirmation"
STEP_SHOPS_AWAIT_QUERY = "await_shop_query"

PRODUCT_SUGGESTIONS = ("beaute", "maison", "vetements", "cadeau")
SERVICE_SUGGESTIONS = ("beaute", "coiffure", "esthetique", "informatique", "menage", "reparation")
LOCATION_SUGGESTIONS = ("maison", "appartement", "chambre", "studio", "bureau", "magasin")
CITY_SUGGESTIONS = ("Rabat", "Sale", "Kenitra", "Temara")
SHOP_QUERY_STOPWORDS = {
    "la",
    "le",
    "les",
    "de",
    "des",
    "du",
    "un",
    "une",
    "trouver",
    "cherche",
    "chercher",
    "recherche",
    "rechercher",
    "boutique",
    "shop",
    "magasin",
    "vendeur",
}
LOCATION_CATEGORY_HINTS = (
    "location",
    "immobilier",
    "appartement",
    "chambre",
    "studio",
    "bureau",
    "maison",
    "villa",
    "vehicule",
    "rental",
    "locatif",
)

SEMANTIC_PROFILES: dict[str, dict[str, Any]] = {
    "maison": {
        "preferred_kind": CATALOG_KIND_LOCATIONS,
        "terms": (
            "maison",
            "appartement",
            "studio",
            "chambre",
            "villa",
            "bureau",
            "magasin",
            "immobilier",
            "location",
        ),
    },
    "beaute": {
        "preferred_kind": CATALOG_KIND_SERVICES,
        "terms": (
            "beaute",
            "coiffure",
            "coiffeur",
            "esthetique",
            "ongle",
            "manucure",
            "pedicure",
            "spa",
            "maquillage",
            "soin",
            "barber",
        ),
    },
    "informatique": {
        "preferred_kind": CATALOG_KIND_SERVICES,
        "terms": (
            "informatique",
            "ordinateur",
            "depannage",
            "maintenance",
            "site web",
            "application mobile",
            "design",
            "reseau",
        ),
    },
    "electricite": {
        "preferred_kind": CATALOG_KIND_SERVICES,
        "terms": (
            "electricite",
            "electrique",
            "electricien",
            "installation electrique",
            "depannage electrique",
            "cablage",
            "courant",
            "tableau electrique",
            "prise",
            "eclairage",
        ),
    },
    "cadeau": {
        "preferred_kind": CATALOG_KIND_PRODUCTS,
        "terms": (
            "cadeau",
            "coffret",
            "offre",
            "parfum",
            "accessoire",
            "decoration",
        ),
    },
}


def _category_alias_terms(category: Category) -> list[str]:
    aliases: list[str] = []
    raw_values = [getattr(category, "name", None), getattr(category, "slug", None)]
    for raw_value in raw_values:
        folded = _fold_text(raw_value)
        if not folded:
            continue
        if folded not in aliases:
            aliases.append(folded)
        for token in re.split(r"[^a-z0-9]+", folded):
            if len(token) < 3:
                continue
            if token not in aliases:
                aliases.append(token)
    return aliases


def _categories_for_kind(kind: str) -> list[Category]:
    try:
        categories = list(get_categories() or [])
    except Exception:
        categories = []
    if not categories:
        return []

    if kind == CATALOG_KIND_PRODUCTS:
        return [c for c in categories if normalize_category_type(getattr(c, "category_type", None)) == "products"]

    if kind == CATALOG_KIND_SERVICES:
        return [c for c in categories if normalize_category_type(getattr(c, "category_type", None)) == "services"]

    if kind == CATALOG_KIND_LOCATIONS:
        location_categories: list[Category] = []
        for category in categories:
            aliases = _category_alias_terms(category)
            if any(_contains_any(alias, LOCATION_CATEGORY_HINTS) for alias in aliases):
                location_categories.append(category)
        return location_categories

    return []


def _category_context_for_query(kind: str, query_text: str) -> dict[str, Any]:
    folded_query = _fold_text(query_text)
    context = {"ids": [], "labels": [], "terms": []}
    if not folded_query:
        return context

    for category in _categories_for_kind(kind):
        aliases = _category_alias_terms(category)
        if not aliases:
            continue
        if not any((alias in folded_query) or (folded_query in alias) for alias in aliases):
            continue

        category_id = int(getattr(category, "id", 0) or 0)
        if category_id > 0 and category_id not in context["ids"]:
            context["ids"].append(category_id)

        folded_name = _fold_text(getattr(category, "name", ""))
        if folded_name and folded_name not in context["labels"]:
            context["labels"].append(folded_name)

        for alias in aliases:
            if len(alias) < 3:
                continue
            if alias not in context["terms"]:
                context["terms"].append(alias)

    return context


def _default_state() -> dict[str, Any]:
    return {"flow": None, "step": None, "context": {}}


def _load_state() -> dict[str, Any]:
    raw = session.get(ASSISTANT_SESSION_KEY)
    if not isinstance(raw, dict):
        return _default_state()
    return {
        "flow": raw.get("flow"),
        "step": raw.get("step"),
        "context": dict(raw.get("context") or {}),
    }


def _save_state(state: dict[str, Any]) -> None:
    session[ASSISTANT_SESSION_KEY] = {
        "flow": state.get("flow"),
        "step": state.get("step"),
        "context": dict(state.get("context") or {}),
    }
    session.modified = True


def _reset_state() -> dict[str, Any]:
    state = _default_state()
    _save_state(state)
    return state


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _fold_text(value: str | None) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return folded


def _contains_any(text: str, words: tuple[str, ...] | list[str]) -> bool:
    folded_text = _fold_text(text)
    return any(_fold_text(word) in folded_text for word in words)


def _semantic_profile_for_query(query_text: str) -> dict[str, Any] | None:
    folded = _fold_text(query_text)
    if not folded:
        return None
    for key, profile in SEMANTIC_PROFILES.items():
        if key in folded:
            return profile
    return None


def _expand_query_terms(
    kind: str,
    query_text: str,
    *,
    category_terms: list[str] | None = None,
) -> list[str]:
    base = _normalize_text(query_text)
    folded = _fold_text(query_text)
    terms: list[str] = []
    if base:
        terms.append(base)
    if folded and folded != base:
        terms.append(folded)

    profile = _semantic_profile_for_query(query_text)
    if profile:
        for item in profile.get("terms", ()):
            normalized = _normalize_text(str(item or ""))
            if normalized and normalized not in terms:
                terms.append(normalized)

    # Dedicated enrichments for location inventory vocabulary.
    if kind == CATALOG_KIND_LOCATIONS and _contains_any(query_text, ("maison", "logement", "habiter")):
        for item in ("appartement", "chambre", "studio", "villa", "bureau", "magasin"):
            if item not in terms:
                terms.append(item)

    # Dedicated enrichments for beauty services.
    if kind == CATALOG_KIND_SERVICES and _contains_any(query_text, ("beaute", "soin")):
        for item in ("coiffure", "esthetique", "ongle", "spa", "manucure", "maquillage"):
            if item not in terms:
                terms.append(item)

    for item in category_terms or []:
        normalized = _normalize_text(item)
        if len(normalized) < 3:
            continue
        if normalized not in terms:
            terms.append(normalized)

    return terms


def _extract_first_number(text: str | None) -> int | None:
    match = re.search(r"(\d{2,6})", str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _main_quick_replies() -> list[dict[str, str]]:
    return [
        {"label": "Trouver un produit", "action": "find_products"},
        {"label": "Trouver un service", "action": "find_services"},
        {"label": "Trouver une location", "action": "find_locations"},
        {"label": "Trouver une boutique", "action": "find_shops"},
        {"label": "Devenir vendeur", "action": "become_vendor"},
        {"label": "Besoin livraison", "action": "help_delivery"},
        {"label": "Parler a un humain", "action": "handoff"},
    ]


def _category_quick_replies(kind: str) -> list[dict[str, str]]:
    mapping = {
        CATALOG_KIND_PRODUCTS: PRODUCT_SUGGESTIONS,
        CATALOG_KIND_SERVICES: SERVICE_SUGGESTIONS,
        CATALOG_KIND_LOCATIONS: LOCATION_SUGGESTIONS,
    }
    values = mapping.get(kind, PRODUCT_SUGGESTIONS)
    quick = [{"label": value.title(), "action": "catalog_query", "value": value} for value in values]
    quick.append({"label": "Sans filtre", "action": "catalog_query", "value": "__any__"})
    return quick


def _budget_quick_replies(kind: str) -> list[dict[str, str]]:
    if kind == CATALOG_KIND_LOCATIONS:
        budgets = (1500, 3000, 5000, 10000, None)
    else:
        budgets = (100, 300, 500, 1000, None)
    replies: list[dict[str, str]] = []
    for budget in budgets:
        if budget is None:
            replies.append({"label": "Sans limite", "action": "catalog_budget", "value": "none"})
        else:
            replies.append(
                {"label": f"{int(budget)} DH", "action": "catalog_budget", "value": str(int(budget))}
            )
    return replies


def _city_quick_replies() -> list[dict[str, str]]:
    return [{"label": city, "action": "delivery_city", "value": city} for city in CITY_SUGGESTIONS]


def _handoff_payload() -> dict[str, Any]:
    lines = [
        "Bonjour, je souhaite parler a un conseiller Baba Market.",
        "Pouvez-vous m'aider s'il vous plait ?",
    ]
    return {"label": "Contacter un humain sur WhatsApp", "url": build_support_whatsapp_url(lines)}


def _delivery_handoff_payload() -> dict[str, Any]:
    return {
        "label": "Contacter livraison sur WhatsApp",
        "url": url_for("shop.delivery_whatsapp_loader", back=url_for("shop.home")),
    }


def _menu_response() -> dict[str, Any]:
    return {
        "text": (
            "Bonjour ! Assistant Baba Market a votre service.\n"
            "Je peux vous aider pour Produits, Services, Locations, Boutiques et Livraison."
        ),
        "quick_replies": _main_quick_replies(),
    }


def assistant_bootstrap() -> dict[str, Any]:
    _reset_state()
    payload = _menu_response()
    payload["hint"] = "Choisissez une option ou ecrivez votre besoin."
    return payload


def _delivery_hours_text() -> str:
    return current_app.config.get(
        "ASSISTANT_DELIVERY_HOURS_TEXT",
        "Livraison disponible tous les jours de 8h a 3h du matin, selon disponibilite du livreur.",
    )


def _faq_delivery_response() -> dict[str, Any]:
    delivery_text = _delivery_hours_text()
    return {"text": delivery_text, "quick_replies": _main_quick_replies()}


def _start_catalog_flow(state: dict[str, Any], kind: str) -> dict[str, Any]:
    kind_label = {
        CATALOG_KIND_PRODUCTS: "produits",
        CATALOG_KIND_SERVICES: "services",
        CATALOG_KIND_LOCATIONS: "locations",
    }.get(kind, "produits")

    state["flow"] = FLOW_CATALOG
    state["step"] = "await_query"
    state["context"] = {"kind": kind}
    _save_state(state)
    return {
        "text": f"Super. Que cherchez-vous en {kind_label} ?",
        "quick_replies": _category_quick_replies(kind),
    }


def _parse_budget(value: str | None) -> int | None:
    text = _normalize_text(value)
    if not text:
        return None
    if text in {"none", "sans limite", "illimite", "illimitee"}:
        return DEFAULT_MAX_BUDGET_DH
    found = _extract_first_number(text)
    if found is None:
        return None
    return max(30, min(found, DEFAULT_MAX_BUDGET_DH))


def _normalize_catalog_query(value: str | None) -> str:
    text = _normalize_text(value)
    if text in {"__any__", "sans filtre", "tout"}:
        return ""
    return text


def _shop_search_quick_replies() -> list[dict[str, str]]:
    return [
        {"label": "Trouver une autre boutique", "action": "find_shops"},
        {"label": "Trouver un produit", "action": "find_products"},
        {"label": "Trouver un service", "action": "find_services"},
        {"label": "Trouver une location", "action": "find_locations"},
        {"label": "Parler a un humain", "action": "handoff"},
    ]


def _extract_shop_query_terms(query_text: str) -> list[str]:
    folded = _fold_text(query_text)
    if not folded:
        return []

    terms: list[str] = []
    for token in re.split(r"[^a-z0-9]+", folded):
        if len(token) < 2 or token in SHOP_QUERY_STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)

    if not terms and len(folded) >= 2:
        terms.append(folded)

    return terms[:5]


def _search_shops_by_name(query_text: str) -> list[dict[str, Any]]:
    terms = _extract_shop_query_terms(query_text)
    if not terms:
        return []

    query = (
        Shop.query.options(
            load_only(
                Shop.id,
                Shop.name,
                Shop.slug,
                Shop.description,
                Shop.is_verified,
                Shop.primary_type,
                Shop.allowed_types_json,
            )
        )
        .filter(Shop.is_active.is_(True))
    )

    for term in terms:
        like = f"%{term}%"
        query = query.filter(
            or_(
                Shop.name.ilike(like),
                Shop.slug.ilike(like),
                Shop.description.ilike(like),
            )
        )

    shops = (
        query.order_by(Shop.is_verified.desc(), Shop.created_at.desc(), Shop.id.desc())
        .limit(5)
        .all()
    )
    if not shops:
        return []

    cards: list[dict[str, Any]] = []
    for shop in shops:
        universes: list[str] = []
        if shop.allows("products"):
            universes.append("Produits")
        if shop.allows("services"):
            universes.append("Services")
        if shop.allows("location"):
            universes.append("Locations")
        universe_label = ", ".join(universes) if universes else "Boutique"
        verification_label = "Verifiee" if bool(getattr(shop, "is_verified", False)) else "Active"
        description = (getattr(shop, "description", "") or "").strip()
        description = description[:90] if description else universe_label

        cards.append(
            {
                "title": shop.name,
                "subtitle": f"{verification_label} | {universe_label}",
                "meta": description,
                "url": url_for("shops.shop_detail", shop_slug=shop.slug),
                "cta": "Visiter la boutique",
            }
        )

    return cards


def _shop_search_response(
    query_text: str,
    *,
    include_empty_feedback: bool = False,
) -> dict[str, Any] | None:
    raw_query = (query_text or "").strip()
    if len(_fold_text(raw_query)) < 2:
        if not include_empty_feedback:
            return None
        return {
            "text": "Donnez-moi au moins 2 lettres du nom de la boutique.",
            "quick_replies": _shop_search_quick_replies(),
        }

    cards = _search_shops_by_name(raw_query)
    if cards:
        return {
            "text": f"J'ai trouve {len(cards)} boutique(s) pour '{raw_query}'.",
            "items": cards,
            "quick_replies": _shop_search_quick_replies(),
        }

    if not include_empty_feedback:
        return None

    return {
        "text": (
            f"Aucune boutique trouvee pour '{raw_query}'. "
            "Essayons une autre recherche ?"
        ),
        "quick_replies": _shop_search_quick_replies(),
    }


def _start_shop_flow(state: dict[str, Any]) -> dict[str, Any]:
    state["flow"] = FLOW_SHOPS
    state["step"] = STEP_SHOPS_AWAIT_QUERY
    state["context"] = {}
    _save_state(state)
    return {
        "text": "D'accord. Donnez-moi le nom de la boutique a trouver.",
        "quick_replies": _shop_search_quick_replies(),
    }


def _shop_query_step(state: dict[str, Any], query_text: str) -> dict[str, Any]:
    state["flow"] = None
    state["step"] = None
    state["context"] = {}
    _save_state(state)
    response = _shop_search_response(query_text, include_empty_feedback=True)
    if response is not None:
        return response
    return {
        "text": "Je n'ai pas trouve de boutique pour cette recherche.",
        "quick_replies": _shop_search_quick_replies(),
    }


def _search_products_or_services(
    kind: str,
    query_terms: list[str],
    budget_max_dh: int,
    *,
    category_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    product_kind = "service" if kind == CATALOG_KIND_SERVICES else "physical"
    query = (
        Product.query.options(
            joinedload(Product.shop).load_only(Shop.id, Shop.name, Shop.rating),
            joinedload(Product.category).load_only(Category.id, Category.name),
        )
        .outerjoin(Category)
        .outerjoin(Shop, Shop.id == Product.shop_id)
        .filter(Product.is_active.is_(True))
        .filter(Product.kind == product_kind)
        .filter(Product.price <= float(budget_max_dh))
    )

    if category_ids:
        query = query.filter(Product.category_id.in_(category_ids))

    if query_terms:
        clauses = []
        for term in query_terms:
            like = f"%{term}%"
            clauses.extend(
                [
                    Product.name.ilike(like),
                    Product.description.ilike(like),
                    Category.name.ilike(like),
                    Shop.name.ilike(like),
                ]
            )
        query = query.filter(or_(*clauses))

    products = (
        query.order_by(Product.view_count.desc(), Product.created_at.desc(), Product.id.desc())
        .limit(5)
        .all()
    )
    if not products:
        return []

    promo_map = get_active_promos_for_products([product.id for product in products])
    cards: list[dict[str, Any]] = []
    for product in products:
        final_cents = final_price_cents(product, promo_map.get(product.id))
        final_price_dh = cents_to_money(final_cents)
        shop = product.shop
        shop_label = getattr(shop, "name", "") or "Boutique"
        rating = float(getattr(shop, "rating", 0.0) or 0.0)
        category_name = getattr(product.category, "name", "") if product.category else ""
        cards.append(
            {
                "title": product.name,
                "subtitle": f"{shop_label} | {final_price_dh:.2f} DH",
                "meta": f"{category_name} | Note {rating:.1f}" if category_name else f"Note {rating:.1f}" if rating else "Nouveau",
                "url": url_for("shop.product_detail", pid=product.id),
                "cta": "Voir details",
            }
        )
    return cards


def _search_locations(query_terms: list[str], budget_max_dh: int) -> list[dict[str, Any]]:
    query = (
        RentalListing.query.options(joinedload(RentalListing.shop).load_only(Shop.id, Shop.name, Shop.rating))
        .outerjoin(Shop, Shop.id == RentalListing.shop_id)
        .filter(RentalListing.is_active.is_(True))
        .filter(RentalListing.status.in_(("active", "reserved")))
        .filter(or_(RentalListing.expires_at.is_(None), RentalListing.expires_at > datetime.utcnow()))
        .filter(RentalListing.rent_cents <= int(budget_max_dh) * 100)
    )

    if query_terms:
        clauses = []
        for term in query_terms:
            like = f"%{term}%"
            clauses.extend(
                [
                    RentalListing.title.ilike(like),
                    RentalListing.description.ilike(like),
                    RentalListing.city.ilike(like),
                    RentalListing.area.ilike(like),
                    RentalListing.property_type.ilike(like),
                    RentalListing.listing_type.ilike(like),
                    Shop.name.ilike(like),
                ]
            )
        query = query.filter(or_(*clauses))

    listings = (
        query.order_by(RentalListing.view_count.desc(), RentalListing.created_at.desc(), RentalListing.id.desc())
        .limit(5)
        .all()
    )
    if not listings:
        return []

    cards: list[dict[str, Any]] = []
    for listing in listings:
        rent_dh = cents_to_money(int(listing.rent_cents or 0))
        rent_type = "Mensuel" if (listing.listing_type or "").lower() == "monthly" else "Journalier"
        shop = listing.shop
        shop_label = getattr(shop, "name", "") or "Annonce"
        rating = float(getattr(shop, "rating", 0.0) or 0.0)
        city = (listing.city or "").strip()
        cards.append(
            {
                "title": listing.title,
                "subtitle": f"{city} | {rent_dh:.2f} DH ({rent_type})",
                "meta": f"{shop_label} | Note {rating:.1f}" if rating else shop_label,
                "url": url_for("rentals.location_detail", slug=listing.slug),
                "cta": "Voir details",
            }
        )
    return cards


def _iter_search_terms(
    kind: str,
    query_text: str,
    *,
    category_terms: list[str] | None = None,
) -> list[str]:
    raw_terms = _expand_query_terms(kind, query_text, category_terms=category_terms)
    terms: list[str] = []
    for raw in raw_terms:
        normalized = _normalize_text(raw)
        if len(normalized) < 2:
            continue
        if normalized in terms:
            continue
        terms.append(normalized)
    return terms[:6]


def _search_products_or_services_via_api(
    kind: str,
    query_text: str,
    budget_max_dh: int,
    *,
    category_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    category_context = category_context or {}
    category_terms = list(category_context.get("terms") or [])
    category_labels = {_fold_text(label) for label in (category_context.get("labels") or []) if _fold_text(label)}
    terms = _iter_search_terms(kind, query_text, category_terms=category_terms)
    if not terms:
        return []

    want_services = kind == CATALOG_KIND_SERVICES
    cards: list[dict[str, Any]] = []
    seen: set[int] = set()

    for term in terms:
        rows = search_public_products(search_q=term, limit=16)
        for row in rows:
            item_id = int(row.get("id") or 0)
            if item_id <= 0 or item_id in seen:
                continue
            row_kind = _normalize_text(row.get("kind"))
            is_service = row_kind == "service"
            if want_services != is_service:
                continue

            price_value = float(row.get("final_price") or row.get("price") or 0.0)
            if price_value <= 0 or price_value > float(budget_max_dh):
                continue

            if category_labels:
                row_category = _fold_text(row.get("category"))
                if row_category not in category_labels:
                    continue

            subtitle_shop = str(row.get("shop_name") or "Boutique")
            category_name = str(row.get("category") or "").strip()
            meta = category_name if category_name else ("Service" if want_services else "Produit")
            target_url = str(row.get("booking_url") or row.get("url") or "").strip()
            if not target_url:
                target_url = url_for("shop.product_detail", pid=item_id)

            cards.append(
                {
                    "title": str(row.get("name") or ""),
                    "subtitle": f"{subtitle_shop} | {price_value:.2f} DH",
                    "meta": meta,
                    "url": target_url,
                    "cta": "Voir details",
                }
            )
            seen.add(item_id)
            if len(cards) >= 5:
                return cards
    return cards


def _search_locations_via_api(
    query_text: str,
    budget_max_dh: int,
    *,
    category_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    category_context = category_context or {}
    terms = _iter_search_terms(
        CATALOG_KIND_LOCATIONS,
        query_text,
        category_terms=list(category_context.get("terms") or []),
    )
    if not terms:
        return []

    cards: list[dict[str, Any]] = []
    seen: set[int] = set()

    for term in terms:
        rows = search_public_locations(search_q=term, limit=16)
        for row in rows:
            listing_id = int(row.get("id") or 0)
            if listing_id <= 0 or listing_id in seen:
                continue

            rent_dh = float(row.get("rent_dh") or 0.0)
            if rent_dh <= 0 or rent_dh > float(budget_max_dh):
                continue

            listing_type = _normalize_text(row.get("listing_type"))
            rent_type_label = "Mensuel" if listing_type == "monthly" else "Journalier"
            city = str(row.get("city") or "").strip()
            area = str(row.get("area") or "").strip()
            city_label = city if city else "Maroc"
            if area:
                city_label = f"{city_label} - {area}"

            cards.append(
                {
                    "title": str(row.get("title") or ""),
                    "subtitle": f"{city_label} | {rent_dh:.2f} DH ({rent_type_label})",
                    "meta": str(row.get("shop_name") or "Annonce"),
                    "url": str(row.get("url") or ""),
                    "cta": "Voir details",
                }
            )
            seen.add(listing_id)
            if len(cards) >= 5:
                return cards
    return cards


def _search_catalog_via_existing_api(
    kind: str,
    query_text: str,
    budget_max_dh: int,
    *,
    category_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if kind == CATALOG_KIND_LOCATIONS:
        return _search_locations_via_api(
            query_text,
            budget_max_dh,
            category_context=category_context,
        )
    return _search_products_or_services_via_api(
        kind,
        query_text,
        budget_max_dh,
        category_context=category_context,
    )


def _run_catalog_search(kind: str, query_text: str, budget_max_dh: int) -> list[dict[str, Any]]:
    category_context = _category_context_for_query(kind, query_text)
    api_cards = _search_catalog_via_existing_api(
        kind,
        query_text,
        budget_max_dh,
        category_context=category_context,
    )
    if api_cards:
        return api_cards

    query_terms = _expand_query_terms(
        kind,
        query_text,
        category_terms=list(category_context.get("terms") or []),
    )
    if kind == CATALOG_KIND_LOCATIONS:
        db_cards = _search_locations(query_terms, budget_max_dh)
    else:
        db_cards = _search_products_or_services(
            kind,
            query_terms,
            budget_max_dh,
            category_ids=list(category_context.get("ids") or []),
        )
    if db_cards:
        return db_cards

    return []


def _catalog_query_step(state: dict[str, Any], choice_text: str) -> dict[str, Any]:
    query_text = _normalize_catalog_query(choice_text)
    kind = str(state.get("context", {}).get("kind") or CATALOG_KIND_PRODUCTS)
    profile = _semantic_profile_for_query(query_text)

    auto_switched_note = ""
    if profile:
        preferred_kind = str(profile.get("preferred_kind") or "")
        if preferred_kind and preferred_kind != kind:
            kind = preferred_kind
            auto_switched_note = (
                "J'ai detecte un besoin plus pertinent dans cet univers, je bascule automatiquement."
            )

    state["step"] = "await_budget"
    state["context"]["query"] = query_text
    state["context"]["kind"] = kind
    _save_state(state)

    if query_text:
        prefix = f"{auto_switched_note}\n" if auto_switched_note else ""
        return {
            "text": f"{prefix}Parfait. Quel budget max pour '{query_text}' ?",
            "quick_replies": _budget_quick_replies(kind),
        }
    return {
        "text": "Parfait. Quel budget max souhaitez-vous ?",
        "quick_replies": _budget_quick_replies(kind),
    }


def _catalog_budget_step(state: dict[str, Any], choice_text: str) -> dict[str, Any]:
    budget = _parse_budget(choice_text)
    if budget is None:
        kind = str(state.get("context", {}).get("kind") or CATALOG_KIND_PRODUCTS)
        return {
            "text": "Je n'ai pas compris le budget. Choisissez une option ou ecrivez un montant en DH.",
            "quick_replies": _budget_quick_replies(kind),
        }

    kind = str(state.get("context", {}).get("kind") or CATALOG_KIND_PRODUCTS)
    query_text = str(state.get("context", {}).get("query") or "")
    cards = _run_catalog_search(kind, query_text, budget)
    result_kind = kind

    # If first search fails, try semantically close universes.
    if not cards:
        fallback_order = [CATALOG_KIND_PRODUCTS, CATALOG_KIND_SERVICES, CATALOG_KIND_LOCATIONS]
        profile = _semantic_profile_for_query(query_text)
        preferred_kind = str(profile.get("preferred_kind") or "") if profile else ""
        if preferred_kind and preferred_kind in fallback_order:
            fallback_order.remove(preferred_kind)
            fallback_order.insert(0, preferred_kind)
        if kind in fallback_order:
            fallback_order.remove(kind)
        for fallback_kind in fallback_order:
            cards = _run_catalog_search(fallback_kind, query_text, budget)
            if cards:
                result_kind = fallback_kind
                break

    state["flow"] = None
    state["step"] = None
    state["context"] = {}
    _save_state(state)

    if not cards:
        return {
            "text": (
                "Aucun resultat trouve avec ce filtre dans les donnees actuelles de l'application. "
                "Voulez-vous changer de recherche ?"
            ),
            "quick_replies": [
                {"label": "Essayer Produits", "action": "find_products"},
                {"label": "Essayer Services", "action": "find_services"},
                {"label": "Essayer Locations", "action": "find_locations"},
                {"label": "Parler a un humain", "action": "handoff"},
            ],
        }

    type_label = {
        CATALOG_KIND_PRODUCTS: "produits",
        CATALOG_KIND_SERVICES: "services",
        CATALOG_KIND_LOCATIONS: "locations",
    }.get(result_kind, "resultats")
    lead = "Voici des suggestions adaptees :"
    if result_kind != kind:
        lead = f"Aucun resultat dans le type choisi. Je vous propose des {type_label} adaptes :"

    return {
        "text": f"{lead}\nTotal: {len(cards)} resultat(s).",
        "items": cards,
        "quick_replies": [
            {"label": "Modifier recherche", "action": "start"},
            {"label": "Besoin livraison", "action": "help_delivery"},
            {"label": "Parler a un humain", "action": "handoff"},
        ],
    }


def _start_delivery_flow(state: dict[str, Any]) -> dict[str, Any]:
    state["flow"] = FLOW_DELIVERY
    state["step"] = STEP_DELIVERY_AWAIT_CITY
    state["context"] = {}
    _save_state(state)
    return {
        "text": "Pour la livraison, dans quelle ville etes-vous ?",
        "quick_replies": _city_quick_replies(),
    }


def _delivery_city_step(state: dict[str, Any], city_text: str) -> dict[str, Any]:
    city = city_text.strip().title() if city_text else "Votre ville"
    state["flow"] = FLOW_DELIVERY
    state["step"] = STEP_DELIVERY_AWAIT_HANDOFF_CONFIRMATION
    state["context"] = {"city": city}
    _save_state(state)
    return {
        "text": (
            f"Bien note pour {city}. {_delivery_hours_text()}\n"
            "Je peux vous mettre en relation directe avec le service livraison.\n"
            "Souhaitez-vous que je le fasse maintenant ? (oui/non)"
        ),
        "quick_replies": [
            {"label": "Oui", "action": "delivery_confirm", "value": "yes"},
            {"label": "Non", "action": "delivery_decline", "value": "no"},
            {"label": "Trouver un produit", "action": "find_products"},
            {"label": "Trouver un service", "action": "find_services"},
            {"label": "Trouver une location", "action": "find_locations"},
            {"label": "Parler a un humain", "action": "handoff"},
        ],
    }


def _delivery_confirm_step(state: dict[str, Any]) -> dict[str, Any]:
    city = str(state.get("context", {}).get("city") or "votre ville")
    state["flow"] = None
    state["step"] = None
    state["context"] = {}
    _save_state(state)
    return {
        "text": f"Parfait. Je vous mets en relation pour la livraison sur {city}.",
        "handoff": _delivery_handoff_payload(),
        "quick_replies": _main_quick_replies(),
    }


def _delivery_decline_step(state: dict[str, Any]) -> dict[str, Any]:
    state["flow"] = None
    state["step"] = None
    state["context"] = {}
    _save_state(state)
    return {
        "text": "D'accord, pas de souci. Je reste disponible si vous avez besoin.",
        "quick_replies": _main_quick_replies(),
    }


def _is_greeting(text: str) -> bool:
    return text in {"salut", "bonjour", "hello", "salam", "bonsoir", "yo"}


def _is_handoff_request(text: str) -> bool:
    return _contains_any(text, ("humain", "agent", "conseiller", "whatsapp", "contact"))


def _is_vendor_onboarding_intent(text: str) -> bool:
    return _contains_any(
        text,
        (
            "devenir vendeur",
            "vendeur",
            "ouvrir boutique",
            "creer boutique",
            "inscription vendeur",
            "acces vendeur",
        ),
    )


def _is_delivery_faq(text: str) -> bool:
    return _contains_any(text, ("livraison", "delai", "frais", "expedition", "shipping"))


def _is_yes_intent(text: str) -> bool:
    return _contains_any(text, ("oui", "ok", "okay", "yes", "daccord", "dac", "vas y", "go"))


def _is_no_intent(text: str) -> bool:
    return _contains_any(text, ("non", "nom", "no", "annuler", "pas maintenant", "plus tard"))


def _is_product_intent(text: str) -> bool:
    return _contains_any(text, ("produit", "article", "acheter", "achat", "cadeau"))


def _is_service_intent(text: str) -> bool:
    return _contains_any(
        text,
        (
            "service",
            "reservation",
            "reserver",
            "rdv",
            "rendez-vous",
            "beaute",
            "coiffure",
            "esthetique",
            "ongle",
            "informatique",
        ),
    )


def _is_location_intent(text: str) -> bool:
    return _contains_any(
        text,
        ("location", "appartement", "chambre", "bureau", "maison", "studio", "immobilier"),
    )


def _is_shop_intent(text: str) -> bool:
    return _contains_any(text, ("boutique", "shop", "magasin"))


def assistant_reply(*, message: str | None, action: str | None = None, value: str | None = None) -> dict[str, Any]:
    text = _normalize_text(message)
    selected_value = _normalize_text(value)
    state = _load_state()

    if action in {"reset", "start"}:
        return assistant_bootstrap()

    if action == "handoff" or _is_handoff_request(text):
        return {
            "text": "D'accord. Je vous mets en relation avec un conseiller humain.",
            "handoff": _handoff_payload(),
            "quick_replies": _main_quick_replies(),
        }

    if action == "faq_delivery":
        return _faq_delivery_response()

    if action == "help_delivery":
        return _start_delivery_flow(state)

    if action == "become_vendor":
        return {
            "text": "Parfait. Je vous redirige vers la page Devenir vendeur.",
            "redirect_url": url_for("auth.vendor_access"),
        }

    if action == "delivery_confirm":
        return _delivery_confirm_step(state)
    if action == "delivery_decline":
        return _delivery_decline_step(state)

    if action == "find_products":
        return _start_catalog_flow(state, CATALOG_KIND_PRODUCTS)
    if action == "find_services":
        return _start_catalog_flow(state, CATALOG_KIND_SERVICES)
    if action == "find_locations":
        return _start_catalog_flow(state, CATALOG_KIND_LOCATIONS)
    if action == "find_shops":
        return _start_shop_flow(state)

    if action == "find_gift":
        return _start_catalog_flow(state, CATALOG_KIND_PRODUCTS)

    if state.get("flow") == FLOW_CATALOG and state.get("step") == "await_query":
        choice = selected_value or text
        return _catalog_query_step(state, choice)

    if state.get("flow") == FLOW_CATALOG and state.get("step") == "await_budget":
        choice = selected_value or text
        return _catalog_budget_step(state, choice)

    if state.get("flow") == FLOW_SHOPS and state.get("step") == STEP_SHOPS_AWAIT_QUERY:
        choice = selected_value or text
        return _shop_query_step(state, choice)

    if state.get("flow") == FLOW_DELIVERY and state.get("step") == STEP_DELIVERY_AWAIT_CITY:
        choice = (selected_value or text or "Rabat").strip()
        return _delivery_city_step(state, choice)

    if (
        state.get("flow") == FLOW_DELIVERY
        and state.get("step") == STEP_DELIVERY_AWAIT_HANDOFF_CONFIRMATION
    ):
        choice = selected_value or text
        if _is_yes_intent(choice):
            return _delivery_confirm_step(state)
        if _is_no_intent(choice):
            return _delivery_decline_step(state)
        return {
            "text": "Je n'ai pas compris. Repondez juste par oui ou non.",
            "quick_replies": [
                {"label": "Oui", "action": "delivery_confirm", "value": "yes"},
                {"label": "Non", "action": "delivery_decline", "value": "no"},
            ],
        }

    if not text or _is_greeting(text):
        return _menu_response()

    if _is_product_intent(text):
        return _start_catalog_flow(state, CATALOG_KIND_PRODUCTS)
    if _is_service_intent(text):
        return _start_catalog_flow(state, CATALOG_KIND_SERVICES)
    if _is_location_intent(text):
        return _start_catalog_flow(state, CATALOG_KIND_LOCATIONS)
    if _is_shop_intent(text):
        response = _shop_search_response(text, include_empty_feedback=False)
        if response is not None:
            return response
        return _start_shop_flow(state)
    if _is_vendor_onboarding_intent(text):
        return {
            "text": "Parfait. Je vous redirige vers la page Devenir vendeur.",
            "redirect_url": url_for("auth.vendor_access"),
        }
    if _is_delivery_faq(text):
        return _faq_delivery_response()
    if _is_yes_intent(text):
        return {
            "text": "Super. Dites-moi votre besoin: Produits, Services, Locations, Boutiques ou Livraison.",
            "quick_replies": _main_quick_replies(),
        }
    if _is_no_intent(text):
        return {
            "text": "D'accord. Je reste disponible pour vous aider quand vous voulez.",
            "quick_replies": _main_quick_replies(),
        }
    if _extract_first_number(text) is not None:
        return {
            "text": "Merci. Avant le budget, choisissez d'abord l'univers: Produits, Services ou Locations.",
            "quick_replies": [
                {"label": "Produits", "action": "find_products"},
                {"label": "Services", "action": "find_services"},
                {"label": "Locations", "action": "find_locations"},
            ],
        }

    shop_response = _shop_search_response(text, include_empty_feedback=False)
    if shop_response is not None:
        return shop_response

    return {
        "text": (
            "Je n'ai pas encore bien compris. Je peux vous aider pour Produits, Services, "
            "Locations, Boutiques ou Livraison."
        ),
        "quick_replies": _main_quick_replies(),
    }
