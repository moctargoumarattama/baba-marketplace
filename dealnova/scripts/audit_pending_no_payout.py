#!/usr/bin/env python3
"""
One-shot read-only audit for pending orders without vendor payouts.
Run this script from the dealnova directory.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models.order import Order, OrderItem
from app.models.vendor_payout import VendorPayout
from app.extensions import db


def audit_pending_no_payout() -> int:
    app = create_app()
    with app.app_context():
        rows = (
            db.session.query(
                Order.id,
                Order.created_at,
                Order.total,
                Order.city,
                db.func.count(db.distinct(OrderItem.id)).label("nb_items"),
            )
            .outerjoin(VendorPayout, VendorPayout.order_id == Order.id)
            .outerjoin(OrderItem, OrderItem.order_id == Order.id)
            .filter(Order.status == "pending")
            .filter(VendorPayout.id.is_(None))
            .group_by(Order.id, Order.created_at, Order.total, Order.city)
            .order_by(Order.created_at.asc(), Order.id.asc())
            .all()
        )

        print("id | created_at | total | city | nb_items")
        print("-" * 48)
        for row in rows:
            created_at = row.created_at.isoformat(sep=" ", timespec="seconds") if row.created_at else "-"
            total = f"{(row.total or 0) / 100:.2f}"
            print(f"{row.id} | {created_at} | {total} | {row.city or '-'} | {row.nb_items}")

        print("-" * 48)
        print(f"TOTAL: {len(rows)}")
        return len(rows)


if __name__ == "__main__":
    audit_pending_no_payout()
