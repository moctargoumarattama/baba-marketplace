"""Keep historical customer sessions in guest mode without losing their basket."""

from flask import session

from ..models.user import User


def load_account_user(user):
    if user is None or (user.role or "").strip().lower() in User.ALLOWED_ROLES:
        return user

    cart = {}
    sources = [session.get(f"cart_user_{user.id}", {})]
    sources.extend(value for key, value in session.items()
                   if key == "cart_guest" or key.startswith("cart_guest_"))
    for source in sources:
        if not isinstance(source, dict):
            continue
        for product_id, quantity in source.items():
            try:
                pid, count = int(product_id), int(quantity)
            except (ValueError, TypeError):
                continue
            if pid > 0 and count > 0:
                key = str(pid)
                cart[key] = max(cart.get(key, 0), count)
    if cart:
        session["cart_guest"] = cart
    session.pop(f"cart_user_{user.id}", None)
    for key in ("_user_id", "_fresh", "_id", "_remember_seconds"):
        session.pop(key, None)
    session["_remember"] = "clear"
    return None
