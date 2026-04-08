# app/routes/shops.py - VERSION RENFORCÉE
from datetime import datetime
import hashlib

from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from sqlalchemy.orm import selectinload, load_only
from sqlalchemy import case, func
from flask import current_app
from ..extensions import db
from ..models.shop import Shop
from ..models.product import Product
from ..models.promo import Promo
from ..services.pricing import calculate_promo_price, get_active_promos_for_products
from ..models.category import Category
from ..models.rental import RentalListing
from ..services.cache import get_catalog_cache
from ..services.pagination import SimplePagination, page_from_args
from ..services.rentals import cents_to_dh, rental_existing_video_poster_rel_path
from ..services.shop_access import is_safe_public_shop_slug, normalize_public_shop_slug

bp = Blueprint("shops", __name__)

RESERVED_ROOT_SHOP_SLUGS = {
    "admin",
    "admin-access",
    "api",
    "booking",
    "cart",
    "delivery",
    "health",
    "lang",
    "locations",
    "location",
    "login",
    "logout",
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
}


def _shop_is_currently_open(shop: Shop | None) -> bool:
    """Vérifie si une boutique est actuellement ouverte."""
    if not shop:
        return False  # Plus sûr que True
    
    if not shop.is_active:
        return False
    
    now = datetime.utcnow()
    if shop.closed_until and shop.closed_until > now:
        return False
    
    # Utiliser la méthode métier si elle existe
    if hasattr(shop, 'is_open_now') and callable(getattr(shop, 'is_open_now')):
        return shop.is_open_now()
    
    return bool(getattr(shop, "is_open", False))


def _is_ajax_request() -> bool:
    """Détecte si la requête est AJAX."""
    requested_with = (request.headers.get("X-Requested-With") or "").strip()
    return requested_with in ("fetch", "XMLHttpRequest")


def _safe_str_param(value: str, max_length: int = 100) -> str:
    """Nettoie et valide une chaîne de paramètre."""
    if not value or not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def _validate_sort_param(sort: str) -> str:
    """Valide le paramètre de tri."""
    valid_sorts = {'new', 'low', 'high', 'promo'}
    return sort if sort in valid_sorts else ''


def _validate_kind_param(kind: str, allowed_kinds=None) -> str:
    """Valide le paramètre de type."""
    if allowed_kinds is None:
        allowed_kinds = {'physical', 'service', 'location'}
    return kind if kind in allowed_kinds else ''


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _safe_session_rollback() -> None:
    try:
        db.session.rollback()
    except Exception:
        pass


def _shops_mix_slot() -> str:
    now = datetime.utcnow()
    return f"{now:%Y%m%d%H}{now.minute // 2}"


def _mixed_shop_ids(query, *, slot: str) -> list[int]:
    base_rows = query.with_entities(
        Shop.id.label("id"),
        Shop.is_verified.label("is_verified"),
        Shop.created_at.label("created_at"),
    ).subquery()

    rows = db.session.query(
        base_rows.c.id,
        base_rows.c.is_verified,
        base_rows.c.created_at,
    ).all()

    def sort_key(row) -> tuple:
        digest = hashlib.sha1(f"{slot}:{row.id}".encode("utf-8")).hexdigest()[:12]
        random_rank = int(digest, 16)
        try:
            freshness = row.created_at.timestamp() if row.created_at else 0.0
        except Exception:
            freshness = 0.0
        return (
            random_rank,
            -int(bool(row.is_verified)),
            -freshness,
            -int(row.id),
        )

    ordered_rows = sorted(rows, key=sort_key)
    return [int(row.id) for row in ordered_rows]


@bp.route("/shops")
def list_shops():
    """Liste toutes les boutiques actives"""
    page = page_from_args(request.args)
    q = _safe_str_param(request.args.get("q", ""))
    kind = _validate_kind_param((request.args.get("kind") or "").strip().lower())

    per_page = 12
    mix_slot = _shops_mix_slot()

    def build_shops_payload():
        """Construit le payload des boutiques (utilisé pour le cache)."""
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
                    .filter(
                        Product.is_active == True,
                        Product.kind == "physical"
                    )
                    .distinct()
                )
                query = query.filter(Shop.id.in_(shop_ids_subq))

            elif kind == "service":
                query = query.filter(Shop.sql_allows_clause("services"))
                shop_ids_subq = (
                    db.session.query(Product.shop_id)
                    .filter(
                        Product.is_active == True,
                        Product.kind == "service"
                    )
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

        mixed_shop_ids = _mixed_shop_ids(query, slot=mix_slot)
        total = len(mixed_shop_ids)
        start_idx = max(0, (page - 1) * per_page)
        page_shop_ids = mixed_shop_ids[start_idx:start_idx + per_page]

        shops_page = []
        if page_shop_ids:
            shops_rows = (
                query
                .options(
                    load_only(
                        Shop.id,
                        Shop.vendor_id,
                        Shop.name,
                        Shop.slug,
                        Shop.logo,
                        Shop.banner,
                        Shop.description,
                        Shop.is_verified,
                        Shop.contact_phone,
                        Shop.address,
                        Shop.service_location_note,
                        Shop.service_latitude,
                        Shop.service_longitude,
                        Shop.is_active,
                        Shop.is_open,
                        Shop.closed_until,
                        Shop.primary_type,
                        Shop.allowed_types_json,
                    )
                )
                .filter(Shop.id.in_(page_shop_ids))
                .all()
            )
            shops_by_id = {shop.id: shop for shop in shops_rows}
            shops_page = [shops_by_id[sid] for sid in page_shop_ids if sid in shops_by_id]
        shop_ids = [shop.id for shop in shops_page]

        physical_counts = {}
        service_counts = {}
        location_counts = {}
        promo_counts = {}

        if shop_ids:
            # Produits physiques + services en une seule requête
            now = datetime.utcnow()
            promo_exists_sq = (
                db.session.query(Promo.id)
                .filter(
                    Promo.product_id == Product.id,
                    Promo.end_date >= now,
                )
                .exists()
            )
            try:
                product_count_rows = (
                    db.session.query(
                        Product.shop_id.label("shop_id"),
                        func.sum(
                            case((Product.kind == "physical", 1), else_=0)
                        ).label("physical"),
                        func.sum(
                            case((Product.kind == "service", 1), else_=0)
                        ).label("service"),
                        func.sum(
                            case((promo_exists_sq, 1), else_=0)
                        ).label("promo"),
                    )
                    .filter(
                        Product.shop_id.in_(shop_ids),
                        Product.is_active == True
                    )
                    .group_by(Product.shop_id)
                    .all()
                )
            except Exception:
                _safe_session_rollback()
                current_app.logger.exception("shops list product counts build error")
                product_count_rows = []

            physical_counts = {
                row.shop_id: int(row.physical or 0)
                for row in product_count_rows
            }
            service_counts = {
                row.shop_id: int(row.service or 0)
                for row in product_count_rows
            }
            if kind != "location":
                promo_counts = {
                    row.shop_id: int(row.promo or 0)
                    for row in product_count_rows
                }

            try:
                location_count_rows = (
                    db.session.query(
                        RentalListing.shop_id,
                        func.count(RentalListing.id)
                    )
                    .filter(
                        RentalListing.shop_id.in_(shop_ids),
                        RentalListing.is_active == True,
                        RentalListing.status.in_(["active", "reserved"]),
                        RentalListing.expires_at > now,
                    )
                    .group_by(RentalListing.shop_id)
                    .all()
                )
            except Exception:
                _safe_session_rollback()
                current_app.logger.exception("shops list location counts build error")
                location_count_rows = []

            location_counts = {
                row[0]: (row[1] or 0)
                for row in location_count_rows
            }


        shops_data = []

        for shop in shops_page:
            physical_count = physical_counts.get(shop.id, 0)
            service_count = service_counts.get(shop.id, 0)
            location_count = int(location_counts.get(shop.id, 0) or 0)

            address = (shop.address or "").strip()
            allowed_types = shop.get_allowed_types()
            can_show_service_location = (
                ("services" in allowed_types) and ("products" not in allowed_types)
            )

            shops_data.append({
                "id": shop.id,
                "name": shop.name,
                "slug": shop.slug,
                "logo": shop.logo,
                "banner": shop.banner,
                "description": shop.description,
                "rating": _safe_float(shop.__dict__.get("rating"), 0.0),
                "is_verified": shop.is_verified,
                "contact_phone": shop.contact_phone,
                "address": address,
                "service_location_note": (
                    (shop.service_location_note or "").strip()
                    if can_show_service_location else ""
                ),
                "service_latitude": (
                    shop.service_latitude if can_show_service_location else None
                ),
                "service_longitude": (
                    shop.service_longitude if can_show_service_location else None
                ),
                "service_map_url": (
                    shop.service_map_url if can_show_service_location else ""
                ),
                "is_open_now": _shop_is_currently_open(shop),
                "physical_count": physical_count,
                "service_count": service_count,
                "location_count": location_count,
                "product_count": physical_count + service_count,
                "promo_count": int(promo_counts.get(shop.id, 0) or 0),
                "has_promo": bool(int(promo_counts.get(shop.id, 0) or 0) > 0),
                "allowed_types": allowed_types,
                "primary_type": shop.primary_type,
            })

        return {
            "shops": shops_data,
            "total": total,
            "per_page": per_page,
        }

    cache_key = f"shops_list:{page}:{q}:{kind}:{mix_slot}"

    try:
        payload = get_catalog_cache(cache_key, build_shops_payload, timeout=120)
    except Exception as exc:
        _safe_session_rollback()
        current_app.logger.exception("shops list cache/build error")
        try:
            payload = build_shops_payload()
        except Exception as inner_exc:
            _safe_session_rollback()
            current_app.logger.exception("shops list fallback build error")
            raise inner_exc from exc

    shops = payload.get("shops", [])
    pagination = SimplePagination(
        page,
        payload.get("per_page", per_page),
        payload.get("total", 0)
    )

    template_name = (
        "partials/_shops_listing.html"
        if _is_ajax_request()
        else "shop/shops.html"
    )

    return render_template(
        template_name,
        shops=shops,
        pagination=pagination,
        q=q,
        kind=kind,
    )

@bp.route("/<string:shop_slug>")
def shop_detail(shop_slug):
    """Détail d'une boutique avec ses produits"""
    # Validation du slug
    if not shop_slug or not isinstance(shop_slug, str):
        return render_template("errors/404.html"), 404
    normalized_slug = normalize_public_shop_slug(shop_slug)
    if not is_safe_public_shop_slug(normalized_slug, reserved=RESERVED_ROOT_SHOP_SLUGS):
        return render_template("errors/404.html"), 404

    shop = Shop.query.filter_by(slug=normalized_slug, is_active=True).first_or_404()
    
    shop_allows_products = shop.allows("products")
    shop_allows_services = shop.allows("services")
    shop_allows_location = shop.allows("location")
    service_location_url = shop.service_map_url if (shop_allows_services and not shop_allows_products) else ""
    shop_is_open_now = _shop_is_currently_open(shop)
    has_product_universe = shop_allows_products or shop_allows_services
    supported_detail_modes = []
    if shop_allows_products:
        supported_detail_modes.append("physical")
    if shop_allows_services:
        supported_detail_modes.append("service")
    if shop_allows_location:
        supported_detail_modes.append("location")
    supported_detail_mode_count = len(supported_detail_modes)
    
    # Validation des paramètres
    page = page_from_args(request.args)
    cat = request.args.get("cat", type=int)
    if cat is not None and cat <= 0:
        cat = None
    
    q = _safe_str_param(request.args.get("q", ""))
    sort = _validate_sort_param((request.args.get("sort") or "").strip())
    kind = _validate_kind_param(
        (request.args.get("kind") or "").strip().lower(),
        set(supported_detail_modes)
    )

    if kind not in supported_detail_modes:
        kind = ""
    if not kind and supported_detail_mode_count == 1:
        kind = supported_detail_modes[0]
    
    ajax = request.args.get("ajax", type=int)
    utc_now = datetime.utcnow()
    
    # Construction de la requête de base
    base_query = Product.query.filter(Product.shop_id == shop.id, Product.is_active == True)
    
    if shop_allows_products and not shop_allows_services:
        base_query = base_query.filter(Product.kind == "physical")
    elif shop_allows_services and not shop_allows_products:
        base_query = base_query.filter(Product.kind == "service")
    elif not has_product_universe:
        base_query = base_query.filter(False)  # Plus propre que Product.id == -1
    
    query = base_query
    active_promo_products = (
        db.session.query(Promo.product_id.label("product_id"))
        .join(Product, Product.id == Promo.product_id)
        .filter(
            Product.shop_id == shop.id,
            Product.is_active == True,
            Promo.end_date >= utc_now,
        )
        .distinct()
        .subquery()
    )

    if kind == "location":
        query = query.filter(False)
    else:
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
            query = query.order_by(Product.price_cents_value.asc())
        elif sort == "high":
            query = query.order_by(Product.price_cents_value.desc())
        elif sort == "promo":
            promo_first_rank = case(
                (active_promo_products.c.product_id.isnot(None), 0),
                else_=1,
            )
            query = (
                query
                .outerjoin(active_promo_products, Product.id == active_promo_products.c.product_id)
                .order_by(promo_first_rank.asc(), Product.created_at.desc())
            )
        else:
            query = query.order_by(Product.created_at.desc())
    
    # Pagination
    per_page = 12
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    promo_map = get_active_promos_for_products([product.id for product in pagination.items])
    try:
        shop_promo_count = int(
            db.session.query(func.count()).select_from(active_promo_products).scalar() or 0
        )
    except Exception:
        _safe_session_rollback()
        current_app.logger.exception("shop detail promo count build error")
        shop_promo_count = 0
    
    # Si requête AJAX, retourner JSON
    if ajax:
        products_html = render_template(
            "shop/_products_partial.html",
            products=pagination.items,
            promo_map=promo_map,
            calculate_promo_price=calculate_promo_price,
        )
        return jsonify({
            'products': products_html,
            'total': pagination.total,  # Utiliser pagination.total
            'has_more': pagination.has_next
        })

    # OPTIMISATION : Une seule requête pour les totaux par type
    kind_totals = dict(
        db.session.query(
            Product.kind, 
            func.count(Product.id)
        )
        .filter(Product.shop_id == shop.id, Product.is_active == True)
        .group_by(Product.kind)
        .all()
    )
    shop_physical_total = kind_totals.get("physical", 0) if shop_allows_products else 0
    shop_service_total = kind_totals.get("service", 0) if shop_allows_services else 0
    shop_total_items = shop_physical_total + shop_service_total

    # OPTIMISATION : Catégories et compteurs en une seule requête
    from sqlalchemy import and_
    
    # Déterminer les kinds à inclure
    kinds_to_include = []
    if shop_allows_products:
        kinds_to_include.append("physical")
    if shop_allows_services:
        kinds_to_include.append("service")
    
    if kinds_to_include:
        # Requête optimisée pour catégories et compteurs
        category_data = db.session.query(
            Category.id,
            Category.name,
            func.count(Product.id).label('total'),
            func.sum(case((Product.kind == "physical", 1), else_=0)).label('physical'),
            func.sum(case((Product.kind == "service", 1), else_=0)).label('service')
        ).join(
            Product, Category.id == Product.category_id
        ).filter(
            Product.shop_id == shop.id,
            Product.is_active == True,
            Product.kind.in_(kinds_to_include)
        ).group_by(
            Category.id, Category.name
        ).order_by(Category.name).all()
        
        categories = []
        category_counts = {}
        category_counts_physical = {}
        category_counts_service = {}
        
        for cat_id, cat_name, total, physical, service in category_data:
            categories.append(Category(id=cat_id, name=cat_name))
            category_counts[cat_id] = total
            category_counts_physical[cat_id] = physical
            category_counts_service[cat_id] = service
    else:
        categories = []
        category_counts = {}
        category_counts_physical = {}
        category_counts_service = {}

    now = datetime.utcnow()
    
    # Locations (gardé séparé car structure différente)
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
        location_query = location_query.filter(False)
    
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
        supported_detail_modes=supported_detail_modes,
        supported_detail_mode_count=supported_detail_mode_count,
        shop_promo_count=shop_promo_count,
        shop_has_promo=bool(shop_promo_count > 0),
        products=pagination.items,
        promo_map=promo_map,
        calculate_promo_price=calculate_promo_price,
        categories=categories,
        category_counts=category_counts,
        category_counts_physical=category_counts_physical,
        category_counts_service=category_counts_service,
        pagination=pagination,
        total_products=pagination.total,  # Utiliser pagination.total
        shop_physical_total=shop_physical_total,
        shop_service_total=shop_service_total,
        shop_total_items=shop_total_items,
        location_total=location_total,
        location_listings=location_listings,
        cents_to_dh=cents_to_dh,
        rental_video_poster_rel_path=rental_existing_video_poster_rel_path,
        service_location_url=service_location_url,
        q=q,
        cat=cat,
        sort=sort,
        kind=kind,
    )


@bp.route("/shop/<string:shop_slug>")
def shop_detail_alias(shop_slug):
    normalized_slug = normalize_public_shop_slug(shop_slug)
    if not is_safe_public_shop_slug(normalized_slug, reserved=RESERVED_ROOT_SHOP_SLUGS):
        return render_template("errors/404.html"), 404
    return redirect(url_for("shops.shop_detail", shop_slug=normalized_slug, **request.args), code=301)
