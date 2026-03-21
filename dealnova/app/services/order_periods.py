from __future__ import annotations

from datetime import datetime, timedelta

from ..extensions import db
from ..models.order_period import OrderPeriod

OPEN_STATUS = "open"
CLOSED_STATUS = "closed"
ORDER_DELETE_RETENTION_DAYS = 40


def _normalized_name(raw_name: str | None) -> str:
    value = str(raw_name or "").strip()
    return value[:120] if value else ""


def _auto_period_name(now: datetime) -> str:
    return f"Auto {now.strftime('%Y-%m-%d %H:%M')}"


def get_open_order_period() -> OrderPeriod | None:
    return (
        OrderPeriod.query
        .filter(OrderPeriod.status == OPEN_STATUS)
        .order_by(OrderPeriod.opened_at.desc(), OrderPeriod.id.desc())
        .first()
    )


def create_order_period(name: str | None, created_by: int | None = None, opened_at: datetime | None = None) -> OrderPeriod:
    existing_open = get_open_order_period()
    if existing_open is not None:
        raise ValueError(f"Une periode est deja ouverte (#{existing_open.id}).")

    now = opened_at or datetime.utcnow()
    period = OrderPeriod(
        name=_normalized_name(name) or f"Periode {now.strftime('%d/%m/%Y %H:%M')}",
        status=OPEN_STATUS,
        opened_at=now,
        created_by=created_by,
    )
    db.session.add(period)
    db.session.flush()
    return period


def get_or_create_open_order_period(created_by: int | None = None, now: datetime | None = None) -> tuple[OrderPeriod, bool]:
    open_period = get_open_order_period()
    if open_period is not None:
        return open_period, False

    current_time = now or datetime.utcnow()
    auto_period = OrderPeriod(
        name=_auto_period_name(current_time),
        status=OPEN_STATUS,
        opened_at=current_time,
        created_by=created_by,
    )
    db.session.add(auto_period)
    db.session.flush()
    return auto_period, True


def close_order_period(period: OrderPeriod, closed_at: datetime | None = None) -> OrderPeriod:
    if period is None:
        raise ValueError("Periode introuvable.")
    if period.status == CLOSED_STATUS:
        return period

    period.status = CLOSED_STATUS
    period.closed_at = closed_at or datetime.utcnow()
    db.session.flush()
    return period


def period_bounds(period: OrderPeriod | None, *, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    if period is None:
        return None, None
    start_at = getattr(period, "opened_at", None)
    end_at = getattr(period, "closed_at", None)
    if end_at is None and getattr(period, "status", "") == OPEN_STATUS:
        end_at = now or datetime.utcnow()
    return start_at, end_at


def delete_available_at_for_period(period: OrderPeriod | None) -> datetime | None:
    if period is None:
        return None
    if period.status != CLOSED_STATUS:
        return None
    if period.closed_at is None:
        return None
    return period.closed_at + timedelta(days=ORDER_DELETE_RETENTION_DAYS)


def order_delete_guard(order, now: datetime | None = None) -> tuple[bool, str, datetime | None]:
    reference_time = now or datetime.utcnow()
    period = getattr(order, "period", None)
    if period is None:
        return False, "Aucune periode liee a cette commande.", None
    if period.status != CLOSED_STATUS:
        return False, "Suppression autorisee uniquement pour une periode fermee.", None

    allowed_at = delete_available_at_for_period(period)
    if allowed_at is None:
        return False, "Date de fermeture de periode indisponible.", None
    if reference_time < allowed_at:
        return False, f"Suppression possible a partir du {allowed_at.strftime('%d/%m/%Y %H:%M')}.", allowed_at
    return True, "", allowed_at

