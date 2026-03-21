# app/routes/shop.py - MODIFI
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime
from types import SimpleNamespace
import hashlib
from sqlalchemy import case, or_
from sqlalchemy.orm import load_only
from ..extensions import db
from ..models.featured_item import FeaturedItem
from ..models.product import Product
from ..models.shop import Shop  # NOUVEAU
from ..models.promo import Promo
from ..models.review import Review
from ..models.rental import RentalListing, RentalMedia
from ..services.pricing import prix_final, get_active_promo, get_active_promos_for_products
from ..services.cache import cache, get_categories, get_catalog_cache
from ..services.marketplace_feed import build_marketplace_feed, should_use_curated_marketplace_feed
from ..services.featured_items import featured_rank_expr, location_featured_exists_expr, product_featured_exists_expr, shop_featured_exists_expr
from ..services.pagination import SimplePagination, page_from_args
from ..services.rentals import rental_existing_video_poster_rel_path

bp = Blueprint("shop", __name__)


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


def safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def _wants_json_response() -> bool:
    return (
        request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )


def _render_shop_home(
    *,
    template_name: str = "shop/home.html",
    forced_promo_only: str | None = None,
):
    if current_user.is_authenticated and getattr(current_user, "role", None) == "courier":
        return redirect(url_for("courier.panel_deliveries"))

    page = page_from_args(request.args)
    cat = request.args.get("cat", type=int)
    q = (request.args.get("q") or "").strip()
    search_q = q if len(q) >= 2 else ""
    sort = (request.args.get("sort") or "").strip()
    kind = (request.args.get("kind") or "").strip().lower()
    if kind not in ("physical", "service"):
        kind = ""
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    promo_only = (forced_promo_only if forced_promo_only is not None else request.args.get("promo", "0")).strip()
    in_stock = request.args.get("stock", "0").strip()
    shop_id = request.args.get("shop", type=int)

    per_page = 24

    def build_products_payload():
        if should_use_curated_marketplace_feed(
            page=page,
            sort=sort,
            shop_id=shop_id,
        ):
            return build_marketplace_feed(
                page=page,
                per_page=per_page,
                category_id=cat,
                search_q=search_q,
                kind=kind,
                min_price=min_price,
                max_price=max_price,
                promo_only=promo_only,
                in_stock=in_stock,
                shop_id=shop_id,
            )

        now = datetime.utcnow()

        promo_value_sq = (
            db.session.query(Promo.value)
            .filter(
                Promo.product_id == Product.id,
                Promo.end_date >= now,
            )
            .order_by(Promo.end_date.asc())
            .limit(1)
            .correlate(Product)
            .scalar_subquery()
        )
        promo_type_sq = (
            db.session.query(Promo.type)
            .filter(
                Promo.product_id == Product.id,
                Promo.end_date >= now,
            )
            .order_by(Promo.end_date.asc())
            .limit(1)
            .correlate(Product)
            .scalar_subquery()
        )
        promo_exists_sq = (
            db.session.query(Promo.id)
            .filter(
                Promo.product_id == Product.id,
                Promo.end_date >= now,
            )
            .exists()
        )

        promo_value = db.func.coalesce(promo_value_sq, 0.0)
        fixed_price_expr = case(
            ((Product.price - promo_value) > 0, Product.price - promo_value),
            else_=0.0,
        )
        final_price_expr = case(
            (promo_type_sq == "percentage", Product.price - (Product.price * promo_value / 100.0)),
            (promo_type_sq == "fixed", fixed_price_expr),
            else_=Product.price,
        )

        query = Product.query.filter(Product.is_active == True)
        product_feature_rank = featured_rank_expr(product_featured_exists_expr(Product.id, Product.shop_id, now))

        if search_q:
            query = query.filter(Product.name.ilike(f"%{search_q}%"))

        if cat:
            query = query.filter(Product.category_id == cat)

        if shop_id:
            query = query.filter(Product.shop_id == shop_id)

        if kind:
            query = query.filter(Product.kind == kind)

        if in_stock == "1":
            # Le filtre "en stock" n'a pas de sens pour les services => ils restent visibles
            query = query.filter((Product.kind == "service") | (Product.stock > 0))

        if promo_only == "1":
            query = query.filter(promo_exists_sq)

        if min_price is not None:
            query = query.filter(final_price_expr >= min_price)
        if max_price is not None:
            query = query.filter(final_price_expr <= max_price)

        if sort == "new":
            query = query.order_by(product_feature_rank.desc(), Product.created_at.desc())
        elif sort == "low":
            query = query.order_by(product_feature_rank.desc(), final_price_expr.asc(), Product.created_at.desc())
        elif sort == "high":
            query = query.order_by(product_feature_rank.desc(), final_price_expr.desc(), Product.created_at.desc())
        else:
            query = query.order_by(product_feature_rank.desc(), Product.created_at.desc())

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        products = pagination.items

        product_ids = [p.id for p in products]
        if product_ids:
            try:
                promos = (
                    Promo.query
                    .filter(
                        Promo.product_id.in_(product_ids),
                        Promo.end_date >= now,
                    )
                    .order_by(Promo.product_id.asc(), Promo.end_date.asc())
                    .all()
                )
            except Exception:
                _safe_session_rollback()
                promos = []
        else:
            promos = []
        promo_map = {}
        for pr in promos:
            promo_map.setdefault(pr.product_id, pr)

        data = []
        for product in products:
            try:
                promo = promo_map.get(product.id)
                safe_price = _safe_float(getattr(product, "price", 0), 0.0)
                final_price = _safe_float(prix_final(product, promo), safe_price)
                discount = _safe_float(getattr(promo, "value", 0), 0.0) if promo and promo.type == "percentage" else 0.0
                product_dict = {
                    "id": product.id,
                    "name": product.name,
                    "price": safe_price,
                    "stock": product.stock or 0,
                    "kind": (product.kind or "physical"),
                    "image_file": product.image_file,
                    "promo_active": bool(promo),
                    "promo_type": (promo.type if promo else ""),
                    "promo_value": _safe_float(getattr(promo, "value", 0), 0.0) if promo else 0.0,
                }
                data.append((product_dict, final_price, discount))
            except Exception:
                continue

        if not kind and page == 1:
            location_query = (
                RentalListing.query
                .join(Shop, Shop.id == RentalListing.shop_id)
                .filter(
                    RentalListing.is_active == True,
                    RentalListing.status.in_(["active", "reserved"]),
                    RentalListing.expires_at > now,
                    Shop.is_active == True,
                    Shop.sql_allows_clause("location"),
                )
            )

            if search_q:
                like = f"%{search_q}%"
                location_query = location_query.filter(
                    (RentalListing.title.ilike(like))
                    | (RentalListing.city.ilike(like))
                    | (RentalListing.area.ilike(like))
                    | (RentalListing.description.ilike(like))
                )

            if shop_id:
                location_query = location_query.filter(RentalListing.shop_id == shop_id)

            if min_price is not None:
                location_query = location_query.filter(RentalListing.rent_cents >= int(round(min_price * 100)))
            if max_price is not None:
                location_query = location_query.filter(RentalListing.rent_cents <= int(round(max_price * 100)))

            if sort == "new":
                location_feature_rank = featured_rank_expr(
                    location_featured_exists_expr(RentalListing.id, RentalListing.shop_id, now)
                )
                location_query = location_query.order_by(location_feature_rank.desc(), RentalListing.created_at.desc())
            elif sort == "low":
                location_feature_rank = featured_rank_expr(
                    location_featured_exists_expr(RentalListing.id, RentalListing.shop_id, now)
                )
                location_query = location_query.order_by(location_feature_rank.desc(), RentalListing.rent_cents.asc())
            elif sort == "high":
                location_feature_rank = featured_rank_expr(
                    location_featured_exists_expr(RentalListing.id, RentalListing.shop_id, now)
                )
                location_query = location_query.order_by(location_feature_rank.desc(), RentalListing.rent_cents.desc())
            else:
                location_feature_rank = featured_rank_expr(
                    location_featured_exists_expr(RentalListing.id, RentalListing.shop_id, now)
                )
                location_query = location_query.order_by(location_feature_rank.desc(), RentalListing.created_at.desc())

            active_locations = location_query.limit(max(6, per_page // 3)).all()
            listing_ids = [listing.id for listing in active_locations]
            location_cover_map = {}
            location_video_map = {}
            location_video_poster_map = {}
            if listing_ids:
                media_rows = (
                    db.session.query(RentalMedia.listing_id, RentalMedia.kind, RentalMedia.file_path)
                    .filter(
                        RentalMedia.listing_id.in_(listing_ids),
                        RentalMedia.kind.in_(("image", "video")),
                    )
                    .order_by(RentalMedia.listing_id.asc(), RentalMedia.id.asc())
                    .all()
                )
                for listing_id, media_kind, file_path in media_rows:
                    if not file_path:
                        continue
                    if media_kind == "image" and listing_id not in location_cover_map:
                        location_cover_map[listing_id] = str(file_path)
                    elif media_kind == "video" and listing_id not in location_video_map:
                        location_video_map[listing_id] = str(file_path)
                        poster_rel = rental_existing_video_poster_rel_path(str(file_path))
                        if poster_rel:
                            location_video_poster_map[listing_id] = poster_rel

            location_entries = []
            for listing in active_locations:
                rent_dh = float((listing.rent_cents or 0) / 100)
                location_entries.append((
                    {
                        "id": listing.id,
                        "slug": listing.slug,
                        "name": listing.title,
                        "price": rent_dh,
                        "stock": None,
                        "kind": "location",
                        "image_file": location_cover_map.get(listing.id, ""),
                        "cover_video_file": location_video_map.get(listing.id, ""),
                        "cover_video_poster_file": location_video_poster_map.get(listing.id, ""),
                        "city": listing.city,
                        "area": listing.area,
                        "listing_type": listing.listing_type,
                    },
                    rent_dh,
                    0,
                ))

            if location_entries:
                mixed = []
                max_len = max(len(data), len(location_entries))
                for idx in range(max_len):
                    if idx < len(data):
                        mixed.append(data[idx])
                    if idx < len(location_entries):
                        mixed.append(location_entries[idx])
                data = mixed[:per_page]

        if sort == "low":
            data.sort(key=lambda x: x[1])
        elif sort == "high":
            data.sort(key=lambda x: x[1], reverse=True)

        return {
            "data": data,
            "total": pagination.total,
            "per_page": per_page,
        }

    cache_key = f"shop_home:v2:{page}:{cat}:{search_q}:{sort}:{kind}:{min_price}:{max_price}:{promo_only}:{in_stock}:{shop_id}"
    try:
        payload = get_catalog_cache(cache_key, build_products_payload, timeout=60)
    except Exception as exc:
        _safe_session_rollback()
        current_app.logger.error("shop home cache/build error: %s", exc)
        try:
            payload = build_products_payload()
        except Exception as inner_exc:
            _safe_session_rollback()
            current_app.logger.error("shop home fallback build error: %s", inner_exc)
            payload = {"data": [], "total": 0, "per_page": per_page}
    data = payload.get("data", [])
    pagination = SimplePagination(page, payload.get("per_page", per_page), payload.get("total", 0))

    categories = get_categories()

    def build_category_counts_bundle():
        try:
            rows = (
                db.session.query(
                    Product.category_id.label("category_id"),
                    db.func.count(Product.id).label("total"),
                    db.func.sum(
                        case((Product.kind == "physical", 1), else_=0)
                    ).label("physical"),
                    db.func.sum(
                        case((Product.kind == "service", 1), else_=0)
                    ).label("service"),
                )
                .filter(Product.is_active == True)
                .group_by(Product.category_id)
                .all()
            )
        except Exception:
            _safe_session_rollback()
            return {
                "all": {},
                "physical": {},
                "service": {},
            }

        return {
            "all": {row.category_id: int(row.total or 0) for row in rows},
            "physical": {row.category_id: int(row.physical or 0) for row in rows},
            "service": {row.category_id: int(row.service or 0) for row in rows},
        }

    category_counts_bundle = dict(get_catalog_cache("category_counts_bundle", build_category_counts_bundle, timeout=120))
    category_counts = dict(category_counts_bundle.get("all", {}))
    category_counts_physical = dict(category_counts_bundle.get("physical", {}))
    category_counts_service = dict(category_counts_bundle.get("service", {}))
    for category in categories:
        category_counts.setdefault(category.id, 0)
        category_counts_physical.setdefault(category.id, 0)
        category_counts_service.setdefault(category.id, 0)

    def build_shop_filters():
        shop_feature_rank = featured_rank_expr(shop_featured_exists_expr(Shop.id))
        shops = (
            Shop.query
            .options(
                load_only(
                    Shop.id,
                    Shop.name,
                    Shop.slug,
                    Shop.logo,
                    Shop.address,
                    Shop.service_location_note,
                    Shop.service_latitude,
                    Shop.service_longitude,
                    Shop.primary_type,
                    Shop.allowed_types_json,
                    Shop.is_active,
                    Shop.is_open,
                    Shop.closed_until,
                )
            )
            .filter_by(is_active=True)
            .order_by(shop_feature_rank.desc(), Shop.name)
            .all()
        )
        now = datetime.utcnow()
        rotation_slot = (now.hour * 60 + now.minute) // 30
        rotation_seed = f"{now:%Y%m%d}:{rotation_slot}:shops"
        featured_ids = {
            int(shop_id) for (shop_id,) in (
                db.session.query(FeaturedItem.shop_id)
                .filter(
                    FeaturedItem.target_type == FeaturedItem.TARGET_SHOP,
                    FeaturedItem.shop_id.isnot(None),
                    FeaturedItem.is_active.is_(True),
                    FeaturedItem.starts_at <= now,
                    FeaturedItem.ends_at >= now,
                )
                .all()
            )
        }
        featured_shops = []
        regular_shops = []
        for shop in shops:
            item = (
                int(hashlib.sha1(f"{rotation_seed}:{shop.id}".encode("utf-8")).hexdigest()[:12], 16),
                shop,
            )
            if shop.id in featured_ids:
                featured_shops.append(item)
            else:
                regular_shops.append(item)
        featured_shops.sort(key=lambda row: row[0])
        regular_shops.sort(key=lambda row: row[1].name.lower() if row[1].name else "")
        ordered_shops = [shop for _, shop in featured_shops[:6]] + [shop for _, shop in regular_shops]
        shop_counts = dict(
            db.session.query(Product.shop_id, db.func.count(Product.id))
            .filter(Product.is_active == True)
            .group_by(Product.shop_id)
            .all()
        )
        location_counts = dict(
            db.session.query(RentalListing.shop_id, db.func.count(RentalListing.id))
            .filter(
                RentalListing.is_active == True,
                RentalListing.status.in_(["active", "reserved"]),
                RentalListing.expires_at > now,
            )
            .group_by(RentalListing.shop_id)
            .all()
        )
        shops_data = []
        for shop in ordered_shops:
            address = (shop.address or "").strip()
            allowed_types = shop.get_allowed_types()
            can_show_service_location = ("services" in allowed_types) and ("products" not in allowed_types)
            shops_data.append({
                "id": shop.id,
                "name": shop.name,
                "logo": shop.logo,
                "slug": shop.slug,
                "address": address,
                "service_location_note": ((shop.service_location_note or "").strip() if can_show_service_location else ""),
                "service_latitude": (shop.service_latitude if can_show_service_location else None),
                "service_longitude": (shop.service_longitude if can_show_service_location else None),
                "primary_type": shop.primary_type,
                "allowed_types": allowed_types,
                "location_count": int(location_counts.get(shop.id, 0) or 0),
                "service_map_url": (shop.service_map_url if can_show_service_location else ""),
            })
        return {"shops": shops_data, "shop_counts": shop_counts}

    try:
        shop_payload = get_catalog_cache("shop_filters", build_shop_filters, timeout=120)
    except Exception as exc:
        _safe_session_rollback()
        current_app.logger.error("shop filters cache/build error: %s", exc)
        try:
            shop_payload = build_shop_filters()
        except Exception as inner_exc:
            _safe_session_rollback()
            current_app.logger.error("shop filters fallback build error: %s", inner_exc)
            shop_payload = {"shops": [], "shop_counts": {}}
    shops = shop_payload.get("shops", [])

    # keep shop_filters cache stable while recomputing volatile open/closed status per-request
    shop_ids = [int(shop.get("id")) for shop in shops if shop.get("id") is not None]
    dynamic_status = {}
    if shop_ids:
        dynamic_status_cache_key = "shop_filters_dynamic_status"
        try:
            cached_dynamic_status = cache.get(dynamic_status_cache_key)
        except Exception:
            cached_dynamic_status = None

        if isinstance(cached_dynamic_status, dict):
            dynamic_status = cached_dynamic_status
        else:
            status_rows = (
                db.session.query(Shop.id, Shop.is_active, Shop.is_open, Shop.closed_until)
                .filter(Shop.id.in_(shop_ids))
                .all()
            )
            for row in status_rows:
                dynamic_status[int(row.id)] = {
                    "id": int(row.id),
                    "is_active": bool(row.is_active),
                    "is_open": bool(row.is_open),
                    "closed_until": row.closed_until,
                }
            try:
                cache.set(dynamic_status_cache_key, dynamic_status, timeout=15)
            except Exception:
                pass

    for shop in shops:
        sid = int(shop.get("id") or 0)
        row = dynamic_status.get(sid)
        if row:
            shop["is_open_now"] = _shop_is_currently_open(SimpleNamespace(**row))
        else:
            shop["is_open_now"] = False

    shop_counts = dict(shop_payload.get("shop_counts", {}))
    for shop in shops:
        shop_counts.setdefault(shop.get("id"), 0)

    return render_template(
        template_name,
        data=data,
        categories=categories,
        shops=shops,
        category_counts=category_counts,
        category_counts_physical=category_counts_physical,
        category_counts_service=category_counts_service,
        shop_counts=shop_counts,
        pagination=pagination,
        q=q,
        cat=cat,
        shop_id=shop_id,
        sort=sort,
        kind=kind,
        min_price=min_price,
        max_price=max_price,
        promo_only=promo_only,
        in_stock=in_stock,
    )


@bp.route("/")
def home():
    return _render_shop_home()


@bp.route("/promotions")
def promotions():
    return _render_shop_home(
        template_name="shop/promotions.html",
        forced_promo_only="1",
    )


@bp.route("/product/<int:pid>")
def product_detail(pid):
    product = Product.query.get_or_404(pid)
    
    if not product.is_active:
        flash("Ce produit n'est plus disponible", "warning")
        return redirect(url_for("shop.home"))

    shop_is_open_now = _shop_is_currently_open(getattr(product, "shop", None))

    # No state write on GET (pre-prod hardening).

    promo = get_active_promo(pid)
    final = prix_final(product, promo)

    reviews = Review.query.filter_by(product_id=pid).order_by(Review.created_at.desc()).all()
    avg = sum(r.rating for r in reviews) / len(reviews) if reviews else 0
    
    # Produits/services similaires : mme type + mme catgorie ou boutique
    similar_products = (
        Product.query.filter(
            Product.is_active == True,
            Product.id != product.id,
            Product.kind == product.kind,
            or_(
                Product.category_id == product.category_id,
                Product.shop_id == product.shop_id,
            ),
        )
        .limit(8)
        .all()
    )
    related_promos = get_active_promos_for_products([p.id for p in similar_products])

    return render_template(
        "shop/product_detail.html",
        product=product,
        shop_is_open_now=shop_is_open_now,
        final=final,
        promo=promo,
        reviews=reviews,
        avg=avg,
        similar_products=similar_products,  # NOUVEAU
        related_products=similar_products,
        related_promos=related_promos,
        calculate_promo_price=prix_final,
    )


@bp.route("/product/<int:pid>/review", methods=["POST"])
@login_required
def review(pid):
    rating = safe_int(request.form.get("rating", 5), None)
    if rating is None or rating < 1 or rating > 5:
        if _wants_json_response():
            return jsonify({"success": False, "error": "invalid_rating"}), 400
        flash("Note invalide (entre 1 et 5).", "warning")
        return redirect(url_for("shop.product_detail", pid=pid))

    comment = (request.form.get("comment") or "").strip()
    review = Review(product_id=pid, user_id=current_user.id, rating=rating, comment=comment)
    db.session.add(review)
    db.session.commit()
    flash("Avis enregistr", "success")
    return redirect(url_for("shop.product_detail", pid=pid))


@bp.route("/track/<token>", methods=["GET", "POST"])
def track_order(token):
    # Endpoint canonique: /cart/track/<token>.
    # On garde /shop/track/<token> en compat pour les anciens liens.
    return redirect(url_for("cart.track", token=token), code=307)


@bp.route("/suivi")
def suivi_redirect():
    return redirect(url_for("cart.my_orders"))
