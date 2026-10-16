"""Four public offers per section, rotating through the whole catalogue."""
import math
import time

from ..models.product import Product
from .cache import get_catalog_cache
from .marketplace_feed import _base_product_query, _serialize_product_legacy_tuple
from .pricing import get_active_promos_for_products


ROTATION_SECONDS = 30 * 60
SECTION_LIMIT = 4


def build_home_selection(slot):
    selections = {}
    for section, kind in (("products", "physical"), ("services", "service")):
        query, *_ = _base_product_query(
            search_q="", category_id=None, kind=kind, min_price=None, max_price=None,
            promo_only="0", in_stock="0", shop_id=None,
        )
        total = query.order_by(None).count()
        size = min(SECTION_LIMIT, total)
        if not size:
            selections[section] = []
            continue
        # Stable order and a circular window give every offer equal exposure.
        # SQL pagination reaches older offers without loading the whole catalogue.
        offset = (slot * size) % total
        ordered = query.order_by(Product.id.asc())
        products = ordered.offset(offset).limit(size).all()
        if len(products) < size:
            products += ordered.limit(size - len(products)).all()
        selections[section] = products

    promos = get_active_promos_for_products(
        [product.id for products in selections.values() for product in products]
    )
    return {
        section: [_serialize_product_legacy_tuple(product, promos.get(product.id)) for product in products]
        for section, products in selections.items()
    }


def get_home_selection():
    now = time.time()
    slot = int(now // ROTATION_SECONDS)
    selection = get_catalog_cache(
        f"home-selection:v1:{slot}", lambda: build_home_selection(slot), timeout=60,
    )
    return {
        **selection,
        "refresh_after": max(1, math.ceil((slot + 1) * ROTATION_SECONDS - time.time())),
    }
