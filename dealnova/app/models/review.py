from datetime import datetime
from ..extensions import db

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship helpers so templates can access r.user and r.product
    user = db.relationship("User", backref=db.backref("reviews", lazy=True))
    product = db.relationship("Product", backref=db.backref("reviews", lazy=True))
