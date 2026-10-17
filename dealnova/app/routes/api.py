from datetime import datetime
import time

from flask import Blueprint, jsonify, request, current_app, render_template, url_for
from sqlalchemy import or_, case, func
from sqlalchemy.orm import selectinload
from ..models.product import Product
from ..models.shop import Shop
from ..models.category import Category
from ..models.rental import RentalListing
from ..services.marketplace_feed import search_public_locations, search_public_products
from ..services.public_catalog import build_public_catalog, parse_catalog_filters
from ..services.public_text import clean_shop_description
from ..services.pricing import (
    cents_to_money,
    final_price_cents,
    get_active_promos_for_products,
)
from ..services.pagination import limit_from_args
from ..services.traffic_stats import track_custom_event
from ..middleware.rate_limit import rate_limit
from .cart import get_cart, set_cart
from ..extensions import db

bp = Blueprint("api", __name__, url_prefix="/api")
PRODUCT_SEARCH_MIN_CHARS = 2
SECONDARY_SEARCH_MIN_CHARS = 3

# =====================================================
# HELPERS
# =====================================================

def _clean_str(value, max_length=100):
    """Nettoie et tronque une chaîne."""
    return (value or "").strip()[:max_length]


def _cart_total(cart):
    """Calcule le total du panier (optimisé)."""
    if not isinstance(cart, dict) or not cart:
        return 0

    qty_by_product_id = {}
    for key, value in cart.items():
        try:
            pid = int(key)
            qty = int(value)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            qty_by_product_id[pid] = qty

    if not qty_by_product_id:
        return 0

    products = Product.query.filter(Product.id.in_(list(qty_by_product_id.keys()))).all()
    promo_map = _active_promo_map([p.id for p in products])

    total_cents = 0
    for product in products:
        if (getattr(product, "kind", None) or "physical") == "service":
            continue
        qty = qty_by_product_id.get(product.id, 0)
        if qty <= 0:
            continue
        total_cents += final_price_cents(product, promo_map.get(product.id)) * qty
    return cents_to_money(total_cents)


def _active_promo_map(product_ids: list[int], now: datetime | None = None):
    _ = now
    return get_active_promos_for_products(product_ids)




# =====================================================
# RECHERCHE PRODUITS
# =====================================================

@bp.route("/catalog")
@rate_limit(limit=120, window_seconds=60, key_prefix="api_public_catalog_minute", methods=["GET"])
def public_catalog():
    try:
        filters = parse_catalog_filters(request.args)
    except ValueError as exc:
        return jsonify({"success": False, "error": "invalid_filters", "message": str(exc)}), 400
    return jsonify(build_public_catalog(filters))


@bp.route("/home-selection")
@rate_limit(limit=60, window_seconds=60, key_prefix="api_home_selection_minute", methods=["GET"])
def home_selection():
    from ..services.home_selection import get_home_selection

    selection = get_home_selection()
    response = jsonify(
        sections={
            kind: {
                "html": render_template("partials/_home_offer_grid.html", offer_items=selection[kind], offer_kind=kind),
                "count": len(selection[kind]),
            }
            for kind in ("products", "services")
        },
        refresh_after=selection["refresh_after"],
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/search/products")
@rate_limit(limit=300, window_seconds=3600, key_prefix="api_search_products_hour", methods=["GET"])
@rate_limit(limit=30, window_seconds=60, key_prefix="api_search_products_minute", methods=["GET"])
def search_products():
    """Recherche de produits (suggestions)."""
    q = _clean_str(request.args.get("q"))
    limit = min(limit_from_args(request.args, default=10), 50)  # ← Borne à 50 max

    if not q or len(q) < PRODUCT_SEARCH_MIN_CHARS:
        return jsonify({"products": []})

    start = time.time()
    results = search_public_products(search_q=q, limit=limit)
    
    duration = time.time() - start
    if duration > 0.3:  # Log si lent (>300ms)
        current_app.logger.info(f"Slow search/products: {duration:.2f}s for q='{q}'")
    
    return jsonify({"products": results})


# =====================================================
# RECHERCHE BOUTIQUES (OPTIMISÉE)
# =====================================================

@bp.route("/search/shops")
@rate_limit(limit=300, window_seconds=3600, key_prefix="api_search_shops_hour", methods=["GET"])
@rate_limit(limit=30, window_seconds=60, key_prefix="api_search_shops_minute", methods=["GET"])
def search_shops():
    """Recherche de boutiques avec compteurs (optimisé)."""
    q = _clean_str(request.args.get("q"))
    limit = min(limit_from_args(request.args, default=10), 50)

    if not q or len(q) < SECONDARY_SEARCH_MIN_CHARS:
        return jsonify({"shops": []})

    exact_name = Shop.name.ilike(q)
    prefix_name = Shop.name.ilike(f"{q}%")
    contains_name = Shop.name.ilike(f"%{q}%")

    shops = (
        Shop.query
        .filter(
            Shop.is_active == True,
            or_(exact_name, prefix_name, contains_name),
        )
        .order_by(
            case(
                (exact_name, 0),
                (prefix_name, 1),
                (contains_name, 2),
                else_=99,
            ),
            Shop.name.asc(),
        )
        .limit(limit)
        .all()
    )

    shop_ids = [shop.id for shop in shops]
    
    physical_counts = {}
    service_counts = {}
    location_counts = {}
    
    if shop_ids:
        # OPTIMISATION : Une seule requête pour les comptages produits
        # 🔧 CORRECTION ICI : je remplace le dict() problématique
        product_data = db.session.query(
            Product.shop_id,
            func.sum(case((Product.kind == "physical", 1), else_=0)).label('physical'),
            func.sum(case((Product.kind == "service", 1), else_=0)).label('service')
        ).filter(
            Product.shop_id.in_(shop_ids),
            Product.is_active == True
        ).group_by(Product.shop_id).all()
        
        # 🔧 CORRECTION ICI : construction manuelle du dictionnaire
        product_stats = {}
        for shop_id, phys, serv in product_data:
            product_stats[shop_id] = (phys or 0, serv or 0)
        
        for shop_id in shop_ids:
            phys, serv = product_stats.get(shop_id, (0, 0))
            physical_counts[shop_id] = int(phys)
            service_counts[shop_id] = int(serv)
        
        # Locations (inchangé - celui-ci fonctionne déjà car c'est une paire)
        location_counts = dict(
            db.session.query(RentalListing.shop_id, func.count(RentalListing.id))
            .filter(
                RentalListing.shop_id.in_(shop_ids),
                RentalListing.is_active == True,
                RentalListing.status.in_(["active", "reserved"]),
                RentalListing.expires_at > datetime.utcnow(),
            )
            .group_by(RentalListing.shop_id)
            .all()
        )

    results = []
    for s in shops:
        physical_count = physical_counts.get(s.id, 0)
        service_count = service_counts.get(s.id, 0)
        location_count = int(location_counts.get(s.id, 0) or 0)
        results.append({
            "id": s.id,
            "name": s.name,
            "slug": s.slug,
            "description": clean_shop_description(s.description),
            "physical_count": physical_count,
            "service_count": service_count,
            "location_count": location_count,
            "product_count": physical_count + service_count,
            "url": f"/{s.slug}",
            "logo": s.logo or "",
        })
    return jsonify({"shops": results})
# =====================================================
# RECHERCHE LOCATIONS
# =====================================================

@bp.route("/search/locations")
@rate_limit(limit=300, window_seconds=3600, key_prefix="api_search_locations_hour", methods=["GET"])
@rate_limit(limit=30, window_seconds=60, key_prefix="api_search_locations_minute", methods=["GET"])
def search_locations():
    """Recherche d'annonces de location."""
    q = _clean_str(request.args.get("q"))
    limit = min(limit_from_args(request.args, default=8), 30)

    if not q or len(q) < SECONDARY_SEARCH_MIN_CHARS:
        return jsonify({"locations": []})

    return jsonify({"locations": search_public_locations(search_q=q, limit=limit)})


# =====================================================
# RECHERCHE CATÉGORIES
# =====================================================

@bp.route("/search/categories")
@rate_limit(limit=300, window_seconds=3600, key_prefix="api_search_categories_hour", methods=["GET"])
@rate_limit(limit=30, window_seconds=60, key_prefix="api_search_categories_minute", methods=["GET"])
def search_categories():
    """Recherche de catégories."""
    q = _clean_str(request.args.get("q"))
    limit = min(limit_from_args(request.args, default=10), 30)

    if not q or len(q) < SECONDARY_SEARCH_MIN_CHARS:
        return jsonify({"categories": []})

    exact_name = Category.name.ilike(q)
    prefix_name = Category.name.ilike(f"{q}%")
    contains_name = Category.name.ilike(f"%{q}%")

    categories = (
        Category.query
        .filter(or_(exact_name, prefix_name, contains_name))
        .order_by(
            case(
                (exact_name, 0),
                (prefix_name, 1),
                (contains_name, 2),
                else_=99,
            ),
            Category.name.asc(),
        )
        .limit(limit)
        .all()
    )

    results = []
    for c in categories:
        results.append({
            "id": c.id,
            "name": c.name,
            "url": f"/shop?cat={c.id}",
        })
    return jsonify({"categories": results})


# =====================================================
# PANIER AJAX
# =====================================================

@bp.route("/cart/add/<int:pid>", methods=["POST"])
def add_to_cart(pid):
    """Ajoute un produit au panier (AJAX)."""
    product = Product.query.get_or_404(pid)
    if (getattr(product, "kind", None) or "physical") == "service":
        return jsonify({
            "success": False,
            "message": "Ce service se réserve. Merci de passer par la réservation.",
            "booking_url": f"/booking/{product.id}",
        })
    cart = get_cart()

    qty = cart.get(str(pid), 0)
    if hasattr(product, "stock") and product.stock <= qty:
        return jsonify({"success": False, "message": "Stock insuffisant"})

    cart[str(pid)] = qty + 1
    set_cart(cart)
    try:
        track_custom_event("add_to_cart")
    except Exception:
        pass

    return jsonify({
        "success": True,
        "product_qty": cart[str(pid)],
        "cart_count": sum(cart.values()),
        "total": _cart_total(cart),
    })


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


@bp.route("/cart/summary")
def cart_summary():
    """Résumé du panier (AJAX)."""
    cart = get_cart()
    return jsonify({
        "cart_count": sum(cart.values()),
        "total": _cart_total(cart)
    })


@bp.route("/product/<int:pid>")
def get_product_detail(pid):
    """Retourne les details complets d'un produit pour la modale Quick-View."""
    from urllib.parse import quote

    product = Product.query.get_or_404(pid)
    if not product.is_active:
        return jsonify({"success": False, "error": "Produit indisponible"}), 404

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
