from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, case, or_

from ..extensions import db
from ..models.featured_item import FeaturedItem


FEATURED_DURATION_OPTIONS = (
    (7, "7 jours"),
    (15, "15 jours"),
    (30, "30 jours"),
    (90, "90 jours"),
)


def featured_duration_choices() -> tuple[tuple[int, str], ...]:
    return FEATURED_DURATION_OPTIONS


def normalize_featured_duration(raw_value, default: int = 30) -> int:
    try:
        days = int(raw_value)
    except (TypeError, ValueError):
        days = default
    allowed = {choice[0] for choice in FEATURED_DURATION_OPTIONS}
    return days if days in allowed else default


def featured_window_filters(now: datetime | None = None) -> list:
    current_time = now or datetime.utcnow()
    return [
        FeaturedItem.is_active.is_(True),
        FeaturedItem.starts_at <= current_time,
        FeaturedItem.ends_at >= current_time,
    ]


def shop_featured_exists_expr(shop_id_column, now: datetime | None = None):
    return (
        db.session.query(FeaturedItem.id)
        .filter(*featured_window_filters(now))
        .filter(
            FeaturedItem.target_type == FeaturedItem.TARGET_SHOP,
            FeaturedItem.shop_id == shop_id_column,
        )
        .exists()
    )


def product_featured_exists_expr(product_id_column, shop_id_column, now: datetime | None = None):
    return (
        db.session.query(FeaturedItem.id)
        .filter(*featured_window_filters(now))
        .filter(
            or_(
                and_(
                    FeaturedItem.target_type == FeaturedItem.TARGET_PRODUCT,
                    FeaturedItem.product_id == product_id_column,
                ),
                and_(
                    FeaturedItem.target_type == FeaturedItem.TARGET_SHOP,
                    FeaturedItem.shop_id == shop_id_column,
                ),
            )
        )
        .exists()
    )


def location_featured_exists_expr(location_id_column, shop_id_column, now: datetime | None = None):
    return (
        db.session.query(FeaturedItem.id)
        .filter(*featured_window_filters(now))
        .filter(
            or_(
                and_(
                    FeaturedItem.target_type == FeaturedItem.TARGET_LOCATION,
                    FeaturedItem.location_id == location_id_column,
                ),
                and_(
                    FeaturedItem.target_type == FeaturedItem.TARGET_SHOP,
                    FeaturedItem.shop_id == shop_id_column,
                ),
            )
        )
        .exists()
    )


def featured_rank_expr(exists_expr):
    return case((exists_expr, 1), else_=0)


def active_featured_shop_notice(shop_id: int | None, now: datetime | None = None) -> FeaturedItem | None:
    if not shop_id:
        return None
    current_time = now or datetime.utcnow()
    return (
        FeaturedItem.query
        .filter(
            FeaturedItem.target_type == FeaturedItem.TARGET_SHOP,
            FeaturedItem.shop_id == shop_id,
            FeaturedItem.is_active.is_(True),
            FeaturedItem.starts_at <= current_time,
            FeaturedItem.ends_at >= current_time,
        )
        .order_by(FeaturedItem.ends_at.desc(), FeaturedItem.id.desc())
        .first()
    )


def upsert_featured_item(
    *,
    target_type: str,
    target_id: int,
    vendor_id: int | None,
    created_by_admin_id: int | None,
    duration_days: int,
    note: str = "",
    now: datetime | None = None,
) -> FeaturedItem:
    current_time = now or datetime.utcnow()
    normalized_type = (target_type or "").strip().lower()
    if normalized_type not in FeaturedItem.TARGET_TYPES:
        raise ValueError("invalid_target_type")

    duration = normalize_featured_duration(duration_days)
    starts_at = current_time
    ends_at = current_time + timedelta(days=duration)

    existing_query = FeaturedItem.query.filter(FeaturedItem.target_type == normalized_type)
    if normalized_type == FeaturedItem.TARGET_SHOP:
        existing_query = existing_query.filter(FeaturedItem.shop_id == target_id)
    elif normalized_type == FeaturedItem.TARGET_PRODUCT:
        existing_query = existing_query.filter(FeaturedItem.product_id == target_id)
    else:
        existing_query = existing_query.filter(FeaturedItem.location_id == target_id)

    existing_rows = existing_query.all()
    for row in existing_rows:
        row.is_active = False
        row.updated_at = current_time

    item = FeaturedItem(
        target_type=normalized_type,
        vendor_id=vendor_id,
        created_by_admin_id=created_by_admin_id,
        note=(note or "").strip()[:255] or None,
        starts_at=starts_at,
        ends_at=ends_at,
        is_active=True,
    )
    if normalized_type == FeaturedItem.TARGET_SHOP:
        item.shop_id = target_id
    elif normalized_type == FeaturedItem.TARGET_PRODUCT:
        item.product_id = target_id
    else:
        item.location_id = target_id

    db.session.add(item)
    return item


def disable_featured_item(item: FeaturedItem, *, now: datetime | None = None) -> FeaturedItem:
    current_time = now or datetime.utcnow()
    item.is_active = False
    if item.ends_at > current_time:
        item.ends_at = current_time
    item.updated_at = current_time
    return item
