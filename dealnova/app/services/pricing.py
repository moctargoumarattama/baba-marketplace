# app/services/pricing.py
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import unicodedata

from ..extensions import db
from ..models.platform_settings import PlatformSettings
from ..models.promo import Promo

_PROMO_UNSET = object()
_MONEY_QUANTUM = Decimal("0.01")


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


def money_decimal(value) -> Decimal:
    return _to_decimal(value).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def parse_money_input(value, *, allow_zero: bool = True) -> Decimal:
    raw = str(value or "").strip().replace(",", ".")
    if not raw:
        raise ValueError("money_required")

    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("money_invalid") from exc

    amount = amount.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if amount < 0 or (not allow_zero and amount <= 0):
        raise ValueError("money_invalid")
    return amount


def _money(value) -> float:
    return float(money_decimal(value))


def money_to_cents(value) -> int:
    amount = money_decimal(value)
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def cents_to_money(value) -> float:
    return float((Decimal(int(value or 0)) / Decimal("100")).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def dh_to_cents(value) -> int:
    return money_to_cents(value)


def product_base_cents(product) -> int:
    direct_cents = getattr(product, "price_cents", None)
    if direct_cents is not None:
        try:
            return max(0, int(direct_cents))
        except (TypeError, ValueError):
            pass

    stored_cents = getattr(product, "price_cents_value", None)
    if stored_cents is not None:
        try:
            return max(0, int(stored_cents))
        except (TypeError, ValueError):
            pass

    return money_to_cents(getattr(product, "price", 0) or 0)


def set_product_price(product, value) -> int:
    cents = money_to_cents(parse_money_input(value, allow_zero=False))
    if hasattr(product, "set_price_amount"):
        product.price_cents = cents
        return cents

    setattr(product, "price", cents_to_money(cents))
    if hasattr(product, "price_cents_value"):
        setattr(product, "price_cents_value", cents)
    return cents


def base_price_decimal(product) -> Decimal:
    return money_decimal(Decimal(product_base_cents(product)) / Decimal("100"))


def base_price_cents(product) -> int:
    return product_base_cents(product)


def calculate_promo_price_decimal(product, promo=_PROMO_UNSET) -> Decimal:
    if promo is _PROMO_UNSET:
        promo = get_active_promo(product.id)

    price = base_price_decimal(product)
    if promo and not _promo_is_active(promo):
        promo = None

    if promo:
        promo_val = money_decimal(getattr(promo, "value", 0) or 0)
        if getattr(promo, "type", "") == "percentage":
            discounted = price - (price * promo_val / Decimal("100"))
            return money_decimal(max(discounted, Decimal("0")))
        if getattr(promo, "type", "") == "fixed":
            return money_decimal(max(price - promo_val, Decimal("0")))
    return money_decimal(price)


def calculate_promo_price(product, promo=_PROMO_UNSET):
    return _money(calculate_promo_price_decimal(product, promo=promo))


def prix_final(product, promo=None):
    return calculate_promo_price(product, promo=promo)


def final_price_decimal(product, promo=None) -> Decimal:
    return calculate_promo_price_decimal(product, promo=promo)


def final_price_cents(product, promo=None) -> int:
    return money_to_cents(final_price_decimal(product, promo=promo))


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
