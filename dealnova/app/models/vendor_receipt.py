from datetime import datetime

from ..extensions import db


class VendorReceipt(db.Model):
    __tablename__ = "vendor_receipt"

    id = db.Column(db.Integer, primary_key=True)

    vendor_id = db.Column(db.Integer, db.ForeignKey("user.id", name="fk_vendorreceipt_vendor_id"), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id", name="fk_vendorreceipt_order_id"), nullable=False, index=True)

    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    vendor = db.relationship("User", backref="vendor_receipts")
    order = db.relationship("Order", backref="vendor_receipts")

    __table_args__ = (
        db.UniqueConstraint("vendor_id", "order_id", name="uq_vendorreceipt_vendor_order"),
    )

    def __repr__(self):
        return f"<VendorReceipt order={self.order_id} vendor={self.vendor_id} received_at={self.received_at}>"


