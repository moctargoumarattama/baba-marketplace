# app/routes/shops.py - NOUVEAU FICHIER
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify
from sqlalchemy.orm import selectinload
from ..extensions import db
from ..models.shop import Shop
from ..models.product import Product
from ..models.category import Category
from ..models.rental import RentalListing
from ..services.cache import get_catalog_cache
from ..services.pagination import SimplePagination, page_from_args
bp = Blueprint("shops", __name__)


def _shop_is_currently_open(shop: Shop | None) -> bool:
    if not shop:
        return True
    if getattr(shop, "is_active", True) is False:
        return False
    now = datetime.utcnow()
    closed_until = getattr(shop, "closed_until", None)
    if closed_until and closed_until > now:
        return False
    return getattr(shop, "is_open", True) is True


def _is_ajax_request() -> bool:
    requested_with = (request.headers.get("X-Requested-With") or "").strip()
    return requested_with in ("fetch", "XMLHttpRequest")


@bp.route("/shops")
def list_shops():
    """Liste toutes les boutiques actives"""
    page = page_from_args(request.args)
    q = (request.args.get("q") or "").strip()
    kind = (request.args.get("kind") or "").strip().lower()
    if kind not in ("physical", "service", "location"):
        kind = ""

    per_page = 12

    def build_shops_payload():
        query = Shop.query.filter_by(is_active=True)
        if q:
            query = query.filter(
                Shop.name.ilike(f"%{q}%") | 
                Shop.description.ilike(f"%{q}%")
            )

        if kind:
            if kind == "physical":
                query = query.filter(Shop.sql_allows_clause("products"))
                shop_ids_subq = (
                    db.session.query(Product.shop_id)
                    .filter(Product.is_active == True, Product.kind == "physical")
                    .distinct()
                )
                query = query.filter(Shop.id.in_(shop_ids_subq))
            elif kind == "service":
                query = query.filter(Shop.sql_allows_clause("services"))
                shop_ids_subq = (
                    db.session.query(Product.shop_id)
                    .filter(Product.is_active == True, Product.kind == "service")
                    .distinct()
                )
                query = query.filter(Shop.id.in_(shop_ids_subq))
            elif kind == "location":
                now = datetime.utcnow()
                query = query.filter(Shop.sql_allows_clause("location"))
                location_shop_ids_subq = (
                    db.session.query(RentalListing.shop_id)
                    .filter(
                        RentalListing.is_active == True,
                        RentalListing.status.in_(["active", "reserved"]),
                        RentalListing.expires_at > now,
                    )
                    .distinct()
                )
                query = query.filter(Shop.id.in_(location_shop_ids_subq))

        pagination = query.order_by(
            Shop.is_verified.desc(), 
            Shop.rating.desc(), 
            Shop.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        shops_page = pagination.items
        shop_ids = [s.id for s in shops_page]
        physical_counts = {}
        service_counts = {}
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
            now = datetime.utcnow()
            location_counts = dict(
                db.session.query(RentalListing.shop_id, db.func.count(RentalListing.id))
                .filter(
                    RentalListing.shop_id.in_(shop_ids),
                    RentalListing.is_active == True,
                    RentalListing.status.in_(["active", "reserved"]),
                    RentalListing.expires_at > now,
                )
                .group_by(RentalListing.shop_id)
                .all()
            )
        else:
            location_counts = {}

        shops_data = []
        for shop in shops_page:
            physical_count = physical_counts.get(shop.id, 0)
            service_count = service_counts.get(shop.id, 0)
            location_count = int(location_counts.get(shop.id, 0) or 0)
            address = (shop.address or "").strip()
            allowed_types = shop.get_allowed_types()
            can_show_service_location = ("services" in allowed_types) and ("products" not in allowed_types)
            shops_data.append({
                "id": shop.id,
                "name": shop.name,
                "slug": shop.slug,
                "logo": shop.logo,
                "banner": shop.banner,
                "description": shop.description,
                "rating": shop.rating,
                "is_verified": shop.is_verified,
                "contact_phone": shop.contact_phone,
                "address": address,
                "service_location_note": ((shop.service_location_note or "").strip() if can_show_service_location else ""),
                "service_latitude": (shop.service_latitude if can_show_service_location else None),
                "service_longitude": (shop.service_longitude if can_show_service_location else None),
                "service_map_url": (shop.service_map_url if can_show_service_location else ""),
                "is_open_now": _shop_is_currently_open(shop),
                "physical_count": physical_count,
                "service_count": service_count,
                "location_count": location_count,
                "product_count": physical_count + service_count,
                "allowed_types": allowed_types,
                "primary_type": shop.primary_type,
            })

        return {
            "shops": shops_data,
            "total": pagination.total,
            "per_page": per_page
        }

    cache_key = f"shops_list:{page}:{q}:{kind}"
    payload = get_catalog_cache(cache_key, build_shops_payload, timeout=120)
    shops = payload.get("shops", [])
    pagination = SimplePagination(page, payload.get("per_page", per_page), payload.get("total", 0))

    template_name = "partials/_shops_listing.html" if _is_ajax_request() else "shop/shops.html"
    return render_template(
        template_name,
        shops=shops,
        pagination=pagination,
        q=q,
        kind=kind,
    )


@bp.route("/shop/<string:shop_slug>")
def shop_detail(shop_slug):
    """Détail d'une boutique avec ses produits"""
    shop = Shop.query.filter_by(slug=shop_slug, is_active=True).first_or_404()
    shop_allows_products = shop.allows("products")
    shop_allows_services = shop.allows("services")
    shop_allows_location = shop.allows("location")
    service_location_url = shop.service_map_url if (shop_allows_services and not shop_allows_products) else ""
    shop_is_open_now = _shop_is_currently_open(shop)
    has_product_universe = shop_allows_products or shop_allows_services
    
    # Récupérer les produits de la boutique
    page = page_from_args(request.args)
    cat = request.args.get("cat", type=int)
    q = (request.args.get("q") or "").strip()
    sort = (request.args.get("sort") or "").strip()
    kind = (request.args.get("kind") or "").strip().lower()
    if kind not in ("physical", "service"):
        kind = ""
    if kind == "physical" and not shop_allows_products:
        kind = ""
    if kind == "service" and not shop_allows_services:
        kind = ""
    ajax = request.args.get("ajax", type=int)
    
    base_query = Product.query.filter(Product.shop_id == shop.id, Product.is_active == True)
    if shop_allows_products and not shop_allows_services:
        base_query = base_query.filter(Product.kind == "physical")
    elif shop_allows_services and not shop_allows_products:
        base_query = base_query.filter(Product.kind == "service")
    elif not has_product_universe:
        base_query = base_query.filter(Product.id == -1)
    query = base_query

    if kind:
        query = query.filter(Product.kind == kind)
    
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    
    if cat:
        query = query.filter_by(category_id=cat)
    
    # Tri
    if sort == "new":
        query = query.order_by(Product.created_at.desc())
    elif sort == "low":
        query = query.order_by(Product.price.asc())
    elif sort == "high":
        query = query.order_by(Product.price.desc())
    else:
        query = query.order_by(Product.created_at.desc())
    
    # Pagination
    per_page = 12
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Total produits
    total_products = query.order_by(None).count()
    
    # Si requête AJAX, retourner JSON
    if ajax:
        products_html = render_template(
            "shop/_products_partial.html",
            products=pagination.items
        )
        return jsonify({
            'products': products_html,
            'total': total_products,
            'has_more': pagination.has_next
        })

    # Totaux boutique (tous articles actifs)
    kind_totals = dict(
        db.session.query(Product.kind, db.func.count(Product.id))
        .filter(Product.shop_id == shop.id, Product.is_active == True)
        .group_by(Product.kind)
        .all()
    )
    shop_physical_total = kind_totals.get("physical", 0) if shop_allows_products else 0
    shop_service_total = kind_totals.get("service", 0) if shop_allows_services else 0
    shop_total_items = shop_physical_total + shop_service_total

    # Catégories + compteurs (pour filtrage Produits/Services côté UI)
    categories_query = (
        Category.query.join(Product)
        .filter(Product.shop_id == shop.id, Product.is_active == True)
    )
    if shop_allows_products and not shop_allows_services:
        categories_query = categories_query.filter(Product.kind == "physical")
    elif shop_allows_services and not shop_allows_products:
        categories_query = categories_query.filter(Product.kind == "service")
    elif not has_product_universe:
        categories_query = categories_query.filter(Product.id == -1)

    categories = categories_query.distinct().order_by(Category.name).all()

    category_counts_query = db.session.query(Product.category_id, db.func.count(Product.id)).filter(
        Product.shop_id == shop.id,
        Product.is_active == True,
    )
    if shop_allows_products and not shop_allows_services:
        category_counts_query = category_counts_query.filter(Product.kind == "physical")
    elif shop_allows_services and not shop_allows_products:
        category_counts_query = category_counts_query.filter(Product.kind == "service")
    elif not has_product_universe:
        category_counts_query = category_counts_query.filter(Product.id == -1)

    category_counts = dict(category_counts_query.group_by(Product.category_id).all())
    category_counts_physical = dict(
        db.session.query(Product.category_id, db.func.count(Product.id))
        .filter(
            Product.shop_id == shop.id,
            Product.is_active == True,
            Product.kind == "physical",
        )
        .group_by(Product.category_id)
        .all()
    ) if shop_allows_products else {}
    category_counts_service = dict(
        db.session.query(Product.category_id, db.func.count(Product.id))
        .filter(
            Product.shop_id == shop.id,
            Product.is_active == True,
            Product.kind == "service",
        )
        .group_by(Product.category_id)
        .all()
    ) if shop_allows_services else {}

    for category in categories:
        category_counts.setdefault(category.id, 0)
        category_counts_physical.setdefault(category.id, 0)
        category_counts_service.setdefault(category.id, 0)

    now = datetime.utcnow()
    location_query = (
        RentalListing.query
        .options(selectinload(RentalListing.media))
        .filter(
            RentalListing.shop_id == shop.id,
            RentalListing.is_active == True,
            RentalListing.status.in_(["active", "reserved"]),
            RentalListing.expires_at > now,
        )
        .order_by(RentalListing.created_at.desc())
    )
    if not shop_allows_location:
        location_query = location_query.filter(RentalListing.id == -1)
    location_total = location_query.count()
    location_listings = location_query.limit(8).all()
    
    return render_template(
        "shop/shop_detail.html",
        shop=shop,
        shop_is_open_now=shop_is_open_now,
        shop_allows_products=shop_allows_products,
        shop_allows_services=shop_allows_services,
        shop_allows_location=shop_allows_location,
        has_product_universe=has_product_universe,
        products=pagination.items,
        categories=categories,
        category_counts=category_counts,
        category_counts_physical=category_counts_physical,
        category_counts_service=category_counts_service,
        pagination=pagination,
        total_products=total_products,
        shop_physical_total=shop_physical_total,
        shop_service_total=shop_service_total,
        shop_total_items=shop_total_items,
        location_total=location_total,
        location_listings=location_listings,
        service_location_url=service_location_url,
        q=q,
        cat=cat,
        sort=sort,
        kind=kind,
    )
