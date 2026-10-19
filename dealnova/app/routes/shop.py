# app/routes/shop.py
from flask import Blueprint, render_template, request, redirect, url_for, current_app
from urllib.parse import urlparse, quote
from ..models.product import Product
from ..services.pricing import prix_final, get_active_promo
from ..services.shop_access import shop_is_currently_open

bp = Blueprint("shop", __name__)


def _is_valid_back_path(path: str | None) -> bool:
    clean = (path or "").strip()
    if not clean.startswith("/") or clean.startswith("//"):
        return False
    lowered = clean.lower()
    if lowered.startswith("/static/"):
        return False
    if lowered.startswith("/sw.js"):
        return False
    if lowered.startswith("/manifest.json"):
        return False
    if lowered.endswith(".js") or lowered.endswith(".css") or lowered.endswith(".map"):
        return False
    return True


def _safe_local_back_target(raw_target: str | None, fallback: str) -> str:
    target = (raw_target or "").strip()
    if _is_valid_back_path(target):
        return target
    if target.startswith("http://") or target.startswith("https://"):
        try:
            parsed = urlparse(target)
            if _is_valid_back_path(parsed.path):
                if parsed.netloc == request.host:
                    suffix = f"?{parsed.query}" if parsed.query else ""
                    return f"{parsed.path}{suffix}"
        except Exception:
            pass
    return fallback


def _delivery_whatsapp_number() -> str:
    raw = (
        current_app.config.get("DELIVERY_WHATSAPP_NUMBER")
        or "212602908954"
    )
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits or "212602908954"


def _delivery_whatsapp_prefill_message() -> str:
    configured = (current_app.config.get("DELIVERY_WHATSAPP_DEFAULT_MESSAGE") or "").strip()
    if configured:
        return configured
    return "Bonjour, je souhaite programmer une livraison. Merci de me confirmer la disponibilite et le delai."


@bp.route("/delivery/whatsapp")
def delivery_whatsapp_loader():
    back_target = _safe_local_back_target(
        request.args.get("back") or request.referrer,
        url_for("landing"),
    )
    wa_url = (
        f"https://wa.me/{_delivery_whatsapp_number()}?text="
        f"{quote(_delivery_whatsapp_prefill_message(), safe='')}"
    )
    return render_template(
        "support/delivery_whatsapp_loader.html",
        wa_url=wa_url,
        back_url=back_target,
        delay_seconds=2,
    )


def _redirect_to_public_hub(default_universe: str = "products"):
    # Keep legacy filters and modal deep links while consolidating catalogue URLs.
    filter_keys = (
        "cat", "sort", "kind", "min_price", "max_price", "promo", "stock", "shop", "page",
        "city", "type", "listing_type", "property_type", "min", "max", "per_page",
    )
    state_keys = ("q", *filter_keys, "pdetail", "sdetail", "slug")
    state = {
        key: value
        for key in state_keys
        if (value := (request.args.get(key) or "").strip())
    }
    requested_universe = (request.args.get("open") or "").strip().lower()
    allowed_universes = {
        "products", "services", "locations", "shops", "delivery", "promotions",
        "search", "cart", "checkout", "shop",
    }
    if requested_universe in allowed_universes:
        universe = requested_universe
    elif default_universe == "promotions" or state.get("promo") == "1":
        universe = "promotions"
    elif state.get("kind", "").lower() == "service":
        universe = "services"
    elif state.get("q") and not any(state.get(key) for key in filter_keys):
        universe = "search"
    else:
        universe = default_universe
    from ..services.public_seo import CATALOG_ENDPOINTS

    if any(state.get(key) for key in ("pdetail", "sdetail", "slug")):
        # Old shared modal links still need their detail state consumed by the
        # existing hub. A catalogue document alone would drop that state.
        return redirect(url_for("landing", open=universe, **state))

    endpoint = CATALOG_ENDPOINTS.get(universe)
    if endpoint:
        # The universe already belongs to the URL. Keep modal-only destinations
        # on the existing hub (cart, checkout, delivery, or one shop).
        return redirect(url_for(endpoint, **state), code=301)
    return redirect(url_for("landing", open=universe, **state))


@bp.route("/")
def home():
    return _redirect_to_public_hub()


@bp.route("/promotions")
def promotions():
    return _redirect_to_public_hub("promotions")


@bp.route("/product/<int:pid>")
def product_detail(pid):
    from ..services.marketplace_feed import _base_product_query

    query, _, _, _, _ = _base_product_query(
        search_q="", category_id=None, kind="", min_price=None, max_price=None,
        promo_only="0", in_stock="0", shop_id=None,
    )
    product = query.filter(Product.kind.in_(("physical", "service")), Product.id == pid).first_or_404()

    shop_is_open_now = shop_is_currently_open(getattr(product, "shop", None), default_if_missing=True)
    promo = get_active_promo(pid)
    final = prix_final(product, promo)

    return render_template(
        "shop/product_detail.html",
        product=product,
        shop_is_open_now=shop_is_open_now,
        final=final,
        promo=promo,
    )
