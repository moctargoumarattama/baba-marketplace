# app/services/pricing.py
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import unicodedata

from ..models.platform_settings import PlatformSettings
from ..models.promo import Promo


def _promo_is_active(promo) -> bool:
    return bool(promo and promo.end_date and promo.end_date >= datetime.utcnow())


def get_active_promo(product_id):
    """Return the nearest active promo for a product."""
    now = datetime.utcnow()
    return (
        Promo.query
        .filter(Promo.product_id == product_id, Promo.end_date >= now)
        .order_by(Promo.end_date.asc())
        .first()
    )


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _money(value) -> float:
    return float(_to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def prix_final(product, promo=None):
    if promo is None:
        promo = get_active_promo(product.id)

    price = _to_decimal(getattr(product, "price", 0) or 0)
    if promo and not _promo_is_active(promo):
        promo = None

    if promo:
        promo_val = _to_decimal(getattr(promo, "value", 0) or 0)
        if promo.type == "percentage":
            return _money(price - (price * promo_val / Decimal("100")))
        if promo.type == "fixed":
            return _money(max(price - promo_val, Decimal("0")))
    return _money(price)


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


def get_delivery_price_cents(city: str | None, settings: PlatformSettings | None = None) -> int:
    cfg = settings or PlatformSettings.get()
    city_key = _normalize_city_key(city)

    if city_key == "rabat":
        return int(cfg.shipping_rabat or 0)
    if city_key == "sale":
        return int(cfg.shipping_sale or 0)
    if city_key == "temara":
        return int(cfg.shipping_temara or 0)
    if city_key == "kenitra":
        return int(cfg.shipping_kenitra or 0)
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

