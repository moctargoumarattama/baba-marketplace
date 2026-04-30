from datetime import datetime

from ..extensions import db


FINANCIAL_ENTRY_TYPES = ("delivery_fee", "subscription", "rental_commission")


class FinancialEntry(db.Model):
    __tablename__ = "financial_entry"

    id = db.Column(db.Integer, primary_key=True)
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
    note = db.Column(db.Text, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    order = db.relationship("Order")
    rental_archive = db.relationship("RentalArchive")
    subscription_payment = db.relationship("SubscriptionPayment")

    __table_args__ = (
        db.UniqueConstraint("entry_type", "order_id", name="uq_financial_entry_type_order_id"),
        db.UniqueConstraint("entry_type", "rental_archive_id", name="uq_financial_entry_type_rental_archive_id"),
        db.UniqueConstraint("entry_type", "subscription_id", name="uq_financial_entry_type_subscription_id"),
    )

    def __repr__(self):
        return f"<FinancialEntry {self.id} type={self.entry_type} amount={self.amount_cents}>"

