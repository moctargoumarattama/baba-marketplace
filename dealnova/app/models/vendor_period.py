from datetime import datetime

from ..extensions import db


class VendorPeriod(db.Model):
    __tablename__ = "vendor_period"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("user.id", name="fk_vendorperiod_vendor_id"), nullable=False, index=True)

    name = db.Column(db.String(120), nullable=False, default="")
    start_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    end_at = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(db.String(10), nullable=False, default="open", index=True)  # open | closed

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    closed_at = db.Column(db.DateTime, nullable=True, index=True)

    vendor = db.relationship("User", backref="vendor_periods")

    def __repr__(self):
        return f"<VendorPeriod {self.id} vendor={self.vendor_id} status={self.status}>"


