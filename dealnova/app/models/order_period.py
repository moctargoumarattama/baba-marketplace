from datetime import datetime

from ..extensions import db


class OrderPeriod(db.Model):
    __tablename__ = "order_period"

    STATUSES = ("open", "closed")

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="")
    status = db.Column(db.String(10), nullable=False, default="open", index=True)  # open | closed
    opened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    closed_at = db.Column(db.DateTime, nullable=True, index=True)
    created_by = db.Column(
        db.Integer,
        db.ForeignKey("user.id", name="fk_orderperiod_created_by_user"),
        nullable=True,
        index=True,
    )

    creator = db.relationship("User", foreign_keys=[created_by], backref="order_periods_created")
    orders = db.relationship("Order", back_populates="period")

    def __repr__(self):
        return f"<OrderPeriod {self.id} status={self.status}>"

