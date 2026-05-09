from datetime import datetime, timedelta

from ..extensions import db


def _default_featured_end() -> datetime:
    return datetime.utcnow() + timedelta(days=30)


class FeaturedItem(db.Model):
    __tablename__ = "featured_item"

    TARGET_SHOP = "shop"
    TARGET_PRODUCT = "product"
    TARGET_LOCATION = "location"
    TARGET_TYPES = (TARGET_SHOP, TARGET_PRODUCT, TARGET_LOCATION)

    id = db.Column(db.Integer, primary_key=True)
    target_type = db.Column(db.String(20), nullable=False, index=True)
    shop_id = db.Column(
        db.Integer,
        db.ForeignKey("shop.id", name="fk_featureditem_shop_id"),
        nullable=True,
        index=True,
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id", name="fk_featureditem_product_id"),
        nullable=True,
        index=True,
    )
    location_id = db.Column(
        db.Integer,
        db.ForeignKey("rental_listing.id", name="fk_featureditem_location_id"),
        nullable=True,
        index=True,
    )
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_featureditem_vendor_id"),
        nullable=True,
        index=True,
    )
    created_by_admin_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_featureditem_created_by_admin_id"),
        nullable=True,
        index=True,
    )
    note = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    starts_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, default=_default_featured_end, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    shop = db.relationship("Shop", foreign_keys=[shop_id], lazy="joined")
    product = db.relationship("Product", foreign_keys=[product_id], lazy="joined")
    location = db.relationship("RentalListing", foreign_keys=[location_id], lazy="joined")
    vendor = db.relationship("User", foreign_keys=[vendor_id], lazy="joined")
    created_by_admin = db.relationship("User", foreign_keys=[created_by_admin_id], lazy="joined")

    __table_args__ = (
        db.CheckConstraint(
            "target_type IN ('shop','product','location')",
            name="ck_featureditem_target_type",
        ),
        db.CheckConstraint(
            "ends_at >= starts_at",
            name="ck_featureditem_dates_order",
        ),
        db.Index(
            "ix_featureditem_active_window",
            "is_active",
            "starts_at",
            "ends_at",
            "target_type",
        ),
        db.Index(
            "ix_featureditem_target_latest",
            "target_type",
            "shop_id",
            "product_id",
            "location_id",
            "is_active",
            "ends_at",
            "created_at",
        ),
        db.Index("ix_featureditem_created_id", "created_at", "id"),
    )

    @property
    def target_id(self):
        if self.target_type == self.TARGET_SHOP:
            return self.shop_id
        if self.target_type == self.TARGET_PRODUCT:
            return self.product_id
        if self.target_type == self.TARGET_LOCATION:
            return self.location_id
        return None

    def is_currently_active(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.utcnow()
        return bool(self.is_active and self.starts_at <= current_time <= self.ends_at)

    def __repr__(self):
        return f"<FeaturedItem {self.target_type}:{self.target_id} active={self.is_active}>"
