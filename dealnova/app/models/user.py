from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from ..extensions import db

class User(UserMixin, db.Model):
    ALLOWED_ROLES = ("admin", "manager", "vendor", "courier")

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    vendor_history_pin_hash = db.Column(db.String(256), nullable=True)
    role = db.Column(db.String(20), default="courier")  # admin, manager, vendor, courier
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    courier_is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    courier_is_available = db.Column(db.Boolean, default=False, nullable=False, index=True)
    courier_admin_note = db.Column(db.Text, nullable=True)
    courier_last_seen_at = db.Column(db.DateTime, nullable=True)
    password_change_allowed_until = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    # Abonnements vendeurs
    subscription_expires_at = db.Column(db.DateTime, nullable=True)
    subscription_last_paid_at = db.Column(db.DateTime, nullable=True)
    subscription_note = db.Column(db.Text, nullable=True)
    subscription_free_until = db.Column(db.DateTime, nullable=True)
    # Profil additionnel
    full_name = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.Text, nullable=True)
    reset_token = db.Column(db.String(200), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    products = db.relationship("Product", back_populates="vendor", lazy=True, cascade="all, delete-orphan")
    shop = db.relationship("Shop", back_populates="vendor", uselist=False, cascade="all, delete-orphan")
    orders = db.relationship("Order", backref="buyer", lazy=True, foreign_keys="Order.buyer_id")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_vendor_history_pin(self, pin):
        self.vendor_history_pin_hash = generate_password_hash(pin)

    def check_vendor_history_pin(self, pin):
        if not self.vendor_history_pin_hash:
            return False
        return check_password_hash(self.vendor_history_pin_hash, pin)

    def password_change_window_active(self, now: datetime | None = None) -> bool:
        if not self.password_change_allowed_until:
            return False
        return self.password_change_allowed_until > (now or datetime.utcnow())

    def __repr__(self):
        return f"<User {self.username}>"

