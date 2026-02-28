from datetime import datetime

from ..extensions import db


class MaintenanceRun(db.Model):
    __tablename__ = "maintenance_runs"

    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(16), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    finished_at = db.Column(db.DateTime, nullable=True, index=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    result_counts = db.Column(db.JSON, nullable=True)
    error_count = db.Column(db.Integer, nullable=False, default=0)


class ErrorLog(db.Model):
    __tablename__ = "error_logs"

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(512), nullable=True)
    method = db.Column(db.String(16), nullable=True)
    status_code = db.Column(db.Integer, nullable=False, index=True)
    short_message = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

