from datetime import datetime

from flask import Blueprint, jsonify, request, current_app, url_for
from sqlalchemy.orm import selectinload
from ..models.product import Product
from ..models.shop import Shop
from ..services.public_catalog import build_public_catalog, parse_catalog_filters
from ..services.public_text import clean_shop_description
from ..services.pricing import (
    cents_to_money,
    final_price_cents,
    get_active_promos_for_products,
)
from ..services.traffic_stats import track_custom_event
from ..middleware.rate_limit import rate_limit

bp = Blueprint("api", __name__, url_prefix="/api")

# =====================================================
# HELPERS
# =====================================================

def _clean_str(value, max_length=100):
    """Nettoie et tronque une chaîne."""
    return (value or "").strip()[:max_length]


def _active_promo_map(product_ids: list[int], now: datetime | None = None):
    _ = now
    return get_active_promos_for_products(product_ids)


# =====================================================
# CATALOGUE PUBLIC & ANALYTICS
# =====================================================

@bp.route("/catalog")
@rate_limit(limit=120, window_seconds=60, key_prefix="api_public_catalog_minute", methods=["GET"])
def public_catalog():
    try:
        filters = parse_catalog_filters(request.args)
    except ValueError as exc:
        return jsonify({"success": False, "error": "invalid_filters", "message": str(exc)}), 400
    return jsonify(build_public_catalog(filters))


@bp.route("/analytics/event", methods=["POST"])
def analytics_event():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}

    event_name = _clean_str(payload.get("event"), max_length=40).lower()
    if not event_name:
        return jsonify({"ok": False, "error": "missing_event"}), 400

    try:
        track_custom_event(event_name)
    except Exception:
        return jsonify({"ok": False, "error": "track_failed"}), 500

    return jsonify({"ok": True})


@bp.route("/product/<int:pid>")
def get_product_detail(pid):
    """Retourne les details complets d'un produit pour la modale Quick-View."""
    from urllib.parse import quote

    from ..services.marketplace_feed import _base_product_query

    query, _, _, _, _ = _base_product_query(
        search_q="", category_id=None, kind="", min_price=None, max_price=None,
        promo_only="0", in_stock="0", shop_id=None,
    )
    product = query.filter(Product.kind.in_(("physical", "service")), Product.id == pid).first_or_404()

    promo_map = _active_promo_map([product.id])
    promo = promo_map.get(product.id)
    final_cents = final_price_cents(product, promo)
    final_price = float(cents_to_money(final_cents))
    original_price = float(cents_to_money(getattr(product, "price_cents", 0) or 0))

    raw_images = (product.image_file or "").split("|") if product.image_file else []
    images = [img.strip() for img in raw_images if img.strip()]

    delivery_wa = current_app.config.get("DELIVERY_WHATSAPP_NUMBER") or "212602908954"
    clean_wa = "".join(ch for ch in str(delivery_wa) if ch.isdigit()) or "212602908954"
    wa_message = f"Bonjour Baba Market, je souhaite commander : {product.name} ({final_price:.2f} DH)"

    shop = getattr(product, "shop", None)
    shop_data = None
    if shop:
        shop_data = {
            "id": shop.id,
            "name": shop.name,
            "slug": shop.slug,
            "logo": shop.logo,
            "rating": getattr(shop, "rating", None),
            "is_verified": bool(getattr(shop, "is_verified", False)),
            "contact_phone": getattr(shop, "contact_phone", None),
        }

    video_url = None
    if getattr(product, "video_file", None):
        clean_video = str(product.video_file).strip()
        if clean_video:
            if clean_video.startswith("/static/"):
                video_url = clean_video
            elif clean_video.startswith("http://") or clean_video.startswith("https://"):
                video_url = clean_video
            elif clean_video.startswith("uploads/"):
                video_url = url_for("static", filename=clean_video)
            else:
                video_url = url_for("static", filename=f"uploads/product_videos/{clean_video}")

    return jsonify({
        "success": True,
        "product": {
            "id": product.id,
            "name": product.name,
            "share_url": url_for("shop.product_detail", pid=product.id, _external=True),
            "description": product.description or "Aucune description disponible pour cet article.",
            "price": original_price,
            "final_price": final_price,
            "has_promo": bool(promo),
            "promo_value": getattr(promo, "value", None) if promo else None,
            "promo_type": getattr(promo, "type", None) if promo else None,
            "discount_amount": round(original_price - final_price, 2) if promo and original_price > final_price else 0,
            "stock": getattr(product, "stock", 0) or 0,
            "kind": getattr(product, "kind", "physical") or "physical",
            "images": images,
            "image_download_urls": [url_for("shop.download_product_photo", pid=product.id, image_index=index)
                                    for index in range(len(images))],
            "video_url": video_url,
            "has_video": bool(video_url),
            "category": product.category.name if getattr(product, "category", None) else "",
            "shop": shop_data,
            "whatsapp_order_url": f"https://wa.me/{clean_wa}?text={quote(wa_message)}",
            "booking_url": f"/booking/{product.id}" if getattr(product, "kind", None) == "service" else None,
        }
    })


@bp.route("/shop/<string:shop_slug_or_id>")
def get_shop_detail(shop_slug_or_id):
    """Retourne les details d'une boutique et ses produits pour la modale Vitrine Boutique."""
    from urllib.parse import quote
    from ..services.shop_access import normalize_public_shop_slug

    clean_param = (shop_slug_or_id or "").strip()
    shop = None
    if clean_param.isdigit():
        shop = Shop.query.filter_by(id=int(clean_param), is_active=True).first()
    if not shop:
        normalized_slug = normalize_public_shop_slug(clean_param)
        shop = Shop.query.filter_by(slug=normalized_slug, is_active=True).first()
    if not shop:
        return jsonify({"success": False, "error": "Boutique non trouvee"}), 404

    # Statut d ouverture
    now = datetime.utcnow()
    if shop.closed_until and shop.closed_until > now:
        is_open = False
    elif hasattr(shop, "is_open_now") and callable(getattr(shop, "is_open_now")):
        is_open = bool(shop.is_open_now())
    else:
        is_open = bool(getattr(shop, "is_open", True))

    # Contact WhatsApp & Telephone
    shop_phone = (shop.contact_phone or "").strip()
    clean_phone = "".join(ch for ch in shop_phone if ch.isdigit())
    default_wa = current_app.config.get("DELIVERY_WHATSAPP_NUMBER") or "212602908954"
    clean_default_wa = "".join(ch for ch in str(default_wa) if ch.isdigit()) or "212602908954"
    target_wa = clean_phone if (clean_phone and len(clean_phone) >= 8) else clean_default_wa

    wa_msg = f"Bonjour {shop.name}, je vous contacte depuis Baba Market"
    whatsapp_url = f"https://wa.me/{target_wa}?text={quote(wa_msg)}"

    # Produits de la boutique
    preview = request.args.get("preview") == "1"
    products_query = (
        Product.query.filter_by(shop_id=shop.id, is_active=True)
        .options(selectinload(Product.category))
        .order_by(Product.created_at.desc(), Product.id.desc())
    )
    if preview:
        products_query = products_query.filter(Product.kind.in_(("physical", "service")))
        product_count = products_query.order_by(None).count()
        products_query = products_query.limit(6)
    products = products_query.all()
    if not preview:
        product_count = len(products)
    product_ids = [p.id for p in products]
    promo_map = _active_promo_map(product_ids)

    products_data = []
    for p in products:
        promo = promo_map.get(p.id)
        final_cents = final_price_cents(p, promo)
        final_price = float(cents_to_money(final_cents))
        orig_price = float(cents_to_money(getattr(p, "price_cents", 0) or 0))

        raw_imgs = (p.image_file or "").split("|") if p.image_file else []
        first_img = raw_imgs[0].strip() if raw_imgs else ""

        products_data.append({
            "id": p.id,
            "name": p.name,
            "description": p.description or "",
            "price": orig_price,
            "final_price": final_price,
            "has_promo": bool(promo),
            "discount_amount": round(orig_price - final_price, 2) if promo and orig_price > final_price else 0,
            "stock": getattr(p, "stock", 0) or 0,
            "kind": getattr(p, "kind", "physical") or "physical",
            "image": first_img,
            "category": p.category.name if getattr(p, "category", None) else "",
        })

    return jsonify({
        "success": True,
        "shop": {
            "id": shop.id,
            "name": shop.name,
            "slug": shop.slug,
            "share_url": url_for("shops.shop_detail", shop_slug=shop.slug, _external=True),
            "logo": shop.logo,
            "banner": shop.banner,
            "description": clean_shop_description(shop.description),
            "address": shop.address or "Rabat • Salé",
            "contact_phone": shop_phone,
            "rating": getattr(shop, "rating", None),
            "review_count": getattr(shop, "review_count", 0),
            "is_verified": bool(getattr(shop, "is_verified", False)),
            "is_open": is_open,
            "whatsapp_url": whatsapp_url,
            "call_url": f"tel:{shop_phone}" if shop_phone else None,
        },
        "products": products_data,
        "product_count": product_count,
        "products_preview": preview,
    })
