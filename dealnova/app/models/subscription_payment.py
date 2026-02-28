from datetime import datetime

from ..extensions import db


class SubscriptionPayment(db.Model):
    __tablename__ = "subscription_payment"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_subscription_payment_user_id"),
        nullable=False,
        index=True,
    )
    months = db.Column(db.Integer, nullable=False, default=1)
    amount_cents = db.Column(db.Integer, nullable=False, default=0)
    paid_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_subscription_payment_created_by_id"),
        nullable=True,
        index=True,
    )
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    user = db.relationship("User", foreign_keys=[user_id], backref="subscription_payments")
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    __table_args__ = (
        db.CheckConstraint("months >= 1", name="ck_subscription_payment_months_positive"),
        db.CheckConstraint("amount_cents >= 0", name="ck_subscription_payment_amount_non_negative"),
    )

    def __repr__(self):
        return f"<SubscriptionPayment {self.id} user={self.user_id} amount={self.amount_cents}>"

