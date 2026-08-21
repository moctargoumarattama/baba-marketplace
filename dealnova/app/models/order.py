from datetime import datetime
import secrets

from ..extensions import db

class Order(db.Model):
    # Villes disponibles pour le champ city de la commande
    CITIES = ['Rabat', 'Salé', 'Témara', 'Kénitra']

    STATUSES = ["pending", "shipped", "delivered", "cancelled", "archived", "draft", "expired"]

    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id", name="fk_order_buyer_id_user"), nullable=True, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    phone_digits = db.Column(db.String(32), nullable=True, index=True)
    address = db.Column(db.Text, nullable=False)
    city = db.Column(db.Enum(*CITIES, name="order_city"), nullable=False)
    status = db.Column(db.Enum(*STATUSES, name="order_status"), default="pending", nullable=False, index=True)
    total = db.Column(db.Integer, nullable=False)        # centimes
    commission = db.Column(db.Integer, default=0)        # centimes
    vendor_net = db.Column(db.Integer, default=0)        # centimes
    vendor_paid = db.Column(db.Boolean, default=False, nullable=False)
    vendor_paid_at = db.Column(db.DateTime, nullable=True)
    vendor_paid_note = db.Column(db.Text, nullable=True)
    vendor_paid_by_id = db.Column(db.Integer, nullable=True)
    order_ip = db.Column(db.String(45), nullable=True, index=True)
    shipping = db.Column(db.Integer, default=0)          # centimes
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    delivered_at = db.Column(db.DateTime, nullable=True, index=True)  # pour la logique 72h
    baba_fee_settled_at = db.Column(db.DateTime, nullable=True, index=True)
    baba_fee_settled_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_order_baba_fee_settled_by_user_id_user"),
        nullable=True,
        index=True,
    )
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(16))
    guest_token = db.Column(db.String(32), unique=True, nullable=True, index=True)
    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")
    baba_fee_settled_by = db.relationship("User", foreign_keys=[baba_fee_settled_by_user_id])

    # ======================
    # Méthodes de visibilité
    # ======================
    def is_visible_for_client(self):
        """Retourne True si le client peut voir cette commande (livrée ≤ 72h)"""
        if self.status != "delivered":
            return True
        if not self.delivered_at:
            return True
        return (datetime.utcnow() - self.delivered_at).total_seconds() <= 72*3600

    @staticmethod
    def get_user_orders(user=None, anonymous_token=None):
        """Retourne les commandes visibles par l'utilisateur ou token anonyme"""
        query = Order.query

        # 1️⃣ Admin voit tout
        if user and getattr(user, "role", None) == "admin":
            return query.all()

        # 2️⃣ Utilisateur connecté voit ses commandes
        elif user and getattr(user, "id", None):
            return query.filter_by(buyer_id=user.id).all()

        # 3️⃣ Utilisateur anonyme avec token
        elif anonymous_token:
            return query.filter_by(token=anonymous_token).all()

        # 4️⃣ Sinon, rien
        return []

    def can_view(self, user=None, token=None):
        """Vérifie si l'utilisateur ou le token peut voir cette commande"""
        # Admin peut tout voir
        if user and getattr(user, "role", None) == "admin":
            return True

        # Propriétaire de la commande
        if user and self.buyer_id and self.buyer_id == getattr(user, "id", None):
            return True

        # Token match pour utilisateur anonyme
        if token and self.token == token:
            return True

        # Vendeur peut voir seulement ses produits dans la commande
        if user and getattr(user, "role", None) == "vendor":
            from .product import Product
            exists = (
                db.session.query(OrderItem.id)
                .join(Product, Product.id == OrderItem.product_id)
                .filter(OrderItem.order_id == self.id, Product.vendor_id == user.id)
                .first()
            )
            return exists is not None

        return False


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id", name="fk_orderitem_order_id_order"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id", name="fk_orderitem_product_id_product"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)  # centimes
    product = db.relationship("Product", backref="order_items", lazy=True)

