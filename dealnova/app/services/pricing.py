# app/services/pricing.py
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import unicodedata

from ..extensions import db
from ..models.platform_settings import PlatformSettings
from ..models.promo import Promo

_PROMO_UNSET = object()


def _safe_session_rollback() -> None:
    try:
        db.session.rollback()
    except Exception:
        pass


def _promo_is_active(promo) -> bool:
    return bool(promo and promo.end_date and promo.end_date >= datetime.utcnow())


def get_active_promo(product_id):
    """Return the nearest active promo for a product."""
    now = datetime.utcnow()
    try:
        return (
            Promo.query
            .filter(Promo.product_id == product_id, Promo.end_date >= now)
            .order_by(Promo.end_date.asc())
            .first()
        )
    except Exception:
        _safe_session_rollback()
        return None


# ===== NOUVELLE FONCTION (AJOUTÉE SANS SUPPRIMER L'ANCIENNE) =====
def get_active_promos_for_products(product_ids):
    """Charge toutes les promos actives pour une liste de produits en 1 requête."""
    if not product_ids:
        return {}
    
    now = datetime.utcnow()
    try:
        promos = Promo.query.filter(
            Promo.product_id.in_(product_ids),
            Promo.end_date >= now
        ).order_by(Promo.product_id.asc(), Promo.end_date.asc()).all()
    except Exception:
        _safe_session_rollback()
        return {}
    
    promo_map = {}
    for promo in promos:
        if promo.product_id not in promo_map:  # Garde la plus proche
            promo_map[promo.product_id] = promo
    return promo_map


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _money(value) -> float:
    return float(_to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate_promo_price(product, promo=_PROMO_UNSET):
    if promo is _PROMO_UNSET:
        promo = get_active_promo(product.id)

    price = _to_decimal(getattr(product, "price", 0) or 0)
    if promo and not _promo_is_active(promo):
        promo = None

    if promo:
        promo_val = _to_decimal(getattr(promo, "value", 0) or 0)
        if getattr(promo, "type", "") == "percentage":
            discounted = price - (price * promo_val / Decimal("100"))
            return _money(max(discounted, Decimal("0")))
        if getattr(promo, "type", "") == "fixed":
            return _money(max(price - promo_val, Decimal("0")))
    return _money(price)


def prix_final(product, promo=None):
    return calculate_promo_price(product, promo=promo)


def compute_commission(_total):
    """Deprecated: seller commission is disabled for product/service orders."""
    return 0


def compute_shipping(_total):
    """Deprecated: use city-based delivery pricing."""
    return 2000


DELIVERY_CITIES = ["Rabat", "Sale", "Temara", "Kenitra"]


def _normalize_city_key(city: str | None) -> str:
    raw = (city or "").strip().lower()
    if not raw:
        return ""
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def list_delivery_cities() -> list[str]:
    return DELIVERY_CITIES[:]


# ===== VERSION AMÉLIORÉE DE get_delivery_price_cents (plus maintenable) =====
def get_delivery_price_cents(city: str | None, settings: PlatformSettings | None = None) -> int:
    cfg = settings or PlatformSettings.get()
    city_key = _normalize_city_key(city)
    
    # Mapping plus maintenable (mais garde l'ancienne logique)
    city_to_field = {
        "rabat": "shipping_rabat",
        "sale": "shipping_sale",
        "temara": "shipping_temara",
        "kenitra": "shipping_kenitra",
    }
    
    field = city_to_field.get(city_key)
    if field:
        return int(getattr(cfg, field, 0) or 0)
    return 0


def get_delivery_platform_fee_cents(settings: PlatformSettings | None = None) -> int:
    cfg = settings or PlatformSettings.get()
    return max(0, int(getattr(cfg, "delivery_platform_fee_fixed_cents", 0) or 0))


def get_delivery_courier_net_cents(
    delivery_price_cents: int,
    settings: PlatformSettings | None = None,
) -> int:
    return max(0, int(delivery_price_cents or 0) - get_delivery_platform_fee_cents(settings=settings))


def compute_shipping_by_city(city: str | None, settings: PlatformSettings | None = None) -> int:
    return get_delivery_price_cents(city, settings=settings)
