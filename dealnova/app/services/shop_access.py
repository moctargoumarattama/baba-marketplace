from datetime import datetime
import re

from flask import abort, flash, redirect, request, url_for

from ..models.shop import Shop, normalize_shop_type

PUBLIC_SHOP_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")

RESERVED_ROOT_SHOP_SLUGS = {
    "admin",
    "admin-access",
    "apple-touch-icon.png",
    "api",
    "booking",
    "cart",
    "delivery",
    "health",
    "lang",
    "location",
    "locations",
    "login",
    "logout",
    "manifest.json",
    "maintenance",
    "register",
    "search",
    "shop",
    "shops",
    "signin",
    "signup",
    "sitemap.xml",
    "sw.js",
    "vendor",
    "vendeur",
    "vendeurs",
    "inscription",
    "connexion",
}


def normalize_public_shop_slug(value: str | None) -> str:
    return str(value or "").strip().strip("/").lower()


def is_safe_public_shop_slug(value: str | None, *, reserved: set[str] | None = None) -> bool:
    slug = normalize_public_shop_slug(value)
    if not slug or "." in slug:
        return False
    if reserved and slug in reserved:
        return False
    return bool(PUBLIC_SHOP_SLUG_RE.fullmatch(slug))


def shop_is_currently_open(shop: Shop | None, *, default_if_missing: bool = False) -> bool:
    if not shop:
        return default_if_missing
    if getattr(shop, "is_active", True) is False:
        return False
    now = datetime.utcnow()
    closed_until = getattr(shop, "closed_until", None)
    if closed_until and closed_until > now:
        return False
    if hasattr(shop, "is_open_now") and callable(getattr(shop, "is_open_now")):
        return bool(shop.is_open_now())
    return bool(getattr(shop, "is_open", True))


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


def _sanitize_shop_slug(raw_value: str | None, fallback_name: str | None = None) -> str:
    from slugify import slugify
    candidate = slugify((raw_value or "").strip())
    if not candidate and fallback_name:
        candidate = slugify((fallback_name or "").strip())
    return candidate


def _build_unique_shop_slug(name: str, *, exclude_shop_id: int | None = None) -> str:
    base_slug = _sanitize_shop_slug(None, fallback_name=name) or "boutique"
    slug = base_slug
    counter = 1

    while True:
        if slug.lower() in RESERVED_ROOT_SHOP_SLUGS:
            slug = f"{base_slug}-{counter}"
            counter += 1
            continue
        query = Shop.query.filter_by(slug=slug)
        if exclude_shop_id is not None:
            query = query.filter(Shop.id != exclude_shop_id)
        if not query.first():
            return slug

        slug = f"{base_slug}-{counter}"
        counter += 1
        if counter > 999:
            slug = f"{base_slug}-{int(datetime.utcnow().timestamp())}"


_USERNAME_SAFE_RE = re.compile(r"[^a-z0-9_]+")


def _unique_vendor_username(base: str | None) -> str:
    from slugify import slugify
    from ..models.user import User

    seed = _USERNAME_SAFE_RE.sub("_", slugify((base or "").strip() or "vendeur", separator="_").lower())
    seed = re.sub(r"_+", "_", seed).strip("_")
    if not seed:
        seed = "vendeur"
    if len(seed) < 3:
        seed = f"{seed}_user"
    seed = seed[:40]

    candidate = seed
    counter = 1
    while User.query.filter_by(username=candidate).first():
        suffix = f"_{counter}"
        candidate = f"{seed[: max(1, 50 - len(suffix))]}{suffix}"
        counter += 1
        if counter > 2000:
            candidate = f"vendor_{int(datetime.utcnow().timestamp())}"
            if not User.query.filter_by(username=candidate).first():
                break
    return candidate


def _shop_types_from_vendor_application(shop_type_text: str | None):
    from ..models.shop import SHOP_TYPE_ORDER, normalize_allowed_shop_types

    raw = (shop_type_text or "").strip().lower()
    if not raw:
        return "products", ["products"]

    allowed: list[str] = []
    has_mix = any(token in raw for token in ("mix", "multi", "tous", "all"))
    if has_mix:
        return "products", list(SHOP_TYPE_ORDER)

    if any(token in raw for token in ("produit", "product", "marchandise", "article")):
        allowed.append("products")
    if any(token in raw for token in ("service", "prestation")):
        allowed.append("services")
    if any(token in raw for token in ("location", "rental", "locatif", "louer", "louage")):
        allowed.append("location")

    normalized_allowed = normalize_allowed_shop_types(allowed, primary_type=allowed[0] if allowed else "products")
    primary_type = normalized_allowed[0] if normalized_allowed else "products"
    return primary_type, normalized_allowed or ["products"]


def _create_shop_for_vendor(
    vendor,
    *,
    name: str,
    description: str = "",
    contact_email: str = "",
    contact_phone: str = "",
    address: str = "",
    primary_type: str = "products",
    allowed_types: list[str] | None = None,
) -> Shop:
    from ..extensions import db
    from ..models.product import Product
    from ..models.shop import normalize_allowed_shop_types

    normalized_primary = normalize_shop_type(primary_type) or "products"
    normalized_allowed = normalize_allowed_shop_types(allowed_types, primary_type=normalized_primary)

    shop = Shop(
        vendor_id=vendor.id,
        name=name.strip(),
        slug=_build_unique_shop_slug(name),
        description=(description or "").strip() or None,
        contact_email=(contact_email or "").strip() or None,
        contact_phone=(contact_phone or "").strip() or getattr(vendor, "phone", None) or None,
        address=(address or "").strip() or getattr(vendor, "address", None) or None,
        primary_type=normalized_primary,
        is_active=True,
        is_open=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    shop.set_allowed_types(normalized_allowed)

    db.session.add(shop)
    db.session.flush()

    Product.query.filter_by(vendor_id=vendor.id).update(
        {"shop_id": shop.id},
        synchronize_session=False,
    )
    return shop

