from datetime import datetime
from ..extensions import db


class BlockedContact(db.Model):
    __tablename__ = "blocked_contact"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False)  # phone | ip
    value = db.Column(db.String(64), nullable=False, index=True)
    reason = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by_id = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("kind", "value", name="uq_blocked_contact_kind_value"),
    )

    def __repr__(self):
        return f"<BlockedContact {self.kind}:{self.value}>"

