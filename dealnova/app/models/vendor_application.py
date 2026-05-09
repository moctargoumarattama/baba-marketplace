from datetime import datetime

from ..extensions import db


class VendorApplication(db.Model):
    __tablename__ = "vendor_application"

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_BLOCKED = "blocked"
    STATUS_ORDER = (
        STATUS_PENDING,
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_BLOCKED,
    )

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    phone_digits = db.Column(db.String(32), nullable=False, index=True)
    email = db.Column(db.String(120), nullable=True)
    email_normalized = db.Column(db.String(120), nullable=True, index=True)
    shop_name = db.Column(db.String(160), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    shop_type = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    short_description = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.String(20),
        nullable=False,
        default=STATUS_PENDING,
        index=True,
    )
    review_note = db.Column(db.Text, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True, index=True)
    reviewed_by_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_vendorapplication_reviewed_by_id"),
        nullable=True,
        index=True,
    )

    created_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_vendorapplication_created_user_id"),
        nullable=True,
        unique=True,
        index=True,
    )
    created_shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shop.id", name="fk_vendorapplication_created_shop_id"),
        nullable=True,
        unique=True,
        index=True,
    )

    source = db.Column(db.String(30), nullable=False, default="web_form")
    request_ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id], lazy="joined")
    created_user = db.relationship("User", foreign_keys=[created_user_id], lazy="joined")
    created_shop = db.relationship("Shop", foreign_keys=[created_shop_id], lazy="joined")

    @classmethod
    def allowed_statuses(cls) -> tuple[str, ...]:
        return cls.STATUS_ORDER

    @classmethod
    def normalize_status(cls, value: str | None) -> str:
        candidate = str(value or "").strip().lower()
        return candidate if candidate in cls.STATUS_ORDER else cls.STATUS_PENDING

    def __repr__(self):
        return f"<VendorApplication id={self.id} status={self.status} phone={self.phone}>"
