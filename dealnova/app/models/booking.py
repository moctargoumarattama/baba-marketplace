from datetime import datetime
import secrets

from ..extensions import db


class Booking(db.Model):
    __tablename__ = "booking"

    STATUSES = ["pending", "confirmed", "completed", "cancelled", "archived"]

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(16))

    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id", name="fk_booking_buyer_id_user"), nullable=True, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", name="fk_booking_product_id_product"), nullable=False, index=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id", name="fk_booking_shop_id_shop"), nullable=True, index=True)

    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20), nullable=False, index=True)
    phone_digits = db.Column(db.String(32), nullable=True, index=True)

    scheduled_for = db.Column(db.DateTime, nullable=True, index=True)
    note = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)

    booking_ip = db.Column(db.String(45), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    buyer = db.relationship("User", backref="bookings", foreign_keys=[buyer_id])
    product = db.relationship("Product", backref="bookings", foreign_keys=[product_id])
    shop = db.relationship("Shop", backref="bookings", foreign_keys=[shop_id])

    def __repr__(self):
        return f"<Booking {self.id} product={self.product_id} status={self.status}>"

