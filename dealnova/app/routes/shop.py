# app/routes/shop.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from datetime import datetime
from urllib.parse import urlparse, quote
from ..models.product import Product
from ..models.shop import Shop
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
    # Keep public navigation state when legacy catalogue URLs reach the hub.
    filter_keys = (
        "cat", "sort", "kind", "min_price", "max_price", "promo", "stock", "shop", "page",
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
    return redirect(url_for("landing", open=universe, **state))


@bp.route("/")
def home():
    return _redirect_to_public_hub()


@bp.route("/promotions")
def promotions():
    return _redirect_to_public_hub("promotions")


_SOCIAL_AND_SEARCH_BOTS = (
    "facebookexternalhit",
    "whatsapp",
    "twitterbot",
    "telegrambot",
    "linkedinbot",
    "slackbot",
    "pinterest",
    "discordbot",
    "googlebot",
    "bingbot",
    "baiduspider",
    "yandexbot",
    "duckduckbot",
    "applebot",
    "skypeuripreview",
)


def _is_social_or_search_bot() -> bool:
    ua = (request.headers.get("User-Agent") or "").lower()
    return any(bot in ua for bot in _SOCIAL_AND_SEARCH_BOTS)


@bp.route("/product/<int:pid>")
def product_detail(pid):
    product = Product.query.get_or_404(pid)
    
    if not product.is_active:
        flash("Ce produit n'est plus disponible", "warning")
        return redirect(url_for("landing", open="products"))

    is_crawler = _is_social_or_search_bot()
    if not is_crawler and request.args.get("view") != "legacy":
        return redirect(url_for("landing", open="products", pdetail=pid))

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
