try:
    from app import create_app, db
    from app.models import order, product, promo, user
except ModuleNotFoundError:
    # Fallback when starting from repository root.
    from dealnova.app import create_app, db
    from dealnova.app.models import order, product, promo, user

app = create_app()


@app.shell_context_processor
def make_shell_context():
    return {
        "db": db,
        "User": user.User,
        "Product": product.Product,
        "Promo": promo.Promo,
        "Order": order.Order,
    }


if __name__ == "__main__":
    app.run(debug=True, port=5002)
