from datetime import datetime

from sqlalchemy import CheckConstraint, event, inspect

from ..extensions import db


class Product(db.Model):
    __tablename__ = "product"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), default="physical", nullable=False, index=True)  # physical | service
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    price_cents_value = db.Column("price_cents", db.Integer, nullable=False, default=0, index=True)
    image_file = db.Column(db.String(255), nullable=True)
    video_file = db.Column(db.String(255), nullable=True)

    # Relations
    vendor_id = db.Column(db.Integer, db.ForeignKey("user.id", name="fk_product_vendor_id"), nullable=True, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id", name="fk_product_category_id"), nullable=True, index=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id", name="fk_product_shop_id"), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    stock = db.Column(db.Integer, default=0, nullable=False)
    view_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # Relations
    vendor = db.relationship("User", back_populates="products", foreign_keys=[vendor_id])
    category = db.relationship("Category", back_populates="products")
    shop = db.relationship("Shop", back_populates="products", foreign_keys=[shop_id])

    promos = db.relationship("Promo", backref="product", lazy=True, cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("price_cents >= 0", name="price_cents_non_negative"),
        CheckConstraint("stock >= 0", name="stock_non_negative"),
        CheckConstraint("view_count >= 0", name="view_count_non_negative"),
        db.Index("ix_product_vendor_created_id", "vendor_id", "created_at", "id"),
        db.Index("ix_product_vendor_active_created", "vendor_id", "is_active", "created_at"),
        db.Index("ix_product_vendor_kind_created", "vendor_id", "kind", "created_at"),
        db.Index("ix_product_vendor_category_created", "vendor_id", "category_id", "created_at"),
    )

    def __repr__(self):
        return f"<Product {self.name}>"

    @property
    def price_cents(self) -> int:
        from ..services.pricing import money_to_cents

        if self.price_cents_value is not None:
            try:
                return max(0, int(self.price_cents_value))
            except (TypeError, ValueError):
                pass
        return money_to_cents(self.price)

    @price_cents.setter
    def price_cents(self, value: int) -> None:
        from ..services.pricing import cents_to_money

        cents = max(0, int(value or 0))
        self.price_cents_value = cents
        self.price = cents_to_money(cents)

    def set_price_amount(self, value) -> int:
        from ..services.pricing import money_to_cents, parse_money_input

        cents = money_to_cents(parse_money_input(value, allow_zero=False))
        self.price_cents = cents
        return cents


def _sync_product_price_fields(target: Product) -> None:
    from ..services.pricing import cents_to_money, money_to_cents

    state = inspect(target)
    cents_attr = state.attrs.price_cents_value
    price_attr = state.attrs.price

    cents_changed = cents_attr.history.has_changes()
    price_changed = price_attr.history.has_changes()
    current_price = getattr(target, "price", 0) or 0
    current_cents_raw = getattr(target, "price_cents_value", None)
    current_price_cents = money_to_cents(current_price)
    current_cents = max(0, int(current_cents_raw or 0))

    if price_changed and (not cents_changed or (current_cents <= 0 and current_price_cents > 0)):
        target.price_cents_value = current_price_cents
        target.price = cents_to_money(current_price_cents)
        return

    if cents_changed:
        target.price_cents_value = current_cents
        target.price = cents_to_money(current_cents)
        return

    if price_changed or current_cents_raw is None:
        target.price_cents_value = current_price_cents
        target.price = cents_to_money(current_price_cents)
        return

    if current_price_cents > 0 and current_cents <= 0:
        target.price_cents_value = current_price_cents
        target.price = cents_to_money(current_price_cents)
        return

    target.price = cents_to_money(current_cents)


@event.listens_for(Product, "before_insert")
def _sync_product_price_before_insert(mapper, connection, target):
    del mapper, connection
    _sync_product_price_fields(target)


@event.listens_for(Product, "before_update")
def _sync_product_price_before_update(mapper, connection, target):
    del mapper, connection
    _sync_product_price_fields(target)
