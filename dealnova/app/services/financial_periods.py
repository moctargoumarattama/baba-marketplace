from __future__ import annotations

from datetime import date, datetime, timedelta

from ..extensions import db
from ..models.financial import FinancialEntry, FinancialPeriod

ENTRY_TYPE_DELIVERY_FEE = "delivery_fee"
ENTRY_TYPE_SUBSCRIPTION = "subscription"
ENTRY_TYPE_RENTAL_COMMISSION = "rental_commission"

FINANCIAL_PERIOD_OPEN = "open"
FINANCIAL_PERIOD_CLOSED = "closed"
FINANCIAL_PERIOD_DELETE_RETENTION_DAYS = 365


def get_open_financial_period() -> FinancialPeriod | None:
    return (
        FinancialPeriod.query
        .filter(
            FinancialPeriod.status == FINANCIAL_PERIOD_OPEN,
            FinancialPeriod.deleted_at.is_(None),
        )
        .order_by(FinancialPeriod.start_date.desc(), FinancialPeriod.id.desc())
        .first()
    )


def create_financial_period(
    *,
    name: str | None,
    start_date: date,
    end_date: date,
) -> FinancialPeriod:
    if start_date is None or end_date is None:
        raise ValueError("Dates de periode invalides.")
    if end_date < start_date:
        raise ValueError("La date de fin doit etre superieure ou egale a la date de debut.")

    existing_open = get_open_financial_period()
    if existing_open is not None:
        raise ValueError(f"Une periode financiere est deja ouverte (#{existing_open.id}).")

    normalized_name = (name or "").strip()
    period = FinancialPeriod(
        name=normalized_name[:120] if normalized_name else f"Periode {start_date.isoformat()} -> {end_date.isoformat()}",
        start_date=start_date,
        end_date=end_date,
        status=FINANCIAL_PERIOD_OPEN,
    )
    db.session.add(period)
    db.session.flush()
    return period


def compute_period_totals(period_id: int) -> dict[str, int]:
    rows = (
        db.session.query(
            FinancialEntry.entry_type,
            db.func.coalesce(db.func.sum(FinancialEntry.amount_cents), 0).label("amount"),
            db.func.count(FinancialEntry.id).label("count"),
        )
        .filter(
            FinancialEntry.period_id == period_id,
            FinancialEntry.deleted_at.is_(None),
        )
        .group_by(FinancialEntry.entry_type)
        .all()
    )

    totals = {
        ENTRY_TYPE_DELIVERY_FEE: 0,
        ENTRY_TYPE_SUBSCRIPTION: 0,
        ENTRY_TYPE_RENTAL_COMMISSION: 0,
    }
    counts = {
        ENTRY_TYPE_DELIVERY_FEE: 0,
        ENTRY_TYPE_SUBSCRIPTION: 0,
        ENTRY_TYPE_RENTAL_COMMISSION: 0,
    }

    for row in rows:
        entry_type = str(row.entry_type or "")
        if entry_type not in totals:
            continue
        totals[entry_type] = int(row.amount or 0)
        counts[entry_type] = int(row.count or 0)

    total_cents = int(
        totals[ENTRY_TYPE_DELIVERY_FEE]
        + totals[ENTRY_TYPE_SUBSCRIPTION]
        + totals[ENTRY_TYPE_RENTAL_COMMISSION]
    )
    entry_count = int(
        counts[ENTRY_TYPE_DELIVERY_FEE]
        + counts[ENTRY_TYPE_SUBSCRIPTION]
        + counts[ENTRY_TYPE_RENTAL_COMMISSION]
    )

    return {
        "delivery_total_cents": totals[ENTRY_TYPE_DELIVERY_FEE],
        "subscription_total_cents": totals[ENTRY_TYPE_SUBSCRIPTION],
        "rental_total_cents": totals[ENTRY_TYPE_RENTAL_COMMISSION],
        "total_cents": total_cents,
        "delivery_count": counts[ENTRY_TYPE_DELIVERY_FEE],
        "subscription_count": counts[ENTRY_TYPE_SUBSCRIPTION],
        "rental_count": counts[ENTRY_TYPE_RENTAL_COMMISSION],
        "entry_count": entry_count,
    }


def close_financial_period(period: FinancialPeriod, *, closed_at: datetime | None = None) -> FinancialPeriod:
    if period is None:
        raise ValueError("Periode financiere introuvable.")

    if period.status == FINANCIAL_PERIOD_CLOSED:
        return period

    period.status = FINANCIAL_PERIOD_CLOSED
    period.closed_at = closed_at or datetime.utcnow()

    totals = compute_period_totals(period.id)
    period.delivery_total_cents = totals["delivery_total_cents"]
    period.subscription_total_cents = totals["subscription_total_cents"]
    period.rental_total_cents = totals["rental_total_cents"]
    period.total_cents = totals["total_cents"]

    db.session.flush()
    return period


def financial_period_delete_available_at(period: FinancialPeriod | None) -> datetime | None:
    if period is None:
        return None
    if period.status != FINANCIAL_PERIOD_CLOSED:
        return None
    if period.closed_at is None:
        return None
    return period.closed_at + timedelta(days=FINANCIAL_PERIOD_DELETE_RETENTION_DAYS)


def financial_period_delete_guard(
    period: FinancialPeriod,
    *,
    now: datetime | None = None,
) -> tuple[bool, str, datetime | None]:
    if period is None:
        return False, "Periode introuvable.", None
    if period.status != FINANCIAL_PERIOD_CLOSED:
        return False, "Suppression autorisee uniquement pour une periode fermee.", None

    available_at = financial_period_delete_available_at(period)
    if available_at is None:
        return False, "Date de fermeture indisponible.", None

    reference = now or datetime.utcnow()
    if reference < available_at:
        return (
            False,
            f"Suppression possible a partir du {available_at.strftime('%d/%m/%Y %H:%M')}.",
            available_at,
        )
    return True, "", available_at


def _resolve_entry_period_id() -> int | None:
    open_period = get_open_financial_period()
    return open_period.id if open_period is not None else None


def record_delivery_fee_entry(order, *, note: str | None = None) -> FinancialEntry | None:
    if order is None or getattr(order, "id", None) is None:
        return None

    amount_cents = int(getattr(order, "delivery_platform_fee_cents", 0) or 0)
    if amount_cents <= 0:
        return None

    existing = (
        FinancialEntry.query
        .filter(
            FinancialEntry.entry_type == ENTRY_TYPE_DELIVERY_FEE,
            FinancialEntry.order_id == order.id,
        )
        .first()
    )
    if existing is not None:
        return existing

    entry = FinancialEntry(
        period_id=_resolve_entry_period_id(),
        entry_type=ENTRY_TYPE_DELIVERY_FEE,
        amount_cents=amount_cents,
        created_at=getattr(order, "delivered_at", None) or datetime.utcnow(),
        order_id=order.id,
        courier_id=getattr(order, "courier_id", None),
        note=(note or "").strip()[:255] or None,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def record_rental_commission_entry(rental_archive, *, note: str | None = None) -> FinancialEntry | None:
    if rental_archive is None:
        return None
    if (getattr(rental_archive, "closed_reason", "") or "").strip().lower() != "taken":
        return None
    if getattr(rental_archive, "id", None) is None:
        db.session.flush()
    if getattr(rental_archive, "id", None) is None:
        return None

    amount_cents = int(getattr(rental_archive, "platform_commission_amount_cents", 0) or 0)
    if amount_cents <= 0:
        return None

    existing = (
        FinancialEntry.query
        .filter(
            FinancialEntry.entry_type == ENTRY_TYPE_RENTAL_COMMISSION,
            FinancialEntry.rental_archive_id == rental_archive.id,
        )
        .first()
    )
    if existing is not None:
        return existing

    entry = FinancialEntry(
        period_id=_resolve_entry_period_id(),
        entry_type=ENTRY_TYPE_RENTAL_COMMISSION,
        amount_cents=amount_cents,
        created_at=getattr(rental_archive, "closed_at", None) or datetime.utcnow(),
        rental_archive_id=rental_archive.id,
        note=(note or "").strip()[:255] or None,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def record_subscription_entry(subscription_payment, *, note: str | None = None) -> FinancialEntry | None:
    if subscription_payment is None:
        return None

    amount_cents = int(getattr(subscription_payment, "amount_cents", 0) or 0)
    if amount_cents <= 0:
        return None
    if getattr(subscription_payment, "id", None) is None:
        db.session.flush()
    if getattr(subscription_payment, "id", None) is None:
        return None

    existing = (
        FinancialEntry.query
        .filter(
            FinancialEntry.entry_type == ENTRY_TYPE_SUBSCRIPTION,
            FinancialEntry.subscription_id == subscription_payment.id,
        )
        .first()
    )
    if existing is not None:
        return existing

    entry = FinancialEntry(
        period_id=_resolve_entry_period_id(),
        entry_type=ENTRY_TYPE_SUBSCRIPTION,
        amount_cents=amount_cents,
        created_at=(
            getattr(subscription_payment, "paid_at", None)
            or getattr(subscription_payment, "created_at", None)
            or datetime.utcnow()
        ),
        subscription_id=subscription_payment.id,
        note=((note or "").strip()[:255] or getattr(subscription_payment, "note", None)),
    )
    db.session.add(entry)
    db.session.flush()
    return entry

