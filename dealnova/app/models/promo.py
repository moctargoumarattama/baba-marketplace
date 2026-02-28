from ..extensions import db

class Promo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # percentage | fixed
    value = db.Column(db.Float, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
