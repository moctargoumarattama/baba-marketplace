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

    status = db.Column(db.String(20), default="pending", nullable=False)  # pending | claimable | claimed | paid | cancelled
    is_claimable = db.Column(db.Boolean, default=False, nullable=False)
    claimed_at = db.Column(db.DateTime, nullable=True)
    claimed_by_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_payout_claimed_by_id"),
        nullable=True,
    )
    paid_at = db.Column(db.DateTime, nullable=True)
    paid_note = db.Column(db.String(255), nullable=True)
    paid_by_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    order = db.relationship("Order", backref="vendor_payouts")
    vendor = db.relationship("User", backref="vendor_payouts", foreign_keys=[vendor_id])
    claimed_by = db.relationship("User", foreign_keys=[claimed_by_id])
    shop = db.relationship("Shop", backref="vendor_payouts")

    def __repr__(self):
        return f"<VendorPayout order={self.order_id} vendor={self.vendor_id} amount={self.amount_cents}>"

