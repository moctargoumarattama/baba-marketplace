import json
from datetime import datetime
from typing import Iterable
from urllib.parse import quote_plus

from sqlalchemy import func, or_

from ..extensions import db

SHOP_TYPE_ORDER = ("products", "services", "location")
SHOP_TYPE_LABELS = {
    "products": "Produits",
    "services": "Services",
    "location": "Location",
}
PRODUCT_KIND_TO_SHOP_TYPE = {
    "physical": "products",
    "service": "services",
}
SHOP_TYPE_ALIASES = {
    "product": "products",
    "products": "products",
    "physical": "products",
    "service": "services",
    "services": "services",
    "booking": "services",
    "location": "location",
    "locations": "location",
    "rental": "location",
    "rentals": "location",
}


def normalize_shop_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    normalized = SHOP_TYPE_ALIASES.get(normalized, normalized)
    return normalized if normalized in SHOP_TYPE_ORDER else None


def normalize_allowed_shop_types(
    values: Iterable[str] | None,
    primary_type: str | None = "products",
) -> list[str]:
    primary = normalize_shop_type(primary_type) or "products"
    seen: set[str] = set()
    for item in values or []:
        normalized = normalize_shop_type(item)
        if normalized:
            seen.add(normalized)

    seen.add(primary)
    ordered = [shop_type for shop_type in SHOP_TYPE_ORDER if shop_type in seen]
    return ordered or [primary]


def shop_type_from_product_kind(kind: str | None) -> str:
    normalized_kind = (kind or "").strip().lower()
    return PRODUCT_KIND_TO_SHOP_TYPE.get(normalized_kind, "products")


class Shop(db.Model):
    __tablename__ = "shop"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("user.id", name="fk_shop_vendor_id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    logo = db.Column(db.String(255), nullable=True)
    banner = db.Column(db.String(255), nullable=True)
    contact_phone = db.Column(db.String(30), nullable=True)
    contact_email = db.Column(db.String(120), nullable=True)
    address = db.Column(db.Text, nullable=True)
    service_latitude = db.Column(db.Float, nullable=True)
    service_longitude = db.Column(db.Float, nullable=True)
    service_location_note = db.Column(db.String(255), nullable=True)
    rating = db.Column(db.Float, default=0.0)
    review_count = db.Column(db.Integer, default=0)
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    # Disponibilite (repos/vacances) : n'affecte pas l'existence du compte, juste l'accueil des nouvelles commandes/rdv.
    is_open = db.Column(db.Boolean, default=True, nullable=False, index=True)
    closed_until = db.Column(db.DateTime, nullable=True, index=True)
    closed_note = db.Column(db.String(255), nullable=True)
    primary_type = db.Column(db.String(20), nullable=False, default="products", index=True)
    allowed_types_json = db.Column(db.Text, nullable=False, default='["products"]')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    vendor = db.relationship("User", back_populates="shop", foreign_keys=[vendor_id])
    products = db.relationship("Product", back_populates="shop", lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Shop {self.name}>"

    @classmethod
    def type_label(cls, type_name: str | None) -> str:
        normalized = normalize_shop_type(type_name)
        return SHOP_TYPE_LABELS.get(normalized or "", "Type inconnu")

    @classmethod
    def sql_allows_clause(cls, type_name: str | None):
        normalized = normalize_shop_type(type_name)
        if not normalized:
            return db.false()
        return or_(
            cls.primary_type == normalized,
            cls.allowed_types_json.like(f'%"{normalized}"%'),
        )

    def get_allowed_types(self) -> list[str]:
        primary = normalize_shop_type(self.primary_type) or "products"
        parsed: list[str] = []
        raw = (self.allowed_types_json or "").strip()
        if raw:
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, list):
                    parsed = [str(item) for item in loaded]
            except Exception:
                parsed = [item.strip() for item in raw.split(",") if item.strip()]
        return normalize_allowed_shop_types(parsed, primary_type=primary)

    def set_allowed_types(self, values: Iterable[str] | None) -> list[str]:
        primary = normalize_shop_type(self.primary_type) or "products"
        normalized = normalize_allowed_shop_types(values, primary_type=primary)
        self.allowed_types_json = json.dumps(normalized, ensure_ascii=False)
        return normalized

    def allows(self, type_name: str | None) -> bool:
        normalized = normalize_shop_type(type_name)
        if not normalized:
            return False
        return normalized in self.get_allowed_types()

    @property
    def allowed_types(self) -> list[str]:
        return self.get_allowed_types()

    @allowed_types.setter
    def allowed_types(self, values: Iterable[str] | None):
        self.set_allowed_types(values)

    @property
    def product_count(self):
        cached = getattr(self, "_product_count_cache", None)
        if cached is not None:
            return cached
        from .product import Product
        return Product.query.filter_by(shop_id=self.id, is_active=True).count()

    @product_count.setter
    def product_count(self, value):
        self._product_count_cache = value

    @property
    def total_sales(self):
        cached = getattr(self, "_total_sales_cache", None)
        if cached is not None:
            return cached
        from .order import OrderItem
        from .product import Product
        return OrderItem.query.join(Product).filter(Product.shop_id == self.id).count()

    @total_sales.setter
    def total_sales(self, value):
        self._total_sales_cache = value

    @property
    def has_precise_service_location(self) -> bool:
        return self.service_latitude is not None and self.service_longitude is not None

    @property
    def service_map_query(self) -> str:
        if self.has_precise_service_location:
            return f"{float(self.service_latitude):.6f},{float(self.service_longitude):.6f}"
        return (self.address or "").strip()

    @property
    def service_map_url(self) -> str:
        query = self.service_map_query
        if not query:
            return ""
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"

    @classmethod
    def sql_is_incomplete_clause(cls):
        return or_(
            cls.description.is_(None),
            func.length(func.trim(cls.description)) == 0,
            cls.contact_email.is_(None),
            func.length(func.trim(cls.contact_email)) == 0,
            cls.contact_phone.is_(None),
            func.length(func.trim(cls.contact_phone)) == 0,
            cls.address.is_(None),
            func.length(func.trim(cls.address)) == 0,
            cls.primary_type.is_(None),
            func.length(func.trim(cls.primary_type)) == 0,
            cls.allowed_types_json.is_(None),
            func.length(func.trim(cls.allowed_types_json)) == 0,
        )

    @property
    def missing_profile_fields(self) -> list[str]:
        missing: list[str] = []
        if not (self.description or "").strip():
            missing.append("description")
        if not (self.contact_email or "").strip():
            missing.append("email de contact")
        if not (self.contact_phone or "").strip():
            missing.append("telephone")
        if not (self.address or "").strip():
            missing.append("adresse")
        if not normalize_shop_type(self.primary_type):
            missing.append("type principal")
        if not self.get_allowed_types():
            missing.append("activites proposees")
        return missing

    @property
    def is_profile_complete(self) -> bool:
        return len(self.missing_profile_fields) == 0

