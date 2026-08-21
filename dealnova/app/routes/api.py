from datetime import datetime
import time

from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import or_, case, func
from ..models.product import Product
from ..models.shop import Shop
from ..models.category import Category
from ..models.rental import RentalListing
from ..services.marketplace_feed import search_public_locations, search_public_products
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
            "description": s.description or "",
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
