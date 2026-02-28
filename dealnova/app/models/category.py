from ..extensions import db
from datetime import datetime

CATEGORY_TYPE_ORDER = ("products", "services")
CATEGORY_TYPE_LABELS = {
    "products": "Produits",
    "services": "Services",
}
CATEGORY_TYPE_ALIASES = {
    "product": "products",
    "products": "products",
    "physical": "products",
    "service": "services",
    "services": "services",
}


def normalize_category_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    normalized = CATEGORY_TYPE_ALIASES.get(normalized, normalized)
    return normalized if normalized in CATEGORY_TYPE_ORDER else None


class Category(db.Model):
    __tablename__ = "category"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)  # Ex: "Appartement", "Chambre"
    slug = db.Column(db.String(100), nullable=False, unique=True)  # pour URL friendly
    description = db.Column(db.Text, nullable=True)
    base_price = db.Column(db.Integer, nullable=False, default=0)  # prix de base en centimes
    category_type = db.Column(db.String(20), nullable=False, default="products", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relation vers les produits
    products = db.relationship("Product", back_populates="category", lazy=True)

    @classmethod
    def type_label(cls, category_type: str | None) -> str:
        normalized = normalize_category_type(category_type) or "products"
        return CATEGORY_TYPE_LABELS.get(normalized, "Produits")

    @classmethod
    def type_from_product_kind(cls, kind: str | None) -> str:
        return "services" if (kind or "").strip().lower() == "service" else "products"

    @property
    def normalized_type(self) -> str:
        return normalize_category_type(self.category_type) or "products"

    def __repr__(self):
        return f"<Category {self.name}>"

