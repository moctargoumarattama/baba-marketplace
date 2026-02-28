import re

from app import create_app
from app.extensions import db
from app.models.order import Order


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def main():
    app = create_app()
    with app.app_context():
        updated = 0
        for order in Order.query.filter(Order.phone_digits.is_(None)).all():
            order.phone_digits = digits_only(order.phone)
            updated += 1

        if updated:
            db.session.commit()
        print(f"Updated orders: {updated}")


if __name__ == "__main__":
    main()
