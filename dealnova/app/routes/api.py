from datetime import datetime

from flask import Blueprint, jsonify, request, url_for
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from ..models.product import Product
from ..models.shop import Shop
from ..models.category import Category
from ..models.promo import Promo
from ..models.rental import RentalListing
from ..services.pricing import prix_final, compute_shipping_by_city, list_delivery_cities
from ..services.pagination import limit_from_args
from .cart import get_cart, set_cart
from ..extensions import db

bp = Blueprint("api", __name__, url_prefix="/api")


def _active_promo_map(product_ids: list[int], now: datetime | None = None) -> dict[int, Promo]:
    if not product_ids:
        return {}
    now_utc = now or datetime.utcnow()
    promos = (
        Promo.query
        .filter(
            Promo.product_id.in_(product_ids),
            Promo.end_date >= now_utc,
        )
        .order_by(Promo.product_id.asc(), Promo.end_date.asc())
        .all()
    )
    promo_map: dict[int, Promo] = {}
    for promo in promos:
        promo_map.setdefault(promo.product_id, promo)
    return promo_map


def _cart_total(cart):
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

    total = 0
    for product in products:
        if (getattr(product, "kind", None) or "physical") == "service":
            continue
        qty = qty_by_product_id.get(product.id, 0)
        if qty <= 0:
            continue
        promo = promo_map.get(product.id)
        total += prix_final(product, promo) * qty
    return total


def _delivery_price_payload(city_raw: str | None, source_raw: str | None):
    city = (city_raw or "").strip()
    source = (source_raw or "marketplace").strip().lower()
    if source not in {"marketplace", "special"}:
        source = "marketplace"

    if not city:
        return {
            "ok": False,
            "success": False,
            "city": "",
            "source": source,
            "price_cents": None,
            "price_display": "N/A",
            "message": "Ville obligatoire.",
            "cities": list_delivery_cities(),
        }, 400

    price_cents = int(compute_shipping_by_city(city))
    if price_cents <= 0:
        return {
            "ok": False,
            "success": False,
            "city": city,
            "source": source,
            "price_cents": None,
            "price_display": "N/A",
            "message": "Ville non supportee.",
            "cities": list_delivery_cities(),
        }, 400

    return {
        "ok": True,
        "success": True,
        "city": city,
        "source": source,
        "price_cents": price_cents,
        "price_dh": round(price_cents / 100, 2),
        "price_display": f"{price_cents / 100:.2f} MAD",
    }, 200


@bp.route("/pricing/delivery")
def pricing_delivery():
    payload, status = _delivery_price_payload(
        request.args.get("city"),
        request.args.get("source"),
    )
    return jsonify(payload), status


@bp.route("/delivery/price")
def delivery_price():
    payload, status = _delivery_price_payload(
        request.args.get("city"),
        request.args.get("source"),
    )
    return jsonify(payload), status


# --- Produits ---
@bp.route("/search/products")
def search_products():
    q = request.args.get("q", "").strip()
    limit = limit_from_args(request.args, default=10)
    if not q:
        return jsonify({"products": []})

    products = (
        Product.query
        .options(
            selectinload(Product.shop),
            selectinload(Product.category),
        )
        .filter(
            Product.is_active == True,
            or_(
                Product.name.ilike(f"%{q}%"),
                Product.description.ilike(f"%{q}%"),
            ),
        )
        .limit(limit)
        .all()
    )
    promo_map = _active_promo_map([p.id for p in products])

    results = []
    for p in products:
        kind = (getattr(p, "kind", None) or "physical")
        is_service = kind == "service"
        promo = promo_map.get(p.id)
        final_price = prix_final(p, promo)
        promo_value = promo.value if promo else 0
        promo_type = promo.type if promo else None

        results.append({
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "final_price": final_price,
            "promo_value": promo_value,
            "promo_type": promo_type,
            "shop_name": p.shop.name if p.shop else "N/A",
            "category": p.category.name if p.category else "",
            "stock": p.stock if hasattr(p, "stock") else None,
            "url": f"/shop/product/{p.id}",
            "image_file": p.image_file.split('|')[0] if p.image_file else "",
            "kind": kind,
            "can_add_to_cart": not is_service,
            "booking_url": f"/booking/{p.id}" if is_service else None,
            "default_quantity": 1,
        })
    return jsonify({"products": results})


# --- Boutiques ---
@bp.route("/search/shops")
def search_shops():
    q = request.args.get("q", "").strip()
    limit = limit_from_args(request.args, default=10)
    if not q:
        return jsonify({"shops": []})

    shops = Shop.query.filter(
        Shop.is_active == True,
        Shop.name.ilike(f"%{q}%")
    ).limit(limit).all()

    shop_ids = [shop.id for shop in shops]
    physical_counts = {}
    service_counts = {}
    location_counts = {}
    if shop_ids:
        physical_counts = dict(
            db.session.query(Product.shop_id, db.func.count(Product.id))
            .filter(
                Product.shop_id.in_(shop_ids),
                Product.is_active == True,
                Product.kind == "physical",
            )
            .group_by(Product.shop_id)
            .all()
        )
        service_counts = dict(
            db.session.query(Product.shop_id, db.func.count(Product.id))
            .filter(
                Product.shop_id.in_(shop_ids),
                Product.is_active == True,
                Product.kind == "service",
            )
            .group_by(Product.shop_id)
            .all()
        )
        location_counts = dict(
            db.session.query(RentalListing.shop_id, db.func.count(RentalListing.id))
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
        physical_count = int(physical_counts.get(s.id, 0) or 0)
        service_count = int(service_counts.get(s.id, 0) or 0)
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
            "url": f"/shop/{s.slug}",
            "logo": s.logo or "",
        })
    return jsonify({"shops": results})


@bp.route("/search/locations")
def search_locations():
    q = request.args.get("q", "").strip()
    limit = limit_from_args(request.args, default=8)
    if not q:
        return jsonify({"locations": []})

    listings = (
        RentalListing.query
        .options(selectinload(RentalListing.media), selectinload(RentalListing.shop))
        .join(Shop, Shop.id == RentalListing.shop_id)
        .filter(
            RentalListing.is_active == True,
            RentalListing.status.in_(["active", "reserved"]),
            RentalListing.expires_at > datetime.utcnow(),
            Shop.is_active == True,
            Shop.sql_allows_clause("location"),
            or_(
                RentalListing.title.ilike(f"%{q}%"),
                RentalListing.city.ilike(f"%{q}%"),
                RentalListing.area.ilike(f"%{q}%"),
            ),
        )
        .order_by(RentalListing.created_at.desc())
        .limit(limit)
        .all()
    )

    results = []
    for listing in listings:
        cover = ""
        if getattr(listing, "media", None):
            for media in listing.media:
                if media.kind == "image" and media.file_path:
                    cover = media.file_path
                    break
        cover_url = ""
        if cover:
            normalized_cover = str(cover).replace("\\", "/").lstrip("/")
            if normalized_cover.startswith(("http://", "https://")):
                cover_url = normalized_cover
            elif normalized_cover.startswith("static/"):
                cover_url = f"/{normalized_cover}"
            elif normalized_cover.startswith("uploads/"):
                cover_url = url_for("static", filename=normalized_cover)
            else:
                cover_url = url_for("static", filename=f"uploads/rentals/{normalized_cover}")
        results.append({
            "id": listing.id,
            "title": listing.title,
            "city": listing.city,
            "area": listing.area or "",
            "rent_cents": int(listing.rent_cents or 0),
            "rent_dh": round((listing.rent_cents or 0) / 100, 2),
            "listing_type": listing.listing_type,
            "url": url_for("rentals.location_detail", slug=listing.slug),
            "shop_name": listing.shop.name if listing.shop else "",
            "cover": cover,
            "cover_url": cover_url,
        })

    return jsonify({"locations": results})


# --- Categories ---
@bp.route("/search/categories")
def search_categories():
    q = request.args.get("q", "").strip()
    limit = limit_from_args(request.args, default=10)
    if not q:
        return jsonify({"categories": []})

    categories = Category.query.filter(
        Category.name.ilike(f"%{q}%")
    ).limit(limit).all()

    results = []
    for c in categories:
        results.append({
            "id": c.id,
            "name": c.name,
            "url": f"/shop?cat={c.id}",
        })
    return jsonify({"categories": results})


# --- Ajout panier AJAX ---
@bp.route("/cart/add/<int:pid>", methods=["POST"])
def add_to_cart(pid):
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

    return jsonify({
        "success": True,
        "product_qty": cart[str(pid)],
        "cart_count": sum(cart.values()),
        "total": _cart_total(cart),
    })


# --- Resume panier AJAX ---
@bp.route("/cart/summary")
def cart_summary():
    cart = get_cart()
    return jsonify({"cart_count": sum(cart.values()), "total": _cart_total(cart)})
