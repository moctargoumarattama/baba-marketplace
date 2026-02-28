from datetime import datetime
from ..extensions import db


class VendorPayout(db.Model):
    __tablename__ = "vendor_payout"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id", name="fk_payout_order_id"), nullable=False, index=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("user.id", name="fk_payout_vendor_id"), nullable=False, index=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id", name="fk_payout_shop_id"), nullable=True, index=True)

    subtotal_cents = db.Column(db.Integer, default=0, nullable=False)
    commission_cents = db.Column(db.Integer, default=0, nullable=False)
    amount_cents = db.Column(db.Integer, default=0, nullable=False)

    status = db.Column(db.String(20), default="pending", nullable=False)  # pending | paid
    paid_at = db.Column(db.DateTime, nullable=True)
    paid_note = db.Column(db.String(255), nullable=True)
    paid_by_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship("Order", backref="vendor_payouts")
    vendor = db.relationship("User", backref="vendor_payouts")
    shop = db.relationship("Shop", backref="vendor_payouts")

    def __repr__(self):
        return f"<VendorPayout order={self.order_id} vendor={self.vendor_id} amount={self.amount_cents}>"

