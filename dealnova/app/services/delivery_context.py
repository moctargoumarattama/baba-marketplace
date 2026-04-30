from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote_plus

from .i18n_labels import label_source as i18n_label_source, normalize_lang

DELIVERY_SOURCE_MARKETPLACE = "marketplace"
DELIVERY_SOURCE_SPECIAL = "special"
DELIVERY_SOURCES = (DELIVERY_SOURCE_MARKETPLACE, DELIVERY_SOURCE_SPECIAL)


def normalize_delivery_source(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in DELIVERY_SOURCES else DELIVERY_SOURCE_MARKETPLACE


def delivery_source_label(source: str | None, lang: str | None = None) -> str:
    return i18n_label_source(normalize_delivery_source(source), normalize_lang(lang))


def safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _normalize_text(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def canonical_city_name(raw_city: str | None, allowed_cities: list[str] | tuple[str, ...]) -> str | None:
    value = (raw_city or "").strip()
    if not value:
        return None
    for city in allowed_cities:
        if value == city:
            return city
    wanted = _normalize_text(value)
    if not wanted:
        return None
    for city in allowed_cities:
        if _normalize_text(city) == wanted:
            return city
    return None


def maps_url_from_lat_lng(lat, lng) -> str:
    lat_val = safe_float(lat)
    lng_val = safe_float(lng)
    if lat_val is None or lng_val is None:
        return ""
    if not (-90 <= lat_val <= 90 and -180 <= lng_val <= 180):
        return ""
    return f"https://www.google.com/maps?q={lat_val:.6f},{lng_val:.6f}"


def maps_url_from_text(*parts: str) -> str:
    cleaned = [str(part).strip() for part in parts if str(part or "").strip()]
    if not cleaned:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(', '.join(cleaned))}"


def has_valid_lat_lng(lat, lng) -> bool:
    lat_val = safe_float(lat)
    lng_val = safe_float(lng)
    if lat_val is None or lng_val is None:
        return False
    return -90 <= lat_val <= 90 and -180 <= lng_val <= 180


def format_lat_lng(lat, lng) -> str:
    if not has_valid_lat_lng(lat, lng):
        return ""
    lat_val = safe_float(lat)
    lng_val = safe_float(lng)
    return f"{lat_val:.6f}, {lng_val:.6f}"


def make_maps_url(lat=None, lng=None, address: str | None = None, city: str | None = None) -> str:
    direct = maps_url_from_lat_lng(lat, lng)
    if direct:
        return direct
    return maps_url_from_text(address or "", city or "")


def normalize_phone_for_wa(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def resolve_dropoff(order) -> dict:
    source = normalize_delivery_source(getattr(order, "delivery_source", None))
    city = (
        (getattr(order, "delivery_city", None) or "").strip()
        or (getattr(order, "city", None) or "").strip()
    )
    if source == DELIVERY_SOURCE_SPECIAL:
        address = (
            (getattr(order, "special_dropoff_address", None) or "").strip()
            or (getattr(order, "delivery_address", None) or "").strip()
            or (getattr(order, "address", None) or "").strip()
        )
        lat = getattr(order, "special_dropoff_lat", None)
        lng = getattr(order, "special_dropoff_lng", None)
        maps_url = (getattr(order, "special_dropoff_maps_url", None) or "").strip()
        if not maps_url:
            maps_url = (getattr(order, "delivery_maps_url", None) or "").strip()
    else:
        address = (
            (getattr(order, "delivery_address", None) or "").strip()
            or (getattr(order, "address", None) or "").strip()
        )
        lat = getattr(order, "delivery_lat", None)
        lng = getattr(order, "delivery_lng", None)
        maps_url = (getattr(order, "delivery_maps_url", None) or "").strip()
    if not maps_url:
        maps_url = make_maps_url(lat=lat, lng=lng, address=address, city=city)

    customer_name = (
        (getattr(order, "customer_name", None) or "").strip()
        or (getattr(order, "full_name", None) or "").strip()
    )
    customer_phone = (
        (getattr(order, "customer_phone", None) or "").strip()
        or (getattr(order, "phone", None) or "").strip()
    )
    customer_phone_wa = normalize_phone_for_wa(customer_phone)
    has_coords = has_valid_lat_lng(lat, lng)
    complete = bool(address) or has_coords

    return {
        "city": city or "N/A",
        "address": address or "N/A",
        "lat": lat,
        "lng": lng,
        "coords_text": format_lat_lng(lat, lng) or "N/A",
        "has_coords": has_coords,
        "is_complete": complete,
        "status": "ok" if complete else "incomplete",
        "maps_url": maps_url or "",
        "customer_name": customer_name or "N/A",
        "customer_phone": customer_phone or "N/A",
        "customer_phone_wa": customer_phone_wa or "",
    }


def _marketplace_pickup_from_order_items(order) -> dict:
    shops_by_id = {}
    for item in getattr(order, "items", []) or []:
        product = getattr(item, "product", None)
        shop = getattr(product, "shop", None) if product else None
        if shop is None or getattr(shop, "id", None) is None:
            continue
        shops_by_id[shop.id] = shop

    if not shops_by_id:
        return {
            "shop_name": "N/A",
            "address": "N/A",
            "note": "",
            "lat": None,
            "lng": None,
            "coords_text": "N/A",
            "has_coords": False,
            "is_complete": None,
            "status": "na",
            "maps_url": "",
            "multi_shops": [],
        }

    shops = list(shops_by_id.values())
    primary_shop = shops[0]
    shop_names = [((getattr(shop, "name", None) or "").strip() or f"Boutique #{shop.id}") for shop in shops]
    shop_name = " / ".join(shop_names) if len(shop_names) > 1 else shop_names[0]
    address = (getattr(primary_shop, "address", None) or "").strip()
    note = (getattr(primary_shop, "service_location_note", None) or "").strip()
    lat = getattr(primary_shop, "service_latitude", None)
    lng = getattr(primary_shop, "service_longitude", None)
    has_coords = has_valid_lat_lng(lat, lng)
    complete = bool(address) or has_coords
    maps_url = make_maps_url(lat=lat, lng=lng, address=address, city=shop_name)

    return {
        "shop_name": shop_name or "N/A",
        "address": address or "N/A",
        "note": note,
        "lat": lat,
        "lng": lng,
        "coords_text": format_lat_lng(lat, lng) or "N/A",
        "has_coords": has_coords,
        "is_complete": complete,
        "status": "ok" if complete else "missing",
        "maps_url": maps_url or "",
        "multi_shops": shop_names,
    }


def resolve_pickup(order) -> dict:
    source = normalize_delivery_source(getattr(order, "delivery_source", None))
    if source == DELIVERY_SOURCE_SPECIAL:
        address = (getattr(order, "special_pickup_address", None) or "").strip()
        note = (getattr(order, "special_note", None) or "").strip()
        lat = getattr(order, "special_pickup_lat", None)
        lng = getattr(order, "special_pickup_lng", None)
        maps_url = (getattr(order, "special_pickup_maps_url", None) or "").strip()
        if not maps_url:
            maps_url = make_maps_url(
                lat=lat,
                lng=lng,
                address=address or note,
                city=(getattr(order, "delivery_city", None) or "").strip(),
            )
        has_coords = has_valid_lat_lng(lat, lng)
        complete = bool(address) or has_coords
        return {
            "shop_name": "Livraison speciale",
            "address": address or "N/A",
            "note": note,
            "lat": lat,
            "lng": lng,
            "coords_text": format_lat_lng(lat, lng) or "N/A",
            "has_coords": has_coords,
            "is_complete": complete,
            "status": "ok" if complete else "missing",
            "maps_url": maps_url or "",
            "multi_shops": [],
        }
    return _marketplace_pickup_from_order_items(order)


def enrich_order_delivery_context(order, lang: str | None = None):
    source = normalize_delivery_source(getattr(order, "delivery_source", None))
    order._delivery_source = source
    order._delivery_source_label = delivery_source_label(source, lang)
    order._delivery_pickup = resolve_pickup(order)
    order._delivery_dropoff = resolve_dropoff(order)
    return order


def enrich_orders_delivery_context(orders, lang: str | None = None):
    for order in orders or []:
        enrich_order_delivery_context(order, lang=lang)
    return orders

