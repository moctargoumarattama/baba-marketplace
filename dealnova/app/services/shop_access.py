from flask import abort, flash, redirect, request, url_for

from ..models.shop import Shop, normalize_shop_type


def _wants_json_response() -> bool:
    return (
        request.is_json
        or request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
    )


def shop_allows_any(shop: Shop | None, *type_names: str) -> bool:
    if not shop:
        return False
    for type_name in type_names:
        normalized = normalize_shop_type(type_name)
        if normalized and shop.allows(normalized):
            return True
    return False


def resolve_vendor_shop(user) -> Shop | None:
    if not user or getattr(user, "is_authenticated", False) is False:
        return None
    if getattr(user, "role", None) != "vendor":
        return None
    shop = getattr(user, "shop", None)
    if shop is not None:
        return shop
    user_id = getattr(user, "id", None)
    if not user_id:
        return None
    return Shop.query.filter_by(vendor_id=user_id).first()


def ensure_vendor_allows(
    user,
    *type_names: str,
    fallback_endpoint: str | None = None,
    fallback_values: dict | None = None,
    strict_forbidden: bool = False,
):
    shop = resolve_vendor_shop(user)
    if shop_allows_any(shop, *type_names):
        return None

    message = "Non autorise pour votre type de boutique."
    if _wants_json_response():
        abort(403, description=message)

    flash(message, "warning")
    if strict_forbidden:
        abort(403, description=message)

    if fallback_endpoint:
        return redirect(url_for(fallback_endpoint, **(fallback_values or {})))

    referrer = (request.referrer or "").strip()
    if referrer:
        return redirect(referrer)
    return redirect(url_for("vendor.manage_shop"))


def ensure_shop_allows(
    shop: Shop | None,
    type_name: str,
    *,
    fallback_endpoint: str | None = None,
    fallback_values: dict | None = None,
):
    normalized = normalize_shop_type(type_name)
    type_label = Shop.type_label(normalized)

    if not shop:
        message = "Vous devez d'abord creer une boutique."
    elif normalized and shop.allows(normalized):
        return None
    else:
        message = f"Cette boutique n'autorise pas le type: {type_label}."

    if _wants_json_response():
        abort(403, description=message)

    flash(message, "warning")

    if fallback_endpoint:
        return redirect(url_for(fallback_endpoint, **(fallback_values or {})))

    referrer = (request.referrer or "").strip()
    if referrer:
        return redirect(referrer)

    endpoint = request.endpoint or ""
    if endpoint.startswith("vendor.") or endpoint.startswith("rentals.owner_"):
        return redirect(url_for("vendor.manage_shop"))
    return redirect(url_for("shop.home"))

