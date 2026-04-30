import json
from datetime import datetime

from ..extensions import db


class ProductContactLead(db.Model):
    __tablename__ = "product_contact_lead"

    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(100), nullable=True)
    client_phone = db.Column(db.String(30), nullable=True, index=True)
    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shop.id", name="fk_product_contact_lead_shop_id"),
        nullable=True,
        index=True,
    )
    product_summary_json = db.Column(db.Text, nullable=False, default="[]")
    estimated_total = db.Column(db.Integer, nullable=False, default=0)
    whatsapp_phone = db.Column(db.String(30), nullable=True)
    source = db.Column(db.String(40), nullable=False, default="product_whatsapp", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    shop = db.relationship("Shop", backref="product_contact_leads")

    @property
    def product_summary(self):
        try:
            data = json.loads(self.product_summary_json or "[]")
        except (TypeError, ValueError):
            return []
        return data if isinstance(data, list) else []

    @property
    def estimated_total_mad(self):
        return (self.estimated_total or 0) / 100
