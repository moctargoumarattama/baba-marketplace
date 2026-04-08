from datetime import datetime

from ..extensions import db


class RuntimeState(db.Model):
    __tablename__ = "runtime_state"

    state_key = db.Column(db.String(120), primary_key=True)
    value_int = db.Column(db.BigInteger, nullable=True)
    value_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True,
    )

    def __repr__(self):
        return f"<RuntimeState {self.state_key}>"
