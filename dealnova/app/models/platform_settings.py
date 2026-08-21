# app/models/platform_settings.py

from ..extensions import db


class PlatformSettings(db.Model):
    __tablename__ = "platform_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Commission plateforme (vendeur)
    # ex: 10 = 10%
    # Deprecated: seller commission is no longer applied to product/service orders.
    seller_commission_percent = db.Column(db.Float, nullable=False, default=10.0)

    # Low stock threshold (vendor alerts)
    low_stock_threshold = db.Column(db.Integer, nullable=False, default=5)

    # Abonnements vendeurs (montant mensuel fixe, en centimes)
    vendor_subscription_monthly_cents = db.Column(db.Integer, nullable=False, default=0)
    # Mode free global jusqu'a une date donnee
    vendor_free_until = db.Column(db.DateTime, nullable=True)

    # Location (commission a succes definie par l'admin)
    rental_success_commission_mode = db.Column(db.String(20), nullable=False, default="percent")  # percent|fixed
    rental_success_commission_bps = db.Column(db.Integer, nullable=False, default=500)  # 5.00%
    rental_success_commission_fixed_cents = db.Column(db.Integer, nullable=False, default=0)
    rental_monthly_duration_days = db.Column(db.Integer, nullable=False, default=14)
    rental_daily_duration_days = db.Column(db.Integer, nullable=False, default=14)

    # Maintenance mode
    maintenance_enabled = db.Column(db.Boolean, nullable=False, default=False)
    maintenance_message = db.Column(db.Text, nullable=True)
    maintenance_enabled_at = db.Column(db.DateTime, nullable=True)
    maintenance_starts_at = db.Column(db.DateTime, nullable=True)
    maintenance_ends_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<PlatformSettings {self.id}>"

    @classmethod
    def get(cls):
        """
        Recupere l'unique ligne de configuration.
        La cree automatiquement si elle n'existe pas.
        """
        instance = cls.query.first()
        if not instance:
            instance = cls()
            db.session.add(instance)
            db.session.commit()
        return instance

