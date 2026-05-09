from datetime import datetime

from ..extensions import db


class VendorChangeRequest(db.Model):
    __tablename__ = "vendor_change_request"

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_ORDER = (
        STATUS_PENDING,
        STATUS_APPROVED,
        STATUS_REJECTED,
    )

    TYPE_ACCOUNT_EMAIL = "account_email"
    TYPE_SHOP_NAME = "shop_name"
    TYPE_ORDER = (
        TYPE_ACCOUNT_EMAIL,
        TYPE_SHOP_NAME,
    )

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_vendorchangerequest_vendor_id"),
        nullable=False,
        index=True,
    )
    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shop.id", name="fk_vendorchangerequest_shop_id"),
        nullable=False,
        index=True,
    )
    request_type = db.Column(db.String(30), nullable=False, index=True)
    current_value = db.Column(db.String(255), nullable=False)
    requested_value = db.Column(db.String(255), nullable=False)
    reason = db.Column(db.Text, nullable=True)

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
        db.ForeignKey("user.id", name="fk_vendorchangerequest_reviewed_by_id"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    vendor = db.relationship("User", foreign_keys=[vendor_id], lazy="joined")
    shop = db.relationship("Shop", foreign_keys=[shop_id], lazy="joined")
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id], lazy="joined")

    @classmethod
    def allowed_statuses(cls) -> tuple[str, ...]:
        return cls.STATUS_ORDER

    @classmethod
    def allowed_types(cls) -> tuple[str, ...]:
        return cls.TYPE_ORDER

    @classmethod
    def normalize_status(cls, value: str | None) -> str:
        candidate = str(value or "").strip().lower()
        return candidate if candidate in cls.STATUS_ORDER else cls.STATUS_PENDING

    @classmethod
    def normalize_type(cls, value: str | None) -> str:
        candidate = str(value or "").strip().lower()
        return candidate if candidate in cls.TYPE_ORDER else ""

    def __repr__(self):
        return (
            f"<VendorChangeRequest id={self.id} vendor_id={self.vendor_id} "
            f"type={self.request_type} status={self.status}>"
        )
