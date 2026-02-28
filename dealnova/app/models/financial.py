from datetime import datetime

from ..extensions import db


FINANCIAL_PERIOD_STATUSES = ("open", "closed")
FINANCIAL_ENTRY_TYPES = ("delivery_fee", "subscription", "rental_commission")


class FinancialPeriod(db.Model):
    __tablename__ = "financial_period"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default="open", index=True)

    closed_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    delivery_total_cents = db.Column(db.Integer, nullable=False, default=0)
    subscription_total_cents = db.Column(db.Integer, nullable=False, default=0)
    rental_total_cents = db.Column(db.Integer, nullable=False, default=0)
    total_cents = db.Column(db.Integer, nullable=False, default=0)

    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    entries = db.relationship("FinancialEntry", back_populates="period", lazy=True)

    __table_args__ = (
        db.CheckConstraint("status IN ('open','closed')", name="ck_financial_period_status"),
        db.CheckConstraint("end_date >= start_date", name="ck_financial_period_dates"),
        db.CheckConstraint("delivery_total_cents >= 0", name="ck_financial_period_delivery_total_non_negative"),
        db.CheckConstraint(
            "subscription_total_cents >= 0", name="ck_financial_period_subscription_total_non_negative"
        ),
        db.CheckConstraint("rental_total_cents >= 0", name="ck_financial_period_rental_total_non_negative"),
        db.CheckConstraint("total_cents >= 0", name="ck_financial_period_total_non_negative"),
    )

    def __repr__(self):
        return f"<FinancialPeriod {self.id} {self.name} {self.status}>"


class FinancialEntry(db.Model):
    __tablename__ = "financial_entry"

    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(
        db.Integer,
        db.ForeignKey("financial_period.id", name="fk_financial_entry_period_id"),
        nullable=True,
        index=True,
    )
    entry_type = db.Column(db.Enum(*FINANCIAL_ENTRY_TYPES, name="financial_entry_type"), nullable=False, index=True)
    amount_cents = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order.id", name="fk_financial_entry_order_id"),
        nullable=True,
        index=True,
    )
    rental_archive_id = db.Column(
        db.Integer,
        db.ForeignKey("rental_archive.id", name="fk_financial_entry_rental_archive_id"),
        nullable=True,
        index=True,
    )
    subscription_id = db.Column(
        db.Integer,
        db.ForeignKey("subscription_payment.id", name="fk_financial_entry_subscription_id"),
        nullable=True,
        index=True,
    )
    courier_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_financial_entry_courier_id"),
        nullable=True,
        index=True,
    )
    note = db.Column(db.Text, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    period = db.relationship("FinancialPeriod", back_populates="entries")
    order = db.relationship("Order")
    rental_archive = db.relationship("RentalArchive")
    subscription_payment = db.relationship("SubscriptionPayment")
    courier = db.relationship("User", foreign_keys=[courier_id])

    __table_args__ = (
        db.UniqueConstraint("entry_type", "order_id", name="uq_financial_entry_type_order_id"),
        db.UniqueConstraint("entry_type", "rental_archive_id", name="uq_financial_entry_type_rental_archive_id"),
        db.UniqueConstraint("entry_type", "subscription_id", name="uq_financial_entry_type_subscription_id"),
    )

    def __repr__(self):
        return f"<FinancialEntry {self.id} type={self.entry_type} amount={self.amount_cents}>"

