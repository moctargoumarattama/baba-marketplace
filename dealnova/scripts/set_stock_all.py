from app import create_app, db
from app.models.product import Product

app = create_app()
with app.app_context():
    products = Product.query.all()
    for p in products:
        p.stock = 30
    db.session.commit()
    print(f"Updated {len(products)} products.")
