from datetime import datetime

from ..extensions import db


class VendorPushSubscription(db.Model):
    __tablename__ = "vendor_push_subscription"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_vendor_push_subscription_vendor_id"),
        nullable=False,
        index=True,
    )
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    user_agent = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    failure_count = db.Column(db.Integer, nullable=False, default=0)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor = db.relationship("User", backref="vendor_push_subscriptions")

    def __repr__(self):
        return f"<VendorPushSubscription vendor={self.vendor_id} active={self.is_active}>"
