from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from collections import defaultdict

from sqlalchemy import and_, case, or_
from sqlalchemy.orm import selectinload, load_only

from ..extensions import db
from ..models.featured_item import FeaturedItem
from ..models.product import Product
from ..models.promo import Promo
from ..models.rental import RentalListing, RentalMedia
from ..models.shop import Shop
from .featured_items import featured_rank_expr, location_featured_exists_expr, product_featured_exists_expr
from .pricing import cents_to_money, dh_to_cents, final_price_cents, get_active_promos_for_products
from .rentals import rental_existing_video_poster_rel_path


CURATED_PAGE_LIMIT = 5
DEFAULT_CANDIDATE_MULTIPLIER = 4
DEFAULT_MAX_FETCH = 240
ANTI_MONOPOLY_WINDOW = 20
ANTI_MONOPOLY_MAX_PER_OWNER = 2
FEATURED_HEAD_WINDOW = 12
FEATURED_HEAD_MAX = 6
SEARCH_DESCRIPTION_MIN_LENGTH = 3


@dataclass(slots=True)
class FeedCard:
    owner_key: str
    owner_id: int | None
    item_type: str
    kind: str
    created_at: datetime | None
    payload: dict
    final_price: float
    discount: float = 0.0
    random_rank: int = 0
    feature_rank: int = 0
    source: object | None = None

    def as_legacy_tuple(self):
        return (self.payload, self.final_price, self.discount)


def should_use_curated_marketplace_feed(
    *,
    page: int,
    sort: str,
    shop_id: int | None,
) -> bool:
    return (not shop_id) and page <= CURATED_PAGE_LIMIT and sort in ("", "new")


def build_marketplace_feed(
    *,
    page: int,
    per_page: int,
    category_id: int | None = None,
    search_q: str = "",
    kind: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    promo_only: str = "0",
    in_stock: str = "0",
    shop_id: int | None = None,
    candidate_multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER,
    max_fetch: int = DEFAULT_MAX_FETCH,
) -> dict:
    include_locations = (
        not kind
        and not category_id
        and promo_only != "1"
        and in_stock != "1"
    )

    total_products = _count_products(
        search_q=search_q,
        category_id=category_id,
        kind=kind,
        min_price=min_price,
        max_price=max_price,
        promo_only=promo_only,
        in_stock=in_stock,
        shop_id=shop_id,
    )
    total_locations = (
        _count_locations(
            search_q=search_q,
            min_price=min_price,
            max_price=max_price,
            shop_id=shop_id,
        )
        if include_locations
        else 0
    )
    total = int(total_products or 0) + int(total_locations or 0)

    if total <= 0:
        return {
            "data": [],
            "total": 0,
            "per_page": per_page,
        }

    end_index = page * per_page
    product_limit = min(max_fetch, max(per_page * candidate_multiplier, end_index * candidate_multiplier))
    location_limit = min(max_fetch, max(max(6, per_page // 2), end_index * 2))

    rotation_seed = _rotation_seed(page=page, search_q=search_q, kind=kind, category_id=category_id, shop_id=shop_id)

    cards = []
    cards.extend(
        _fetch_product_cards(
            limit=product_limit,
            rotation_seed=rotation_seed,
            search_q=search_q,
            category_id=category_id,
            kind=kind,
            min_price=min_price,
            max_price=max_price,
            promo_only=promo_only,
            in_stock=in_stock,
            shop_id=shop_id,
        )
    )

    if include_locations:
        cards.extend(
            _fetch_location_cards(
                limit=location_limit,
                rotation_seed=rotation_seed,
                search_q=search_q,
                min_price=min_price,
                max_price=max_price,
                shop_id=shop_id,
            )
        )

    ordered_cards = _interleave_cards(cards)
    start_index = max(0, (page - 1) * per_page)
    page_cards = ordered_cards[start_index:start_index + per_page]

    return {
        "data": [card.as_legacy_tuple() for card in page_cards],
        "total": total,
        "per_page": per_page,
    }


def build_location_feed(
    *,
    page: int,
    per_page: int,
    search_q: str = "",
    listing_type: str = "",
    property_type: str = "",
    city_area: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    candidate_multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER,
    max_fetch: int = DEFAULT_MAX_FETCH,
) -> dict:
    total = _count_locations(
        search_q=search_q,
        listing_type=listing_type,
        property_type=property_type,
        city_area=city_area,
        min_price=min_price,
        max_price=max_price,
        shop_id=None,
    )
    if total <= 0:
        return {"items": [], "total": 0, "per_page": per_page}

    end_index = page * per_page
    limit = min(max_fetch, max(per_page * candidate_multiplier, end_index * candidate_multiplier))
    rotation_seed = _rotation_seed(
        page=page,
        search_q=search_q,
        kind="location",
        category_id=None,
        shop_id=None,
    )
    cards = _fetch_location_cards(
        limit=limit,
        rotation_seed=rotation_seed,
        search_q=search_q,
        listing_type=listing_type,
        property_type=property_type,
        city_area=city_area,
        min_price=min_price,
        max_price=max_price,
        shop_id=None,
        include_media=True,
    )
    ordered_cards = _interleave_cards(cards)
    start_index = max(0, (page - 1) * per_page)
    page_cards = ordered_cards[start_index:start_index + per_page]
    return {
        "items": [card.source for card in page_cards if card.source is not None],
        "total": total,
        "per_page": per_page,
    }


def build_standard_marketplace_page(
    *,
    page: int,
    per_page: int,
    category_id: int | None = None,
    search_q: str = "",
    sort: str = "",
    kind: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    promo_only: str = "0",
    in_stock: str = "0",
    shop_id: int | None = None,
) -> dict:
    query, _, final_price_expr, featured_expr, search_rank_expr = _base_product_query(
        search_q=search_q,
        category_id=category_id,
        kind=kind,
        min_price=min_price,
        max_price=max_price,
        promo_only=promo_only,
        in_stock=in_stock,
        shop_id=shop_id,
    )
    ordered_query = _apply_product_sort(
        query,
        sort=sort,
        featured_expr=featured_expr,
        final_price_expr=final_price_expr,
        search_rank_expr=search_rank_expr,
    )
    try:
        pagination = ordered_query.paginate(page=page, per_page=per_page, error_out=False)
    except Exception:
        _safe_session_rollback()
        return {"data": [], "total": 0, "per_page": per_page}

    products = pagination.items
    product_ids = [product.id for product in products]
    promo_map = _promo_map_for_products(product_ids)
    data = [_serialize_product_legacy_tuple(product, promo_map.get(product.id)) for product in products]

    if not kind and page == 1:
        rotation_seed = _rotation_seed(
            page=page,
            search_q=search_q,
            kind=kind,
            category_id=category_id,
            shop_id=shop_id,
        )
        location_cards = _fetch_location_cards(
            limit=max(6, per_page // 3),
            rotation_seed=rotation_seed,
            search_q=search_q,
            min_price=min_price,
            max_price=max_price,
            shop_id=shop_id,
            sort=sort,
        )
        location_entries = [card.as_legacy_tuple() for card in location_cards]
        if location_entries:
            data = _mix_legacy_entries(data, location_entries)[:per_page]

    if sort == "low":
        data.sort(key=lambda item: item[1])
    elif sort == "high":
        data.sort(key=lambda item: item[1], reverse=True)

    return {
        "data": data,
        "total": pagination.total,
        "per_page": per_page,
    }


def search_public_products(*, search_q: str, limit: int) -> list[dict]:
    search_filter, search_rank_expr = _product_search_filter(search_q, include_description=True)
    if search_filter is None:
        return []
    try:
        products = (
            Product.query
            .options(
                selectinload(Product.shop).load_only(Shop.id, Shop.name),
                selectinload(Product.category),
            )
            .filter(Product.is_active == True)
            .filter(search_filter)
            .order_by(search_rank_expr.asc(), Product.created_at.desc(), Product.id.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        _safe_session_rollback()
        return []

    product_ids = [product.id for product in products]
    promo_map = _promo_map_for_products(product_ids)
    return [_serialize_product_search_result(product, promo_map.get(product.id)) for product in products]


def search_public_locations(*, search_q: str, limit: int) -> list[dict]:
    if not (search_q or "").strip():
        return []
    try:
        listings = (
            _public_location_query(
                search_q=search_q,
                min_price=None,
                max_price=None,
                shop_id=None,
            )
            .options(
                selectinload(RentalListing.media),
                selectinload(RentalListing.shop).load_only(Shop.id, Shop.name),
            )
            .order_by(
                _location_search_rank(search_q).asc(),
                RentalListing.created_at.desc(),
                RentalListing.id.desc(),
            )
            .limit(limit)
            .all()
        )
    except Exception:
        _safe_session_rollback()
        return []

    return [_serialize_location_search_result(listing) for listing in listings]


def _rotation_seed(*, page: int, search_q: str, kind: str, category_id: int | None, shop_id: int | None) -> str:
    now = datetime.utcnow()
    slot = (now.hour * 60 + now.minute) // 30
    return f"{now:%Y%m%d}:{slot}:{page}:{search_q}:{kind}:{category_id or 0}:{shop_id or 0}"


def _hash_rank(seed: str, *parts) -> int:
    raw = "|".join(str(part) for part in (seed, *parts))
    return int(hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12], 16)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _safe_session_rollback() -> None:
    try:
        db.session.rollback()
    except Exception:
        pass


def _promo_map_for_products(product_ids: list[int]) -> dict[int, Promo]:
    return get_active_promos_for_products(product_ids)


def _mix_legacy_entries(product_entries: list[tuple], location_entries: list[tuple]) -> list[tuple]:
    mixed: list[tuple] = []
    max_len = max(len(product_entries), len(location_entries))
    for idx in range(max_len):
        if idx < len(product_entries):
            mixed.append(product_entries[idx])
        if idx < len(location_entries):
            mixed.append(location_entries[idx])
    return mixed


def _product_search_filter(search_q: str, *, include_description: bool = False):
    term = (search_q or "").strip()
    if not term:
        return None, None

    exact_name = Product.name.ilike(term)
    prefix_name = Product.name.ilike(f"{term}%")
    contains_name = Product.name.ilike(f"%{term}%")

    clauses = [exact_name, prefix_name, contains_name]
    rank_cases = [
        (exact_name, 0),
        (prefix_name, 1),
    ]

    if include_description and len(term) >= SEARCH_DESCRIPTION_MIN_LENGTH:
        prefix_description = Product.description.ilike(f"{term}%")
        contains_description = Product.description.ilike(f"%{term}%")
        clauses.extend([prefix_description, contains_description])
        rank_cases.extend([
            (prefix_description, 2),
            (contains_name, 3),
            (contains_description, 4),
        ])
    else:
        rank_cases.append((contains_name, 2))

    return or_(*clauses), case(*rank_cases, else_=99)


def _location_search_filter(search_q: str, *, include_description: bool = True):
    term = (search_q or "").strip()
    if not term:
        return None

    clauses = [
        RentalListing.title.ilike(term),
        RentalListing.title.ilike(f"{term}%"),
        RentalListing.city.ilike(f"{term}%"),
        RentalListing.area.ilike(f"{term}%"),
        RentalListing.title.ilike(f"%{term}%"),
        RentalListing.city.ilike(f"%{term}%"),
        RentalListing.area.ilike(f"%{term}%"),
    ]
    if include_description and len(term) >= SEARCH_DESCRIPTION_MIN_LENGTH:
        clauses.append(RentalListing.description.ilike(f"%{term}%"))
    return or_(*clauses)


def _location_search_rank(search_q: str):
    term = (search_q or "").strip()
    if not term:
        return case((RentalListing.id.isnot(None), 0), else_=0)

    exact_title = RentalListing.title.ilike(term)
    prefix_title = RentalListing.title.ilike(f"{term}%")
    prefix_city = RentalListing.city.ilike(f"{term}%")
    prefix_area = RentalListing.area.ilike(f"{term}%")
    contains_title = RentalListing.title.ilike(f"%{term}%")
    contains_city = RentalListing.city.ilike(f"%{term}%")
    contains_area = RentalListing.area.ilike(f"%{term}%")
    contains_description = (
        RentalListing.description.ilike(f"%{term}%")
        if len(term) >= SEARCH_DESCRIPTION_MIN_LENGTH
        else None
    )

    rank_cases = [
        (exact_title, 0),
        (prefix_title, 1),
        (prefix_city, 2),
        (prefix_area, 3),
        (contains_title, 4),
        (contains_city, 5),
        (contains_area, 6),
    ]
    if contains_description is not None:
        rank_cases.append((contains_description, 7))
    return case(*rank_cases, else_=99)


def _apply_product_sort(query, *, sort: str, featured_expr, final_price_expr, search_rank_expr):
    if search_rank_expr is None:
        if sort == "low":
            return query.order_by(featured_expr.desc(), final_price_expr.asc(), Product.created_at.desc(), Product.id.desc())
        if sort == "high":
            return query.order_by(featured_expr.desc(), final_price_expr.desc(), Product.created_at.desc(), Product.id.desc())
        return query.order_by(featured_expr.desc(), Product.created_at.desc(), Product.id.desc())

    if sort == "low":
        return query.order_by(search_rank_expr.asc(), featured_expr.desc(), final_price_expr.asc(), Product.created_at.desc(), Product.id.desc())
    if sort == "high":
        return query.order_by(search_rank_expr.asc(), featured_expr.desc(), final_price_expr.desc(), Product.created_at.desc(), Product.id.desc())
    return query.order_by(search_rank_expr.asc(), featured_expr.desc(), Product.created_at.desc(), Product.id.desc())


def _apply_location_sort(query, *, sort: str, featured_expr, search_rank_expr):
    if search_rank_expr is None:
        if sort == "low":
            return query.order_by(featured_expr.desc(), RentalListing.rent_cents.asc(), RentalListing.created_at.desc(), RentalListing.id.desc())
        if sort == "high":
            return query.order_by(featured_expr.desc(), RentalListing.rent_cents.desc(), RentalListing.created_at.desc(), RentalListing.id.desc())
        return query.order_by(featured_expr.desc(), RentalListing.created_at.desc(), RentalListing.id.desc())

    if sort == "low":
        return query.order_by(search_rank_expr.asc(), featured_expr.desc(), RentalListing.rent_cents.asc(), RentalListing.created_at.desc(), RentalListing.id.desc())
    if sort == "high":
        return query.order_by(search_rank_expr.asc(), featured_expr.desc(), RentalListing.rent_cents.desc(), RentalListing.created_at.desc(), RentalListing.id.desc())
    return query.order_by(search_rank_expr.asc(), featured_expr.desc(), RentalListing.created_at.desc(), RentalListing.id.desc())


def _serialize_product_legacy_tuple(product, promo) -> tuple:
    safe_price = cents_to_money(getattr(product, "price_cents", 0) or 0)
    final_price = cents_to_money(final_price_cents(product, promo))
    discount = _safe_float(getattr(promo, "value", 0), 0.0) if promo and promo.type == "percentage" else 0.0
    product_dict = {
        "id": product.id,
        "name": product.name,
        "price": safe_price,
        "stock": product.stock or 0,
        "kind": (product.kind or "physical"),
        "item_type": "service" if (product.kind or "physical") == "service" else "product",
        "image_file": product.image_file,
        "promo_active": bool(promo),
        "promo_type": (promo.type if promo else ""),
        "promo_value": _safe_float(getattr(promo, "value", 0), 0.0) if promo else 0.0,
        "owner_id": product.vendor_id or getattr(product.shop, "vendor_id", None),
        "shop_id": product.shop_id,
        "created_at": product.created_at,
    }
    return (product_dict, final_price, discount)


def _serialize_product_search_result(product, promo) -> dict:
    kind = (getattr(product, "kind", None) or "physical")
    is_service = kind == "service"
    final_price = cents_to_money(final_price_cents(product, promo))
    image_file = ""
    if getattr(product, "image_file", None):
        image_file = str(product.image_file).split("|")[0]
    return {
        "id": product.id,
        "name": product.name,
        "price": cents_to_money(getattr(product, "price_cents", 0) or 0),
        "final_price": final_price,
        "promo_value": _safe_float(getattr(promo, "value", 0), 0.0) if promo else 0.0,
        "promo_type": promo.type if promo else None,
        "shop_name": product.shop.name if getattr(product, "shop", None) else "N/A",
        "category": product.category.name if getattr(product, "category", None) else "",
        "stock": product.stock if hasattr(product, "stock") else None,
        "url": f"/shop/product/{product.id}",
        "image_file": image_file,
        "kind": kind,
        "can_add_to_cart": not is_service,
        "booking_url": f"/booking/{product.id}" if is_service else None,
        "default_quantity": 1,
    }


def _serialize_location_search_result(listing) -> dict:
    cover = ""
    if getattr(listing, "media", None):
        for media in listing.media:
            if media.kind == "image" and media.file_path:
                cover = media.file_path
                break
    cover_url = ""
    if cover:
        normalized_cover = str(cover).replace("\\", "/").lstrip("/")
        if normalized_cover.startswith(("http://", "https://")):
            cover_url = normalized_cover
        elif normalized_cover.startswith("static/"):
            cover_url = f"/{normalized_cover}"
        elif normalized_cover.startswith("uploads/"):
            cover_url = f"/static/{normalized_cover}"
        else:
            cover_url = f"/static/uploads/rentals/{normalized_cover}"

    return {
        "id": listing.id,
        "title": listing.title,
        "city": listing.city,
        "area": listing.area or "",
        "rent_cents": int(listing.rent_cents or 0),
        "rent_dh": round((listing.rent_cents or 0) / 100, 2),
        "listing_type": listing.listing_type,
        "url": f"/location/{listing.slug}",
        "shop_name": listing.shop.name if getattr(listing, "shop", None) else "",
        "cover": cover,
        "cover_url": cover_url,
    }


def _base_product_query(*, search_q: str, category_id: int | None, kind: str, min_price: float | None, max_price: float | None, promo_only: str, in_stock: str, shop_id: int | None):
    now = datetime.utcnow()

    promo_value_sq = (
        db.session.query(Promo.value)
        .filter(
            Promo.product_id == Product.id,
            Promo.end_date >= now,
            Promo.status == Promo.STATUS_APPROVED,
        )
        .order_by(Promo.end_date.asc())
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    promo_type_sq = (
        db.session.query(Promo.type)
        .filter(
            Promo.product_id == Product.id,
            Promo.end_date >= now,
            Promo.status == Promo.STATUS_APPROVED,
        )
        .order_by(Promo.end_date.asc())
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    promo_exists_sq = (
        db.session.query(Promo.id)
        .filter(
            Promo.product_id == Product.id,
            Promo.end_date >= now,
            Promo.status == Promo.STATUS_APPROVED,
        )
        .exists()
    )

    promo_value = db.func.coalesce(promo_value_sq, 0.0)
    promo_value_cents = db.cast(db.func.round(promo_value * 100.0), db.Integer)
    base_price_cents_expr = db.func.coalesce(Product.price_cents_value, 0)
    fixed_price_expr = case(
        ((base_price_cents_expr - promo_value_cents) > 0, base_price_cents_expr - promo_value_cents),
        else_=0,
    )
    final_price_cents_expr = case(
        (promo_type_sq == "percentage", db.cast(db.func.round(base_price_cents_expr - (base_price_cents_expr * promo_value / 100.0)), db.Integer)),
        (promo_type_sq == "fixed", fixed_price_expr),
        else_=base_price_cents_expr,
    )

    query = (
        Product.query
        .outerjoin(Shop, Shop.id == Product.shop_id)
        .options(selectinload(Product.shop).load_only(Shop.id, Shop.vendor_id, Shop.is_active))
        .filter(Product.is_active == True)
        .filter(or_(Product.shop_id.is_(None), Shop.is_active == True))
    )
    featured_expr = featured_rank_expr(product_featured_exists_expr(Product.id, Product.shop_id, now))
    search_filter, search_rank_expr = _product_search_filter(search_q, include_description=False)

    if search_filter is not None:
        query = query.filter(search_filter)
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if shop_id:
        query = query.filter(Product.shop_id == shop_id)
    if kind:
        query = query.filter(Product.kind == kind)
    if in_stock == "1":
        query = query.filter((Product.kind == "service") | (Product.stock > 0))
    if promo_only == "1":
        query = query.filter(promo_exists_sq)
    if min_price is not None:
        query = query.filter(final_price_cents_expr >= dh_to_cents(min_price))
    if max_price is not None:
        query = query.filter(final_price_cents_expr <= dh_to_cents(max_price))

    return query, promo_exists_sq, final_price_cents_expr, featured_expr, search_rank_expr


def _count_products(**kwargs) -> int:
    query, _, _, _, _ = _base_product_query(**kwargs)
    try:
        base_rows = (
            query.enable_eagerloads(False)
            .order_by(None)
            .with_entities(Product.id.label("id"))
            .subquery()
        )
        return int(db.session.query(db.func.count()).select_from(base_rows).scalar() or 0)
    except Exception:
        _safe_session_rollback()
        return 0


def _fetch_product_cards(
    *,
    limit: int,
    rotation_seed: str,
    search_q: str,
    sort: str = "",
    category_id: int | None,
    kind: str,
    min_price: float | None,
    max_price: float | None,
    promo_only: str,
    in_stock: str,
    shop_id: int | None,
) -> list[FeedCard]:
    query, _, final_price_expr, featured_expr, search_rank_expr = _base_product_query(
        search_q=search_q,
        category_id=category_id,
        kind=kind,
        min_price=min_price,
        max_price=max_price,
        promo_only=promo_only,
        in_stock=in_stock,
        shop_id=shop_id,
    )
    try:
        products = (
            _apply_product_sort(
                query,
                sort=sort,
                featured_expr=featured_expr,
                final_price_expr=final_price_expr,
                search_rank_expr=search_rank_expr,
            )
            .limit(limit)
            .all()
        )
    except Exception:
        _safe_session_rollback()
        return []

    product_ids = [product.id for product in products]
    promo_map = _promo_map_for_products(product_ids)

    now = datetime.utcnow()
    featured_product_ids: set[int] = set()
    featured_shop_ids: set[int] = set()
    if product_ids:
        try:
            featured_rows = (
                FeaturedItem.query
                .with_entities(FeaturedItem.target_type, FeaturedItem.product_id, FeaturedItem.shop_id)
                .filter(
                    FeaturedItem.is_active.is_(True),
                    FeaturedItem.starts_at <= now,
                    FeaturedItem.ends_at >= now,
                    or_(
                        and_(
                            FeaturedItem.target_type == FeaturedItem.TARGET_PRODUCT,
                            FeaturedItem.product_id.in_(product_ids),
                        ),
                        and_(
                            FeaturedItem.target_type == FeaturedItem.TARGET_SHOP,
                            FeaturedItem.shop_id.in_([p.shop_id for p in products if p.shop_id]),
                        ),
                    ),
                )
                .all()
            )
        except Exception:
            _safe_session_rollback()
            featured_rows = []
        for target_type, product_id, featured_shop_id in featured_rows:
            if target_type == FeaturedItem.TARGET_PRODUCT and product_id:
                featured_product_ids.add(int(product_id))
            elif target_type == FeaturedItem.TARGET_SHOP and featured_shop_id:
                featured_shop_ids.add(int(featured_shop_id))

    cards: list[FeedCard] = []
    for product in products:
        try:
            promo = promo_map.get(product.id)
            payload, final_price, discount = _serialize_product_legacy_tuple(product, promo)
            item_type = payload.get("item_type", "product")
            owner_id = payload.get("owner_id")
            cards.append(
                FeedCard(
                    owner_key=_owner_key(owner_id=owner_id, shop_id=product.shop_id, fallback_id=product.id),
                    owner_id=owner_id,
                    item_type=item_type,
                    kind=payload["kind"],
                    created_at=product.created_at,
                    payload=payload,
                    final_price=final_price,
                    discount=discount,
                    random_rank=_hash_rank(rotation_seed, item_type, product.id),
                    feature_rank=1 if (product.id in featured_product_ids or (product.shop_id in featured_shop_ids if product.shop_id else False)) else 0,
                )
            )
        except Exception:
            continue
    return cards


def _public_location_query(
    *,
    search_q: str,
    listing_type: str = "",
    property_type: str = "",
    city_area: str = "",
    min_price: float | None,
    max_price: float | None,
    shop_id: int | None,
):
    now = datetime.utcnow()
    query = (
        RentalListing.query
        .join(Shop, Shop.id == RentalListing.shop_id)
        .filter(
            RentalListing.is_active == True,
            RentalListing.status.in_(["active", "reserved"]),
            RentalListing.expires_at > now,
            Shop.is_active == True,
            Shop.sql_allows_clause("location"),
        )
    )

    search_filter = _location_search_filter(search_q, include_description=True)
    if search_filter is not None:
        query = query.filter(search_filter)
    if listing_type:
        query = query.filter(RentalListing.listing_type == listing_type)
    if property_type:
        query = query.filter(RentalListing.property_type == property_type)
    if city_area:
        like_city = f"%{city_area}%"
        query = query.filter(
            (RentalListing.city.ilike(like_city))
            | (RentalListing.area.ilike(like_city))
        )
    if shop_id:
        query = query.filter(RentalListing.shop_id == shop_id)
    if min_price is not None:
        query = query.filter(RentalListing.rent_cents >= dh_to_cents(min_price))
    if max_price is not None:
        query = query.filter(RentalListing.rent_cents <= dh_to_cents(max_price))

    return query


def _count_locations(**kwargs) -> int:
    try:
        base_rows = (
            _public_location_query(**kwargs)
            .enable_eagerloads(False)
            .order_by(None)
            .with_entities(RentalListing.id.label("id"))
            .subquery()
        )
        return int(db.session.query(db.func.count()).select_from(base_rows).scalar() or 0)
    except Exception:
        _safe_session_rollback()
        return 0


def _fetch_location_cards(
    *,
    limit: int,
    rotation_seed: str,
    search_q: str,
    sort: str = "",
    listing_type: str = "",
    property_type: str = "",
    city_area: str = "",
    min_price: float | None,
    max_price: float | None,
    shop_id: int | None,
    include_media: bool = False,
) -> list[FeedCard]:
    query = _public_location_query(
        search_q=search_q,
        listing_type=listing_type,
        property_type=property_type,
        city_area=city_area,
        min_price=min_price,
        max_price=max_price,
        shop_id=shop_id,
    )
    if include_media:
        query = query.options(
            selectinload(RentalListing.media).load_only(
                RentalMedia.id,
                RentalMedia.kind,
                RentalMedia.file_path,
                RentalMedia.listing_id,
            )
        )
    featured_expr = featured_rank_expr(
        location_featured_exists_expr(RentalListing.id, RentalListing.shop_id, datetime.utcnow())
    )
    listings = (
        _apply_location_sort(
            query,
            sort=sort,
            featured_expr=featured_expr,
            search_rank_expr=_location_search_rank(search_q) if (search_q or "").strip() else None,
        )
        .limit(limit)
        .all()
    )

    listing_ids = [listing.id for listing in listings]
    cover_map: dict[int, str] = {}
    cover_video_map: dict[int, str] = {}
    cover_video_poster_map: dict[int, str] = {}
    if listing_ids:
        media_rows = (
            db.session.query(RentalMedia.listing_id, RentalMedia.kind, RentalMedia.file_path)
            .filter(
                RentalMedia.listing_id.in_(listing_ids),
                RentalMedia.kind.in_(("image", "video")),
            )
            .order_by(RentalMedia.listing_id.asc(), RentalMedia.id.asc())
            .all()
        )
        for listing_id, media_kind, file_path in media_rows:
            if not file_path:
                continue
            if media_kind == "image" and listing_id not in cover_map:
                cover_map[listing_id] = str(file_path)
            elif media_kind == "video" and listing_id not in cover_video_map:
                cover_video_map[listing_id] = str(file_path)
                poster_rel = rental_existing_video_poster_rel_path(str(file_path))
                if poster_rel:
                    cover_video_poster_map[listing_id] = poster_rel

    now = datetime.utcnow()
    featured_location_ids: set[int] = set()
    featured_shop_ids: set[int] = set()
    if listing_ids:
        featured_rows = (
            FeaturedItem.query
            .with_entities(FeaturedItem.target_type, FeaturedItem.location_id, FeaturedItem.shop_id)
            .filter(
                FeaturedItem.is_active.is_(True),
                FeaturedItem.starts_at <= now,
                FeaturedItem.ends_at >= now,
                or_(
                    and_(
                        FeaturedItem.target_type == FeaturedItem.TARGET_LOCATION,
                        FeaturedItem.location_id.in_(listing_ids),
                    ),
                    and_(
                        FeaturedItem.target_type == FeaturedItem.TARGET_SHOP,
                        FeaturedItem.shop_id.in_([listing.shop_id for listing in listings if listing.shop_id]),
                    ),
                ),
            )
            .all()
        )
        for target_type, location_id, featured_shop_id in featured_rows:
            if target_type == FeaturedItem.TARGET_LOCATION and location_id:
                featured_location_ids.add(int(location_id))
            elif target_type == FeaturedItem.TARGET_SHOP and featured_shop_id:
                featured_shop_ids.add(int(featured_shop_id))

    cards: list[FeedCard] = []
    for listing in listings:
        final_price = float((listing.rent_cents or 0) / 100)
        payload = {
            "id": listing.id,
            "slug": listing.slug,
            "name": listing.title,
            "price": final_price,
            "stock": None,
            "kind": "location",
            "item_type": "location",
            "image_file": cover_map.get(listing.id, ""),
            "cover_video_file": cover_video_map.get(listing.id, ""),
            "cover_video_poster_file": cover_video_poster_map.get(listing.id, ""),
            "city": listing.city,
            "area": listing.area,
            "listing_type": listing.listing_type,
            "owner_id": listing.owner_id,
            "shop_id": listing.shop_id,
            "created_at": listing.created_at,
        }
        cards.append(
            FeedCard(
                owner_key=_owner_key(owner_id=listing.owner_id, shop_id=listing.shop_id, fallback_id=listing.id),
                owner_id=listing.owner_id,
                item_type="location",
                kind="location",
                created_at=listing.created_at,
                payload=payload,
                final_price=final_price,
                random_rank=_hash_rank(rotation_seed, "location", listing.id),
                feature_rank=1 if (listing.id in featured_location_ids or (listing.shop_id in featured_shop_ids if listing.shop_id else False)) else 0,
                source=listing,
            )
        )
    return cards


def _owner_key(*, owner_id: int | None, shop_id: int | None, fallback_id: int) -> str:
    if owner_id:
        return f"owner:{owner_id}"
    if shop_id:
        return f"shop:{shop_id}"
    return f"item:{fallback_id}"


def _freshness_rank(value: datetime | None) -> float:
    if not value:
        return 0.0
    return value.timestamp()


def _rotation_priority(card: FeedCard) -> int:
    return card.random_rank if card.feature_rank else 0


def _pick_group_item(queue: list[FeedCard], *, last_type: str | None, type_counts: dict[str, int]) -> tuple[int, FeedCard]:
    inspect_count = min(3, len(queue))
    best_idx = 0
    best_card = queue[0]
    best_key = None
    for idx in range(inspect_count):
        card = queue[idx]
        key = (
            -card.feature_rank,
            type_counts[card.item_type],
            1 if last_type and card.item_type == last_type else 0,
            _rotation_priority(card),
            -_freshness_rank(card.created_at),
            card.random_rank if not card.feature_rank else 0,
        )
        if best_key is None or key < best_key:
            best_key = key
            best_idx = idx
            best_card = card
    return best_idx, best_card


def _interleave_cards(cards: list[FeedCard]) -> list[FeedCard]:
    if not cards:
        return []

    groups: dict[str, list[FeedCard]] = defaultdict(list)
    for card in cards:
        groups[card.owner_key].append(card)

    for queue in groups.values():
        queue.sort(key=lambda card: (-_freshness_rank(card.created_at), card.random_rank))

    owner_counts: dict[str, int] = defaultdict(int)
    type_counts: dict[str, int] = defaultdict(int)
    featured_count = 0
    result: list[FeedCard] = []
    last_owner: str | None = None
    last_type: str | None = None

    while True:
        candidates = _build_candidates(
            groups=groups,
            owner_counts=owner_counts,
            type_counts=type_counts,
            featured_count=featured_count,
            result_len=len(result),
            last_owner=last_owner,
            last_type=last_type,
            enforce_owner_cap=len(result) < ANTI_MONOPOLY_WINDOW,
            enforce_featured_quota=len(result) < FEATURED_HEAD_WINDOW,
        )
        if not candidates:
            break

        _, owner_key, card_idx, card = min(candidates, key=lambda row: row[0])
        groups[owner_key].pop(card_idx)
        if not groups[owner_key]:
            groups.pop(owner_key, None)

        result.append(card)
        owner_counts[owner_key] += 1
        type_counts[card.item_type] += 1
        if card.feature_rank:
            featured_count += 1
        last_owner = owner_key
        last_type = card.item_type

    return result


def _build_candidates(
    *,
    groups: dict[str, list[FeedCard]],
    owner_counts: dict[str, int],
    type_counts: dict[str, int],
    featured_count: int,
    result_len: int,
    last_owner: str | None,
    last_type: str | None,
    enforce_owner_cap: bool,
    enforce_featured_quota: bool,
):
    candidates = []
    fallback_candidates = []
    for owner_key, queue in groups.items():
        if not queue:
            continue
        if enforce_owner_cap and owner_counts[owner_key] >= ANTI_MONOPOLY_MAX_PER_OWNER:
            continue
        card_idx, card = _pick_group_item(queue, last_type=last_type, type_counts=type_counts)
        if enforce_featured_quota and card.feature_rank and featured_count >= FEATURED_HEAD_MAX:
            fallback_candidates.append((owner_key, card_idx, card))
            continue
        score = (
            -card.feature_rank,
            owner_counts[owner_key],
            1 if last_owner and owner_key == last_owner else 0,
            type_counts[card.item_type],
            1 if last_type and card.item_type == last_type else 0,
            _rotation_priority(card),
            -_freshness_rank(card.created_at),
            card.random_rank if not card.feature_rank else 0,
        )
        candidates.append((score, owner_key, card_idx, card))

    if fallback_candidates and enforce_featured_quota:
        return _build_candidates(
            groups=groups,
            owner_counts=owner_counts,
            type_counts=type_counts,
            featured_count=featured_count,
            result_len=result_len,
            last_owner=last_owner,
            last_type=last_type,
            enforce_owner_cap=enforce_owner_cap,
            enforce_featured_quota=False,
        )

    if candidates or not enforce_owner_cap:
        return candidates

    return _build_candidates(
        groups=groups,
        owner_counts=owner_counts,
        type_counts=type_counts,
        featured_count=featured_count,
        result_len=result_len,
        last_owner=last_owner,
        last_type=last_type,
        enforce_owner_cap=False,
        enforce_featured_quota=enforce_featured_quota,
    )
