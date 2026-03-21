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
from .pricing import prix_final
from .rentals import rental_existing_video_poster_rel_path


CURATED_PAGE_LIMIT = 5
DEFAULT_CANDIDATE_MULTIPLIER = 4
DEFAULT_MAX_FETCH = 240
ANTI_MONOPOLY_WINDOW = 20
ANTI_MONOPOLY_MAX_PER_OWNER = 2
FEATURED_HEAD_WINDOW = 12
FEATURED_HEAD_MAX = 6


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


def _base_product_query(*, search_q: str, category_id: int | None, kind: str, min_price: float | None, max_price: float | None, promo_only: str, in_stock: str, shop_id: int | None):
    now = datetime.utcnow()

    promo_value_sq = (
        db.session.query(Promo.value)
        .filter(
            Promo.product_id == Product.id,
            Promo.end_date >= now,
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
        )
        .exists()
    )

    promo_value = db.func.coalesce(promo_value_sq, 0.0)
    fixed_price_expr = case(
        ((Product.price - promo_value) > 0, Product.price - promo_value),
        else_=0.0,
    )
    final_price_expr = case(
        (promo_type_sq == "percentage", Product.price - (Product.price * promo_value / 100.0)),
        (promo_type_sq == "fixed", fixed_price_expr),
        else_=Product.price,
    )

    query = (
        Product.query
        .outerjoin(Shop, Shop.id == Product.shop_id)
        .options(selectinload(Product.shop).load_only(Shop.id, Shop.vendor_id, Shop.is_active))
        .filter(Product.is_active == True)
        .filter(or_(Product.shop_id.is_(None), Shop.is_active == True))
    )
    featured_expr = featured_rank_expr(product_featured_exists_expr(Product.id, Product.shop_id, now))

    if search_q:
        query = query.filter(Product.name.ilike(f"%{search_q}%"))
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
        query = query.filter(final_price_expr >= min_price)
    if max_price is not None:
        query = query.filter(final_price_expr <= max_price)

    return query, promo_exists_sq, final_price_expr, featured_expr


def _count_products(**kwargs) -> int:
    query, _, _, _ = _base_product_query(**kwargs)
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
    category_id: int | None,
    kind: str,
    min_price: float | None,
    max_price: float | None,
    promo_only: str,
    in_stock: str,
    shop_id: int | None,
) -> list[FeedCard]:
    query, _, _, featured_expr = _base_product_query(
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
            query.order_by(featured_expr.desc(), Product.created_at.desc(), Product.id.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        _safe_session_rollback()
        return []

    product_ids = [product.id for product in products]
    if product_ids:
        try:
            promos = (
                Promo.query
                .filter(
                    Promo.product_id.in_(product_ids),
                    Promo.end_date >= datetime.utcnow(),
                )
                .order_by(Promo.product_id.asc(), Promo.end_date.asc())
                .all()
            )
        except Exception:
            _safe_session_rollback()
            promos = []
    else:
        promos = []
    promo_map = {}
    for promo in promos:
        promo_map.setdefault(promo.product_id, promo)

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
            safe_price = _safe_float(getattr(product, "price", 0), 0.0)
            final_price = _safe_float(prix_final(product, promo), safe_price)
            discount = _safe_float(getattr(promo, "value", 0), 0.0) if promo and promo.type == "percentage" else 0.0
            item_type = "service" if product.kind == "service" else "product"
            owner_id = product.vendor_id or getattr(product.shop, "vendor_id", None)
            payload = {
                "id": product.id,
                "name": product.name,
                "price": safe_price,
                "stock": product.stock or 0,
                "kind": product.kind or "physical",
                "item_type": item_type,
                "image_file": product.image_file,
                "owner_id": owner_id,
                "shop_id": product.shop_id,
                "created_at": product.created_at,
                "promo_active": bool(promo),
                "promo_type": (promo.type if promo else ""),
                "promo_value": _safe_float(getattr(promo, "value", 0), 0.0) if promo else 0.0,
            }
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

    if search_q:
        like = f"%{search_q}%"
        query = query.filter(
            (RentalListing.title.ilike(like))
            | (RentalListing.city.ilike(like))
            | (RentalListing.area.ilike(like))
            | (RentalListing.description.ilike(like))
        )
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
        query = query.filter(RentalListing.rent_cents >= int(round(min_price * 100)))
    if max_price is not None:
        query = query.filter(RentalListing.rent_cents <= int(round(max_price * 100)))

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
        query.order_by(featured_expr.desc(), RentalListing.created_at.desc(), RentalListing.id.desc())
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
