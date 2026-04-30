from datetime import datetime, timedelta

from ..extensions import db
from ..models.order import Order


def expire_old_drafts(ttl_hours=2) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)
    orders = (
        Order.query
        .filter(Order.status == "draft", Order.created_at < cutoff)
        .all()
    )
    if not orders:
        return 0

    for order in orders:
        order.status = "expired"

    db.session.commit()
    return len(orders)
