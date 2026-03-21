from datetime import datetime
from ..extensions import db
from sqlalchemy import CheckConstraint

class Product(db.Model):
    __tablename__ = "product"
    
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), default="physical", nullable=False, index=True)  # physical | service
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
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
        CheckConstraint('price >= 0', name='price_non_negative'),
        CheckConstraint('stock >= 0', name='stock_non_negative'),
        CheckConstraint('view_count >= 0', name='view_count_non_negative'),
    )

    def __repr__(self):
        return f"<Product {self.name}>"

