# app/routes/shop.py - MODIFI
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
from sqlalchemy import case, or_
from ..extensions import db
from ..models.product import Product
from ..models.shop import Shop  # NOUVEAU
from ..models.promo import Promo
from ..models.review import Review
from ..models.rental import RentalListing, RentalMedia
from ..services.pricing import prix_final, get_active_promo
from ..services.cache import get_categories, get_catalog_cache
from ..services.pagination import SimplePagination, page_from_args

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


@bp.route("/")
def home():
    page = page_from_args(request.args)
    cat = request.args.get("cat", type=int)
    q = (request.args.get("q") or "").strip()
    sort = (request.args.get("sort") or "").strip()
    kind = (request.args.get("kind") or "").strip().lower()
    if kind not in ("physical", "service"):
        kind = ""
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    promo_only = request.args.get("promo", "0").strip()
    in_stock = request.args.get("stock", "0").strip()
    shop_id = request.args.get("shop", type=int)

    per_page = 24

    def build_products_payload():
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

        if q:
            query = query.filter(Product.name.ilike(f"%{q}%"))

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
            query = query.order_by(Product.created_at.desc())
        elif sort == "low":
            query = query.order_by(final_price_expr.asc(), Product.created_at.desc())
        elif sort == "high":
            query = query.order_by(final_price_expr.desc(), Product.created_at.desc())
        else:
            query = query.order_by(Product.created_at.desc())

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        products = pagination.items

        product_ids = [p.id for p in products]
        promos = (
            Promo.query
            .filter(
                Promo.product_id.in_(product_ids),
                Promo.end_date >= now,
            )
            .order_by(Promo.product_id.asc(), Promo.end_date.asc())
            .all()
        ) if product_ids else []
        promo_map = {}
        for pr in promos:
            promo_map.setdefault(pr.product_id, pr)

        data = []
        for product in products:
            promo = promo_map.get(product.id)
            final_price = prix_final(product, promo)

            discount = promo.value if promo and promo.type == "percentage" else 0
            product_dict = {
                "id": product.id,
                "name": product.name,
                "price": float(product.price or 0),
                "stock": product.stock or 0,
                "kind": (product.kind or "physical"),
                "image_file": product.image_file,
            }
            data.append((product_dict, final_price, discount))

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

            if q:
                like = f"%{q}%"
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
                location_query = location_query.order_by(RentalListing.created_at.desc())
            elif sort == "low":
                location_query = location_query.order_by(RentalListing.rent_cents.asc())
            elif sort == "high":
                location_query = location_query.order_by(RentalListing.rent_cents.desc())
            else:
                location_query = location_query.order_by(RentalListing.created_at.desc())

            active_locations = location_query.limit(max(6, per_page // 3)).all()
            listing_ids = [listing.id for listing in active_locations]
            location_cover_map = {}
            if listing_ids:
                media_rows = (
                    db.session.query(RentalMedia.listing_id, RentalMedia.file_path)
                    .filter(
                        RentalMedia.listing_id.in_(listing_ids),
                        RentalMedia.kind == "image",
                    )
                    .order_by(RentalMedia.listing_id.asc(), RentalMedia.id.asc())
                    .all()
                )
                for listing_id, file_path in media_rows:
                    if listing_id not in location_cover_map and file_path:
                        location_cover_map[listing_id] = str(file_path)

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

    cache_key = f"shop_home:{page}:{cat}:{q}:{sort}:{kind}:{min_price}:{max_price}:{promo_only}:{in_stock}:{shop_id}"
    payload = get_catalog_cache(cache_key, build_products_payload, timeout=60)
    data = payload.get("data", [])
    pagination = SimplePagination(page, payload.get("per_page", per_page), payload.get("total", 0))

    categories = get_categories()

    def build_category_counts_all():
        return dict(
            db.session.query(Product.category_id, db.func.count(Product.id))
            .filter(Product.is_active == True)
            .group_by(Product.category_id)
            .all()
        )

    def build_category_counts_physical():
        return dict(
            db.session.query(Product.category_id, db.func.count(Product.id))
            .filter(Product.is_active == True, Product.kind == "physical")
            .group_by(Product.category_id)
            .all()
        )

    def build_category_counts_service():
        return dict(
            db.session.query(Product.category_id, db.func.count(Product.id))
            .filter(Product.is_active == True, Product.kind == "service")
            .group_by(Product.category_id)
            .all()
        )

    category_counts = dict(get_catalog_cache("category_counts", build_category_counts_all, timeout=120))
    category_counts_physical = dict(get_catalog_cache("category_counts_physical", build_category_counts_physical, timeout=120))
    category_counts_service = dict(get_catalog_cache("category_counts_service", build_category_counts_service, timeout=120))
    for category in categories:
        category_counts.setdefault(category.id, 0)
        category_counts_physical.setdefault(category.id, 0)
        category_counts_service.setdefault(category.id, 0)

    def build_shop_filters():
        shops = Shop.query.filter_by(is_active=True).order_by(Shop.name).all()
        shop_counts = dict(
            db.session.query(Product.shop_id, db.func.count(Product.id))
            .filter(Product.is_active == True)
            .group_by(Product.shop_id)
            .all()
        )
        now = datetime.utcnow()
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
        for shop in shops:
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
                "is_open_now": _shop_is_currently_open(shop),
                "primary_type": shop.primary_type,
                "allowed_types": allowed_types,
                "location_count": int(location_counts.get(shop.id, 0) or 0),
                "service_map_url": (shop.service_map_url if can_show_service_location else ""),
            })
        return {"shops": shops_data, "shop_counts": shop_counts}

    shop_payload = get_catalog_cache("shop_filters", build_shop_filters, timeout=120)
    shops = shop_payload.get("shops", [])
    shop_counts = dict(shop_payload.get("shop_counts", {}))
    for shop in shops:
        shop_counts.setdefault(shop.get("id"), 0)

    return render_template(
        "shop/home.html",
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
    )

# ... (le reste du code reste inchang)

@bp.route("/product/<int:pid>/review", methods=["POST"])
@login_required
def review(pid):
    rating = int(request.form.get("rating", 5))
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

