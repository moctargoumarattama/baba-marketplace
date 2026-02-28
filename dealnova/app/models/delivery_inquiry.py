from datetime import datetime

from ..extensions import db


class DeliveryInquiry(db.Model):
    __tablename__ = "delivery_inquiry"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(40), nullable=False, index=True)
    city = db.Column(db.String(50), nullable=False, index=True)
    price_cents = db.Column(db.Integer, nullable=False, default=0)

    item_text = db.Column(db.String(255), nullable=True)
    pickup_text = db.Column(db.String(255), nullable=True)
    dropoff_text = db.Column(db.String(255), nullable=True)
    note_text = db.Column(db.String(255), nullable=True)
    urgent = db.Column(db.Boolean, nullable=False, default=False)
    desired_datetime = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<DeliveryInquiry {self.id} {self.city}>"

