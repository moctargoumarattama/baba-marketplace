from __future__ import annotations

from datetime import datetime

from flask import current_app

from ..extensions import db
from ..models.financial import FinancialEntry


ENTRY_TYPE_DELIVERY_FEE = "delivery_fee"
ENTRY_TYPE_SUBSCRIPTION = "subscription"
ENTRY_TYPE_RENTAL_COMMISSION = "rental_commission"
MAX_REASONABLE_AMOUNT = 1_000_000_00


def _amount_is_suspicious(amount_cents: int, reference: str) -> bool:
    if amount_cents <= MAX_REASONABLE_AMOUNT:
        return False
    current_app.logger.warning("Montant anormal: %s pour %s", amount_cents, reference)
    return True


def record_delivery_fee_entry(order, *, note: str | None = None) -> FinancialEntry | None:
    if order is None or getattr(order, "id", None) is None:
        return None

    amount_cents = int(getattr(order, "delivery_platform_fee_cents", 0) or 0)
    if amount_cents <= 0:
        return None
    _amount_is_suspicious(amount_cents, f"order {order.id}")

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
        entry_type=ENTRY_TYPE_DELIVERY_FEE,
        amount_cents=amount_cents,
        created_at=getattr(order, "delivered_at", None) or datetime.utcnow(),
        order_id=order.id,
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
    _amount_is_suspicious(amount_cents, f"rental {rental_archive.id}")

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
    _amount_is_suspicious(amount_cents, f"payment {getattr(subscription_payment, 'id', '')}")

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
