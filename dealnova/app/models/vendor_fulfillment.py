from datetime import datetime

from ..extensions import db


class VendorFulfillment(db.Model):
    """
    Suivi logistique "vendeur" par commande.

    Important:
    - Ce statut est propre au vendeur (multi-vendeurs possible dans la meme commande).
    - Ne remplace pas Order.status (marketplace / livraison).
    """

    __tablename__ = "vendor_fulfillment"

    STATUSES = ["to_prepare", "ready", "handed"]

    id = db.Column(db.Integer, primary_key=True)

    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_vendorfulfillment_vendor_id"),
        nullable=False,
        index=True,
    )
    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order.id", name="fk_vendorfulfillment_order_id"),
        nullable=False,
        index=True,
    )

    status = db.Column(db.String(20), nullable=False, default="to_prepare", index=True)
    prepared_at = db.Column(db.DateTime, nullable=True, index=True)
    handed_at = db.Column(db.DateTime, nullable=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    vendor = db.relationship("User", backref="vendor_fulfillments")
    order = db.relationship("Order", backref="vendor_fulfillments")

    __table_args__ = (
        db.UniqueConstraint("vendor_id", "order_id", name="uq_vendorfulfillment_vendor_order"),
    )

    def __repr__(self):
        return f"<VendorFulfillment vendor={self.vendor_id} order={self.order_id} status={self.status}>"


