# app/routes/vendor.py - VERSION CORRIGE
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from ..extensions import db
from ..models.product import Product
from ..models.category import Category
from ..models.shop import SHOP_TYPE_LABELS, SHOP_TYPE_ORDER, Shop, normalize_shop_type, shop_type_from_product_kind
from ..models.order import Order, OrderItem
from ..models.booking import Booking
from ..models.user import User
from ..models.vendor_payout import VendorPayout
from ..models.vendor_period import VendorPeriod
from ..models.vendor_receipt import VendorReceipt
from ..models.rental import RentalListing
from ..models.platform_settings import PlatformSettings
from ..services.image import save_image
from ..services.cache import bump_catalog_version
from sqlalchemy.orm import selectinload
from sqlalchemy import or_, and_, text
from ..services.audit import log_access
from ..services.shop_access import ensure_shop_allows, ensure_vendor_allows, resolve_vendor_shop, shop_allows_any
from ..services.pagination import page_from_args
from ..middleware.security import order_access_required
from datetime import datetime, timedelta
from slugify import slugify

bp = Blueprint("vendor", __name__)

ALLOWED = {"png", "jpg", "jpeg", "webp"}
MAX_PRODUCT_IMAGES = 4
MAX_PRODUCT_IMAGES_TOTAL_BYTES = 15 * 1024 * 1024
PRODUCT_PURGE_GRACE_DAYS = 21
ACTIVE_ORDER_STATUSES = {"pending", "paid", "processing", "shipping", "shipped"}

@bp.before_request
@login_required
def restrict_vendor():
    if getattr(current_user, "role", None) != "vendor":
        flash("Accs rserv aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

def _is_ajax_request() -> bool:
    return (
        request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED


def _parse_product_images(image_file: str | None) -> list[str]:
    if not image_file:
        return []
    return [img.strip() for img in image_file.split("|") if img and img.strip()]


def _uploaded_files_total_bytes(files) -> int:
    total = 0
    for file_storage in files or []:
        if not file_storage:
            continue
        stream = getattr(file_storage, "stream", None)
        if not stream:
            continue
        try:
            current_pos = stream.tell()
            stream.seek(0, 2)
            total += int(stream.tell() or 0)
            stream.seek(current_pos)
        except Exception:
            continue
    return total


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


def _vendor_type_flags(shop: Shop | None) -> dict:
    allows_products = shop_allows_any(shop, "products")
    allows_services = shop_allows_any(shop, "services")
    allows_location = shop_allows_any(shop, "location")
    allows_catalog = allows_products or allows_services
    return {
        "allows_products": allows_products,
        "allows_services": allows_services,
        "allows_location": allows_location,
        "allows_catalog": allows_catalog,
        "catalog_title": "Services" if (allows_services and not allows_products) else "Produits",
        "catalog_placeholder": "Rechercher un service..." if (allows_services and not allows_products) else "Rechercher un produit...",
        "catalog_create_label": "Nouveau service" if (allows_services and not allows_products) else "Nouveau produit",
        "catalog_empty_label": "Aucun service trouve" if (allows_services and not allows_products) else "Aucun produit trouve",
    }


def _scope_catalog_query(query, allows_products: bool, allows_services: bool):
    if allows_products and not allows_services:
        return query.filter(Product.kind != "service")
    if allows_services and not allows_products:
        return query.filter(Product.kind == "service")
    return query


def _category_type_for_kind(kind: str | None) -> str:
    return Category.type_from_product_kind(kind)


def _load_categories_by_kind() -> dict[str, list[Category]]:
    return {
        "physical": Category.query.filter_by(category_type="products").order_by(Category.name.asc()).all(),
        "service": Category.query.filter_by(category_type="services").order_by(Category.name.asc()).all(),
    }


def _validate_category_for_kind(category_id: int, kind: str) -> Category | None:
    category = Category.query.get(category_id)
    if not category:
        return None
    expected = _category_type_for_kind(kind)
    return category if category.normalized_type == expected else None


def _require_physical_vendor_access(strict_forbidden: bool = True):
    return ensure_vendor_allows(
        current_user,
        "products",
        fallback_endpoint="vendor.dashboard",
        strict_forbidden=strict_forbidden,
    )

# ==================== DASHBOARD & GESTION PRODUITS ====================

@bp.route("/dashboard")
@login_required
def dashboard():
    if not hasattr(current_user, "role") or current_user.role != "vendor":
        flash("Acces reserve aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    vendor_user = db.session.get(User, current_user.id) or current_user
    shop = resolve_vendor_shop(vendor_user)
    if not shop:
        flash("Vous devez d'abord creer votre boutique.", "warning")
        return redirect(url_for("vendor.create_shop"))

    type_flags = _vendor_type_flags(shop)
    allows_products = type_flags["allows_products"]
    allows_services = type_flags["allows_services"]
    allows_location = type_flags["allows_location"]
    allows_catalog = type_flags["allows_catalog"]

    if request.args.get("get_categories"):
        if not allows_catalog:
            return jsonify({"categories": []})

        allowed_category_types = []
        if allows_products:
            allowed_category_types.append("products")
        if allows_services:
            allowed_category_types.append("services")
        if not allowed_category_types:
            return jsonify({"categories": []})

        join_conditions = [
            Product.category_id == Category.id,
            Product.vendor_id == current_user.id,
        ]
        if allows_products and not allows_services:
            join_conditions.append(Product.kind != "service")
        elif allows_services and not allows_products:
            join_conditions.append(Product.kind == "service")

        categories = (
            db.session.query(
                Category.id,
                Category.name,
                db.func.count(Product.id).label("count"),
            )
            .join(Product, db.and_(*join_conditions), isouter=True)
            .filter(Category.category_type.in_(allowed_category_types))
            .group_by(Category.id)
            .order_by(Category.name.asc())
            .all()
        )
        return jsonify({
            "categories": [
                {"id": cat.id, "name": cat.name, "count": cat.count or 0}
                for cat in categories
            ]
        })

    if not allows_catalog:
        if allows_location:
            if _is_ajax_request():
                return jsonify({"success": True, "redirect_url": url_for("rentals.owner_locations")})
            return redirect(url_for("rentals.owner_locations"))
        flash("Non autorise pour votre type de boutique.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    open_period = None
    if allows_products:
        open_period = _get_open_period(current_user.id)
        if not open_period:
            flash("Veuillez ouvrir une periode avant d'acceder a votre espace vendeur.", "warning")
            return redirect(url_for("vendor.periods"))

    page = page_from_args(request.args)
    per_page = 20
    product_query = Product.query.filter_by(vendor_id=current_user.id)
    product_query = _scope_catalog_query(product_query, allows_products, allows_services)
    product_query = product_query.order_by(Product.created_at.desc())
    pagination = product_query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items

    settings = PlatformSettings.get()
    try:
        low_stock_threshold = int(settings.low_stock_threshold or 5)
    except (TypeError, ValueError):
        low_stock_threshold = 5
    if low_stock_threshold < 0:
        low_stock_threshold = 0

    show_stock_alerts = allows_products
    low_stock_total = 0
    no_image_total = 0
    low_stock_products = []
    no_image_products = []
    if show_stock_alerts:
        low_stock_query = Product.query.filter(
            Product.vendor_id == current_user.id,
            Product.kind != "service",
            Product.stock <= low_stock_threshold,
        )
        no_image_query = Product.query.filter(
            Product.vendor_id == current_user.id,
            Product.kind != "service",
            or_(Product.image_file.is_(None), Product.image_file == ""),
        )
        low_stock_total = low_stock_query.count()
        no_image_total = no_image_query.count()
        low_stock_products = low_stock_query.order_by(Product.stock.asc()).limit(5).all()
        no_image_products = no_image_query.order_by(Product.created_at.desc()).limit(5).all()

    total_products = pagination.total
    total_orders = 0
    total_revenue = 0.0
    if allows_products and open_period:
        start = open_period.start_at or datetime.utcnow()
        end = open_period.end_at or datetime.utcnow()
        if end <= start:
            end = start + timedelta(days=1)

        orders_query = (
            db.session.query(db.func.count(db.func.distinct(Order.id)))
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(Product, Product.id == OrderItem.product_id)
            .filter(Product.vendor_id == current_user.id)
            .filter(Product.kind != "service")
            .filter(Order.created_at >= start, Order.created_at < end)
        )
        total_orders = int(orders_query.scalar() or 0)

        revenue_query = (
            db.session.query(db.func.sum(OrderItem.price * OrderItem.quantity))
            .join(Order, Order.id == OrderItem.order_id)
            .join(Product, Product.id == OrderItem.product_id)
            .filter(Product.vendor_id == current_user.id)
            .filter(Product.kind != "service")
            .filter(Order.created_at >= start, Order.created_at < end)
        )
        total_revenue = float((revenue_query.scalar() or 0) / 100)

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    today_prepare = []
    today_bookings = []
    today_locations_count = 0

    try:
        if allows_products:
            order_rows = (
                db.session.query(
                    Order.id.label("order_id"),
                    Order.created_at.label("created_at"),
                    db.func.sum(OrderItem.quantity).label("items_qty"),
                    db.func.sum(OrderItem.price * OrderItem.quantity).label("amount_cents"),
                )
                .join(OrderItem, OrderItem.order_id == Order.id)
                .join(Product, Product.id == OrderItem.product_id)
                .filter(Product.vendor_id == current_user.id)
                .filter(Product.kind != "service")
                .filter(Order.status == "pending")
                .filter(Order.created_at >= today_start, Order.created_at < today_end)
                .group_by(Order.id, Order.created_at)
                .order_by(Order.created_at.desc())
                .all()
            )

            for row in order_rows:
                today_prepare.append({
                    "order_id": int(row.order_id),
                    "created_at": row.created_at,
                    "items_qty": int(row.items_qty or 0),
                    "amount_cents": int(row.amount_cents or 0),
                })

        if allows_services:
            today_bookings = (
                Booking.query
                .join(Product, Product.id == Booking.product_id)
                .filter(Product.vendor_id == current_user.id)
                .filter(Product.kind == "service")
                .filter(Booking.scheduled_for.isnot(None))
                .filter(Booking.scheduled_for >= today_start, Booking.scheduled_for < today_end)
                .filter(Booking.status.in_(["pending", "confirmed"]))
                .order_by(Booking.scheduled_for.asc())
                .limit(30)
                .all()
            )

        if allows_location:
            today_locations_count = (
                RentalListing.query
                .filter(RentalListing.owner_id == current_user.id)
                .filter(RentalListing.is_active == True)
                .filter(RentalListing.status.in_(["active", "reserved"]))
                .count()
            )
    except Exception:
        today_prepare = []
        today_bookings = []
        today_locations_count = 0

    shop_is_open = _shop_is_currently_open(shop)
    return render_template(
        "vendor/dashboard.html",
        products=products,
        pagination=pagination,
        shop=shop,
        shops=[shop],
        open_period=open_period,
        low_stock_threshold=low_stock_threshold,
        low_stock_products=low_stock_products,
        no_image_products=no_image_products,
        low_stock_total=low_stock_total,
        no_image_total=no_image_total,
        total_products=total_products,
        total_orders=total_orders,
        total_revenue=total_revenue,
        shop_is_open=shop_is_open,
        today_prepare=today_prepare,
        today_bookings=today_bookings,
        today_locations_count=today_locations_count,
        today_prepare_count=len(today_prepare),
        today_bookings_count=len(today_bookings),
        allows_products=allows_products,
        allows_services=allows_services,
        allows_location=allows_location,
        allows_catalog=allows_catalog,
        show_stock_alerts=show_stock_alerts,
        catalog_title=type_flags["catalog_title"],
        catalog_placeholder=type_flags["catalog_placeholder"],
        catalog_create_label=type_flags["catalog_create_label"],
        catalog_empty_label=type_flags["catalog_empty_label"],
        password_change_window_active=vendor_user.password_change_window_active(),
        password_change_allowed_until=vendor_user.password_change_allowed_until,
    )


@bp.route("/password/change", methods=["POST"])
@login_required
def change_password():
    if getattr(current_user, "role", None) != "vendor":
        return redirect(url_for("shop.home"))

    vendor_user = db.session.get(User, current_user.id)
    if vendor_user is None:
        flash("Utilisateur introuvable.", "danger")
        return redirect(url_for("shop.home"))

    if not vendor_user.password_change_window_active():
        flash("Demandez a l'admin d'activer la fenetre de changement (20 min).", "warning")
        return redirect(url_for("vendor.dashboard"))

    current_password = (request.form.get("current_password") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()
    confirm_password = (request.form.get("confirm_password") or "").strip()

    if not current_password or not new_password or not confirm_password:
        flash("Tous les champs mot de passe sont obligatoires.", "warning")
        return redirect(url_for("vendor.dashboard"))
    if not vendor_user.check_password(current_password):
        flash("Mot de passe actuel incorrect.", "danger")
        return redirect(url_for("vendor.dashboard"))
    if len(new_password) < 8:
        flash("Nouveau mot de passe trop court (min 8 caracteres).", "warning")
        return redirect(url_for("vendor.dashboard"))
    if new_password != confirm_password:
        flash("Confirmation mot de passe non correspondante.", "warning")
        return redirect(url_for("vendor.dashboard"))

    vendor_user.set_password(new_password)
    vendor_user.password_change_allowed_until = None
    db.session.commit()
    log_access("vendor_change_password", "user", vendor_user.id, success=True)
    flash("Mot de passe mis a jour avec succes.", "success")
    return redirect(url_for("vendor.dashboard"))


@bp.route("/product/new", methods=["GET", "POST"])
@login_required
def product_new():
    if current_user.role != "vendor":
        flash("Accs rserv aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    # Vrifier que le vendeur a une boutique
    shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    if not shop:
        flash("Vous devez d'abord crer votre boutique", "warning")
        return redirect(url_for("vendor.create_shop"))

    if not shop_allows_any(shop, "products", "services"):
        flash("Cette boutique n'autorise pas la creation de produits ou services.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    categories_by_kind = _load_categories_by_kind()
    type_flags = _vendor_type_flags(shop)
    allows_products = type_flags["allows_products"]
    allows_services = type_flags["allows_services"]

    if request.method == "POST":
        name = request.form["name"].strip()
        description = request.form.get("description", "").strip()
        kind = (request.form.get("kind") or "physical").strip().lower()
        if kind not in ("physical", "service"):
            kind = "physical"
        access_guard = ensure_shop_allows(
            shop,
            shop_type_from_product_kind(kind),
            fallback_endpoint="vendor.manage_shop",
        )
        if access_guard:
            return access_guard
        price = float(request.form["price"])
        if kind == "service":
            stock = 0
        else:
            stock = int(request.form.get("stock", 0))
        try:
            category_id = int(request.form["category_id"])
        except (TypeError, ValueError):
            flash("Categorie invalide.", "danger")
            return redirect(url_for("vendor.product_new"))

        category = _validate_category_for_kind(category_id, kind)
        if not category:
            expected_label = "Services" if kind == "service" else "Produits"
            flash(f"Choisissez une categorie valide ({expected_label}).", "warning")
            return redirect(url_for("vendor.product_new"))

        files = [f for f in request.files.getlist("images") if f and (f.filename or "").strip()]
        if len(files) > MAX_PRODUCT_IMAGES:
            flash(f"Maximum {MAX_PRODUCT_IMAGES} photos autorises.", "warning")
            return redirect(url_for("vendor.product_new"))

        uploaded_total_bytes = _uploaded_files_total_bytes(files)
        if uploaded_total_bytes > MAX_PRODUCT_IMAGES_TOTAL_BYTES:
            flash("Taille totale des photos dpasse (max 15 MB).", "warning")
            return redirect(url_for("vendor.product_new"))

        filenames = []
        for f in files:
            if f and allowed_file(f.filename):
                saved = save_image(f)
                if saved:
                    filenames.append(saved)
        if len(filenames) != len(files):
            flash("Certains fichiers ne sont pas des images supportes (png, jpg, jpeg, webp).", "warning")
            return redirect(url_for("vendor.product_new"))

        image_file = "|".join(filenames) if filenames else None

        product = Product(
            kind=kind,
            name=name,
            description=description,
            price=price,
            stock=stock,
            category_id=category.id,
            image_file=image_file,
            vendor_id=current_user.id,
            shop_id=shop.id
        )
        db.session.add(product)
        db.session.commit()
        bump_catalog_version()

        log_access(
            "create_product",
            "product",
            product.id,
            success=True,
            changes={"price": product.price, "stock": product.stock, "shop_id": product.shop_id}
        )

        flash("Produit ajout  votre boutique", "success")
        return redirect(url_for("vendor.dashboard"))

    if allows_services and not allows_products:
        default_kind = "service"
    else:
        default_kind = "physical"

    available_kinds = []
    if allows_products:
        available_kinds.append("physical")
    if allows_services:
        available_kinds.append("service")

    categories = categories_by_kind["service"] if default_kind == "service" else categories_by_kind["physical"]

    return render_template(
        "vendor/product_form.html",
        categories=categories,
        categories_by_kind=categories_by_kind,
        shop=shop,
        default_kind=default_kind,
        available_kinds=available_kinds,
        allows_products=allows_products,
        allows_services=allows_services,
        form_mode_label="service" if (allows_services and not allows_products) else "produit",
    )

@bp.route("/product/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def product_edit(pid):
    product = Product.query.get_or_404(pid)

    before = {
        "kind": getattr(product, "kind", "physical"),
        "name": product.name,
        "price": product.price,
        "stock": product.stock,
        "category_id": product.category_id,
        "is_active": product.is_active,
        "image_file": product.image_file,
    }

    if current_user.role != "admin" and product.vendor_id != current_user.id:
        flash("Interdit", "danger")
        return redirect(url_for("vendor.dashboard"))

    shop = product.shop or Shop.query.filter_by(vendor_id=product.vendor_id).first()
    if current_user.role == "vendor":
        existing_guard = ensure_shop_allows(
            shop,
            shop_type_from_product_kind(getattr(product, "kind", "physical")),
            fallback_endpoint="vendor.manage_shop",
        )
        if existing_guard:
            return existing_guard

    categories_by_kind = _load_categories_by_kind()
    allows_products = True
    allows_services = True
    available_kinds = ["physical", "service"]
    if current_user.role == "vendor":
        type_flags = _vendor_type_flags(shop)
        allows_products = type_flags["allows_products"]
        allows_services = type_flags["allows_services"]
        available_kinds = []
        if allows_products:
            available_kinds.append("physical")
        if allows_services:
            available_kinds.append("service")

    if request.method == "POST":
        kind = (request.form.get("kind") or getattr(product, "kind", "physical") or "physical").strip().lower()
        if kind not in ("physical", "service"):
            kind = "physical"
        if current_user.role == "vendor":
            access_guard = ensure_shop_allows(
                shop,
                shop_type_from_product_kind(kind),
                fallback_endpoint="vendor.manage_shop",
            )
            if access_guard:
                return access_guard

        product.kind = kind
        product.name = request.form["name"].strip()
        product.description = request.form.get("description", "").strip()
        product.price = float(request.form["price"])

        try:
            category_id = int(request.form["category_id"])
        except (TypeError, ValueError):
            flash("Categorie invalide.", "danger")
            return redirect(url_for("vendor.product_edit", pid=product.id))

        category = _validate_category_for_kind(category_id, kind)
        if not category:
            expected_label = "Services" if kind == "service" else "Produits"
            flash(f"Choisissez une categorie valide ({expected_label}).", "warning")
            return redirect(url_for("vendor.product_edit", pid=product.id))
        product.category_id = category.id

        if kind == "service":
            product.stock = 0
        else:
            try:
                product.stock = int(request.form.get("stock", product.stock or 0))
            except (TypeError, ValueError):
                product.stock = product.stock or 0

        existing_images = _parse_product_images(product.image_file)
        remove_images_raw = (request.form.get("remove_images") or "").strip()
        remove_images = {part.strip() for part in remove_images_raw.split(",") if part and part.strip()}
        kept_existing_images = [img for img in existing_images if img not in remove_images]
        files = [f for f in request.files.getlist("images") if f and (f.filename or "").strip()]

        if len(kept_existing_images) + len(files) > MAX_PRODUCT_IMAGES:
            flash(f"Maximum {MAX_PRODUCT_IMAGES} photos au total (existantes + nouvelles).", "warning")
            return redirect(url_for("vendor.product_edit", pid=product.id))

        uploaded_total_bytes = _uploaded_files_total_bytes(files)
        if uploaded_total_bytes > MAX_PRODUCT_IMAGES_TOTAL_BYTES:
            flash("Taille totale des nouvelles photos depassee (max 15 MB).", "warning")
            return redirect(url_for("vendor.product_edit", pid=product.id))

        new_filenames = []
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                saved = save_image(file)
                if saved:
                    new_filenames.append(saved)

        if len(new_filenames) != len(files):
            flash("Certains fichiers ne sont pas des images supportees (png, jpg, jpeg, webp).", "warning")
            return redirect(url_for("vendor.product_edit", pid=product.id))

        all_images = (kept_existing_images + new_filenames)[:MAX_PRODUCT_IMAGES]
        product.image_file = "|".join(all_images) if all_images else None

        db.session.commit()
        bump_catalog_version()

        changed_fields = [k for k, v in before.items() if getattr(product, k) != v]
        if changed_fields:
            log_access(
                "update_product",
                "product",
                product.id,
                success=True,
                changes={
                    "fields": changed_fields,
                    "price": product.price,
                    "stock": product.stock,
                    "image_count": len(all_images),
                },
            )
        flash("Produit mis a jour", "success")
        return redirect(url_for("vendor.dashboard"))

    current_kind = getattr(product, "kind", "physical") or "physical"
    categories = categories_by_kind["service"] if current_kind == "service" else categories_by_kind["physical"]

    return render_template(
        "vendor/product_form.html",
        product=product,
        categories=categories,
        categories_by_kind=categories_by_kind,
        available_kinds=available_kinds,
        allows_products=allows_products,
        allows_services=allows_services,
        default_kind=current_kind,
        form_mode_label="service" if (allows_services and not allows_products) else "produit",
    )

def _product_delete_denied(message: str):
    if _is_ajax_request():
        return jsonify(success=False, message=message), 409
    flash(message, "warning")
    return redirect(url_for("vendor.dashboard"))


def _latest_closed_period(vendor_id: int):
    return (
        VendorPeriod.query
        .filter(
            VendorPeriod.vendor_id == vendor_id,
            VendorPeriod.status == "closed",
            VendorPeriod.closed_at.isnot(None),
        )
        .order_by(VendorPeriod.closed_at.desc())
        .first()
    )


def _has_active_order_for_product(product_id: int) -> bool:
    return (
        db.session.query(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            OrderItem.product_id == product_id,
            Order.status.in_(tuple(ACTIVE_ORDER_STATUSES)),
        )
        .first()
        is not None
    )


@bp.route("/product/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    product = Product.query.get_or_404(pid)

    # Verifier les permissions
    if current_user.role != "admin" and product.vendor_id != current_user.id:
        if _is_ajax_request():
            return jsonify(success=False, message="Interdit"), 403
        flash("Interdit", "danger")
        return redirect(url_for("vendor.dashboard"))

    if product.vendor_id:
        has_open_period = (
            db.session.query(VendorPeriod.id)
            .filter(
                VendorPeriod.vendor_id == product.vendor_id,
                VendorPeriod.status == "open",
            )
            .first()
            is not None
        )
        if has_open_period:
            return _product_delete_denied("Suppression refuse: priode vendeur encore ouverte.")

        latest_closed_period = _latest_closed_period(product.vendor_id)
        if not latest_closed_period or not latest_closed_period.closed_at:
            return _product_delete_denied("Suppression refuse: aucune priode ferme trouve.")

        unlock_at = latest_closed_period.closed_at + timedelta(days=PRODUCT_PURGE_GRACE_DAYS)
        if datetime.utcnow() < unlock_at:
            return _product_delete_denied(
                f"Suppression autorise  partir du {unlock_at.strftime('%d/%m/%Y %H:%M')}."
            )

    if _has_active_order_for_product(product.id):
        return _product_delete_denied(
            "Suppression refuse: commandes actives lies (pending/paid/processing/shipping)."
        )

    # Purge archivee: on supprime aussi les lignes order_item liees au produit.
    db.session.execute(text("DELETE FROM order_item WHERE product_id = :pid"), {"pid": product.id})
    db.session.delete(product)
    db.session.commit()
    bump_catalog_version()

    try:
        log_access(
            "delete_product",
            "product",
            product.id,
            success=True,
            changes={"name": product.name, "price": product.price}
        )
    except Exception:
        pass

    if _is_ajax_request():
        return jsonify(success=True, product_id=product.id)

    flash("Produit supprim avec succs.", "success")
    return redirect(url_for("vendor.dashboard"))


# ==================== GESTION BOUTIQUE ====================

@bp.route("/shop/manage")
@login_required
def manage_shop():
    """Page de gestion de la boutique"""
    if current_user.role != "vendor":
        flash("Accs rserv aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    # Vrifier si le vendeur a une boutique
    shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    shop_locations = []
    location_views_total = 0
    location_top = []
    location_active_count = 0

    if shop:
        type_flags = _vendor_type_flags(shop)
        shop_locations = (
            RentalListing.query
            .filter_by(owner_id=current_user.id, shop_id=shop.id)
            .order_by(RentalListing.created_at.desc())
            .limit(12)
            .all()
        )
        location_views_total = sum(int(row.view_count or 0) for row in shop_locations)
        location_top = sorted(shop_locations, key=lambda row: int(row.view_count or 0), reverse=True)[:5]
        location_active_count = sum(1 for row in shop_locations if row.status == "active")
    else:
        type_flags = {
            "allows_products": False,
            "allows_services": False,
            "allows_location": False,
            "allows_catalog": False,
            "catalog_title": "Catalogue",
            "catalog_placeholder": "Rechercher...",
            "catalog_create_label": "Nouveau",
            "catalog_empty_label": "Aucun element",
        }

    return render_template(
        "vendor/manage_shop.html",
        shop=shop,
        shop_locations=shop_locations,
        location_views_total=location_views_total,
        location_top=location_top,
        location_active_count=location_active_count,
        shop_type_labels=SHOP_TYPE_LABELS,
        allows_products=type_flags["allows_products"],
        allows_services=type_flags["allows_services"],
        allows_location=type_flags["allows_location"],
        allows_catalog=type_flags["allows_catalog"],
        catalog_title=type_flags["catalog_title"],
        catalog_create_label=type_flags["catalog_create_label"],
    )

@bp.route("/shop/create", methods=["GET", "POST"])
@login_required
def create_shop():
    """Crer une boutique"""
    if current_user.role != "vendor":
        flash("Accs rserv aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    # Vrifier si le vendeur a dj une boutique
    existing_shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    if existing_shop:
        flash("Vous avez dj une boutique", "info")
        return redirect(url_for("vendor.manage_shop"))

    if request.method == "POST":
        try:
            name = request.form["name"].strip()
            description = request.form.get("description", "").strip()
            contact_phone = request.form.get("contact_phone", "").strip()
            contact_email = request.form.get("contact_email", current_user.email)
            address = request.form.get("address", "").strip()
            primary_type = normalize_shop_type(request.form.get("primary_type")) or "products"

            if not name:
                flash("Le nom de la boutique est requis", "danger")
                return redirect(url_for("vendor.create_shop"))

            # Crer le slug
            slug = slugify(name)

            # Vrifier si le slug existe dj
            counter = 1
            original_slug = slug
            while Shop.query.filter_by(slug=slug).first():
                slug = f"{original_slug}-{counter}"
                counter += 1

            # Crer la boutique
            shop = Shop(
                vendor_id=current_user.id,
                name=name,
                slug=slug,
                description=description,
                contact_phone=contact_phone,
                contact_email=contact_email,
                address=address,
                primary_type=primary_type,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            shop.set_allowed_types([primary_type])

            # Grer le logo si fourni
            if 'logo' in request.files:
                file = request.files['logo']
                if file and file.filename and allowed_file(file.filename):
                    logo_filename = save_image(file)
                    if logo_filename:
                        shop.logo = logo_filename

            db.session.add(shop)
            db.session.flush()  # Pour obtenir l'ID

            # Mettre  jour les produits existants du vendeur
            products = Product.query.filter_by(vendor_id=current_user.id).all()
            for product in products:
                product.shop_id = shop.id

            db.session.commit()
            bump_catalog_version()

            log_access(
                "create_shop",
                "shop",
                shop.id,
                success=True,
                changes={"name": shop.name, "vendor_id": current_user.id}
            )

            flash(" Boutique cre avec succs !", "success")
            return redirect(url_for("vendor.manage_shop"))

        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "vendor.create_shop.failed",
                extra={"vendor_id": getattr(current_user, "id", None)},
            )
            flash("Erreur lors de la cration de la boutique", "danger")
            return redirect(url_for("vendor.create_shop"))

    return render_template(
        "vendor/create_shop.html",
        shop_type_order=SHOP_TYPE_ORDER,
        shop_type_labels=SHOP_TYPE_LABELS,
    )

@bp.route("/shop/edit", methods=["GET", "POST"])
@login_required
def edit_shop():
    """Modifier la boutique"""
    if current_user.role != "vendor":
        flash("Accs rserv aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    # Rcuprer la boutique du vendeur
    shop = Shop.query.filter_by(vendor_id=current_user.id).first()

    if not shop:
        flash("Vous n'avez pas encore de boutique", "warning")
        return redirect(url_for("vendor.create_shop"))

    if request.method == "POST":
        before = {
            "name": shop.name,
            "description": shop.description,
            "contact_phone": shop.contact_phone,
            "contact_email": shop.contact_email,
            "address": shop.address,
            "logo": shop.logo,
        }
        try:
            shop.name = request.form["name"].strip()
            shop.description = request.form.get("description", "").strip()
            shop.contact_phone = request.form.get("contact_phone", "").strip()
            shop.contact_email = request.form.get("contact_email", shop.contact_email)
            shop.address = request.form.get("address", "").strip()

            # Mettre  jour le slug si le nom a chang
            new_slug = slugify(shop.name)
            if new_slug != shop.slug:
                # Vrifier si le nouveau slug est disponible
                counter = 1
                original_slug = new_slug
                while Shop.query.filter(Shop.slug == new_slug, Shop.id != shop.id).first():
                    new_slug = f"{original_slug}-{counter}"
                    counter += 1
                shop.slug = new_slug

            # Grer le logo
            if 'logo' in request.files:
                file = request.files['logo']
                if file and file.filename and allowed_file(file.filename):
                    logo_filename = save_image(file)
                    if logo_filename:
                        shop.logo = logo_filename

            # Supprimer le logo si demand
            if request.form.get("remove_logo") == "on":
                shop.logo = None

            shop.updated_at = datetime.utcnow()
            db.session.commit()
            bump_catalog_version()

            changed_fields = [k for k, v in before.items() if getattr(shop, k) != v]
            if changed_fields:
                log_access(
                    "update_shop",
                    "shop",
                    shop.id,
                    success=True,
                    changes={"fields": changed_fields}
                )

            flash(" Boutique mise  jour avec succs !", "success")
            return redirect(url_for("vendor.manage_shop"))

        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "vendor.edit_shop.failed",
                extra={"vendor_id": getattr(current_user, "id", None), "shop_id": getattr(shop, "id", None)},
            )
            flash("Erreur lors de la mise  jour", "danger")

    return render_template("vendor/edit_shop.html", shop=shop)


@bp.route("/shop/service-location", methods=["POST"])
@login_required
def update_service_location():
    if current_user.role != "vendor":
        flash("Acces reserve aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    if not shop:
        flash("Boutique non trouvee", "danger")
        return redirect(url_for("vendor.create_shop"))

    if not shop_allows_any(shop, "services", "products"):
        flash("Point de retrait disponible uniquement pour les boutiques produits/services.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    shop.address = (request.form.get("service_address") or "").strip()
    shop.service_location_note = (request.form.get("service_location_note") or "").strip()[:255]

    lat_raw = (request.form.get("service_latitude") or "").strip()
    lng_raw = (request.form.get("service_longitude") or "").strip()
    clear_exact = (request.form.get("clear_exact_location") or "").strip() == "1"

    if clear_exact:
        shop.service_latitude = None
        shop.service_longitude = None
    elif lat_raw and lng_raw:
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                shop.service_latitude = lat
                shop.service_longitude = lng
            else:
                flash("Coordonnees invalides. Utilisez le bouton position exacte.", "warning")
        except (TypeError, ValueError):
            flash("Coordonnees invalides. Utilisez le bouton position exacte.", "warning")

    shop.updated_at = datetime.utcnow()
    db.session.commit()
    bump_catalog_version()

    flash("Point de retrait mis a jour (position exacte + repere).", "success")
    return redirect(url_for("vendor.manage_shop"))

@bp.route("/shop/toggle", methods=["POST"])
@login_required
def toggle_shop_status():
    """Activer/desactiver la boutique"""
    if current_user.role != "vendor":
        if _is_ajax_request():
            return jsonify(success=False, message="Acces reserve aux vendeurs"), 403
        flash("Acces reserve aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    shop = Shop.query.filter_by(vendor_id=current_user.id).first()

    if not shop:
        if _is_ajax_request():
            return jsonify(success=False, message="Boutique non trouvee"), 404
        flash("Boutique non trouvee", "danger")
        return redirect(url_for("vendor.dashboard"))

    shop.is_active = not shop.is_active
    db.session.commit()
    bump_catalog_version()

    if _is_ajax_request():
        return jsonify(success=True, shop_id=shop.id, is_active=shop.is_active)

    log_access(
        "toggle_shop",
        "shop",
        shop.id,
        success=True,
        changes={"is_active": shop.is_active}
    )

    status = "activee" if shop.is_active else "desactivee"
    flash(f"Boutique {status}", "success")
    return redirect(url_for("vendor.manage_shop"))


@bp.route("/shop/set-open", methods=["POST"])
@login_required
def set_shop_open_state():
    """Ouvrir/Fermer temporairement la boutique (sans la dsactiver)."""
    shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    if not shop:
        if _is_ajax_request():
            return jsonify(success=False, message="Boutique non trouvee"), 404
        flash("Boutique non trouvee", "danger")
        return redirect(request.referrer or url_for("vendor.dashboard"))

    state = (request.form.get("state") or "").strip().lower()
    if state not in ("open", "closed"):
        if _is_ajax_request():
            return jsonify(success=False, message="Etat invalide"), 400
        flash("Etat invalide.", "warning")
        return redirect(request.referrer or url_for("vendor.dashboard"))

    now = datetime.utcnow()
    if state == "open":
        shop.is_open = True
        shop.closed_until = None
        shop.closed_note = None
    else:
        shop.is_open = False
        shop.closed_note = (request.form.get("closed_note") or "").strip()[:255] or None
        until_raw = (request.form.get("closed_until") or "").strip()
        closed_until = None
        if until_raw:
            try:
                closed_until = datetime.fromisoformat(until_raw)
            except ValueError:
                closed_until = None
        if closed_until and closed_until <= now:
            closed_until = None
        shop.closed_until = closed_until

    db.session.commit()
    bump_catalog_version()

    if _is_ajax_request():
        return jsonify(
            success=True,
            shop_id=shop.id,
            is_open=bool(shop.is_open),
            closed_until=shop.closed_until.isoformat() if shop.closed_until else None,
        )

    flash("Boutique ouverte." if shop.is_open else "Boutique fermee.", "success" if shop.is_open else "info")
    return redirect(request.referrer or url_for("vendor.dashboard"))


# ==================== COMMANDES ====================

@bp.route("/orders")
@login_required
def orders():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard
    return redirect(url_for("vendor.earnings"), code=302)


@bp.route("/orders/receipt/<int:oid>", methods=["POST"])
@login_required
@order_access_required
def confirm_receipt(oid):
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    vendor_id = current_user.id
    physical_order_line = (
        db.session.query(OrderItem.id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(OrderItem.order_id == oid)
        .filter(Product.vendor_id == vendor_id)
        .filter(Product.kind != "service")
        .first()
    )
    if not physical_order_line:
        flash("Cette commande ne contient aucun produit physique confirmable.", "warning")
        return redirect(request.referrer or url_for("vendor.earnings"))

    existing = VendorReceipt.query.filter_by(vendor_id=vendor_id, order_id=oid).first()
    if existing:
        flash("Encaissement dj confirm.", "info")
        return redirect(request.referrer or url_for("vendor.earnings"))

    period = _get_or_create_open_period(vendor_id)
    note = (request.form.get("note") or "").strip()[:255] or None

    receipt = VendorReceipt(
        vendor_id=vendor_id,
        order_id=oid,
        period_id=period.id,
        received_at=datetime.utcnow(),
        note=note,
        created_at=datetime.utcnow(),
    )
    db.session.add(receipt)
    db.session.commit()

    flash("Encaissement confirm.", "success")
    return redirect(request.referrer or url_for("vendor.earnings"))


@bp.route("/orders/notifications")
@login_required
def orders_notifications():
    if current_user.role not in ("vendor", "admin"):
        return jsonify(latest_id=0, pending_count=0, to_confirm_count=0)

    vendor_shop = resolve_vendor_shop(current_user)
    vendor_allows_products = shop_allows_any(vendor_shop, "products")

    query = Order.query.join(OrderItem).join(Product)
    if current_user.role == "vendor":
        query = query.filter(Product.vendor_id == current_user.id)

    latest_order = query.order_by(Order.created_at.desc()).distinct().first()
    latest_order_id = latest_order.id if latest_order else 0
    pending_count = query.filter(Order.status == "pending").with_entities(Order.id).distinct().count()

    to_confirm_count = 0
    if current_user.role != "vendor" or vendor_allows_products:
        to_confirm_query = query.filter(Order.status.in_(["shipped", "delivered"]))
        if current_user.role == "vendor":
            to_confirm_query = to_confirm_query.filter(Product.kind != "service")
            to_confirm_query = to_confirm_query.outerjoin(
                VendorReceipt,
                and_(VendorReceipt.order_id == Order.id, VendorReceipt.vendor_id == current_user.id),
            ).filter(VendorReceipt.id.is_(None))
        to_confirm_count = to_confirm_query.with_entities(Order.id).distinct().count()

    items = []
    message = ""
    if latest_order:
        items_query = OrderItem.query.join(Product).filter(OrderItem.order_id == latest_order.id)
        if current_user.role == "vendor":
            items_query = items_query.filter(Product.vendor_id == current_user.id)
        for item in items_query.all():
            name = item.product.name if item.product and item.product.name else f"Produit #{item.product_id}"
            items.append({
                "name": name,
                "qty": item.quantity or 0
            })
        if items:
            parts = [f"{i['name']} x{i['qty']}" for i in items[:3]]
            if len(items) > 3:
                parts.append(f"+{len(items) - 3} autres")
            message = "Nouvelle commande: " + ", ".join(parts)

    return jsonify(
        latest_id=latest_order_id,
        pending_count=pending_count,
        to_confirm_count=to_confirm_count,
        items=items,
        message=message
    )

@bp.route("/order/<int:oid>")
@login_required
@order_access_required
def order_detail(oid):
    order = Order.query.options(
        selectinload(Order.items).selectinload(OrderItem.product)
    ).get_or_404(oid)

    # Audit (acces autorise)
    log_access("view_order", "order", order.id, success=True)

    # Dfinir les numros de contact
    admin_phone = "+212600000000"
    delivery_phone = "+212611111111"

    return render_template(
        "vendor/order_detail.html",
        order=order,
        admin_phone=admin_phone,
        delivery_phone=delivery_phone
    )

# ==================== PRIODES (LIVRE VENDEUR) ====================

def _get_open_period(vendor_id: int):
    return (
        VendorPeriod.query
        .filter_by(vendor_id=vendor_id, status="open")
        .order_by(VendorPeriod.created_at.desc())
        .first()
    )


def _get_or_create_open_period(vendor_id: int):
    period = _get_open_period(vendor_id)
    if period:
        return period

    earliest_order_at = (
        db.session.query(db.func.min(Order.created_at))
        .join(OrderItem)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(Product.vendor_id == vendor_id)
        .filter(Product.kind != "service")
        .scalar()
    )
    start_at = earliest_order_at or datetime.utcnow()
    period = VendorPeriod(
        vendor_id=vendor_id,
        name=f"Priode {start_at.strftime('%Y-%m')}",
        start_at=start_at,
        status="open",
        created_at=datetime.utcnow(),
    )
    db.session.add(period)
    db.session.commit()
    return period


def _parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


@bp.route("/periods")
@login_required
def periods():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    vendor_id = current_user.id
    open_period = _get_open_period(vendor_id)
    periods = (
        VendorPeriod.query
        .filter_by(vendor_id=vendor_id)
        .order_by(VendorPeriod.created_at.desc())
        .all()
    )
    return render_template(
        "vendor/periods.html",
        open_period=open_period,
        periods=periods,
    )


@bp.route("/periods/open", methods=["POST"])
@login_required
def open_period():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    vendor_id = current_user.id
    if _get_open_period(vendor_id):
        flash("Vous avez dj une priode ouverte.", "warning")
        return redirect(url_for("vendor.periods"))

    name = (request.form.get("name") or "").strip()[:120]
    start_raw = (request.form.get("start_date") or "").strip()
    start_at = _parse_date(start_raw) or datetime.utcnow()
    now = datetime.utcnow()
    if start_at > now:
        start_at = now

    if not name:
        name = f"Priode {start_at.strftime('%Y-%m')}"

    period = VendorPeriod(
        vendor_id=vendor_id,
        name=name,
        start_at=start_at,
        status="open",
        created_at=datetime.utcnow(),
    )
    db.session.add(period)
    db.session.commit()
    flash("Priode ouverte.", "success")
    return redirect(url_for("vendor.periods"))


@bp.route("/periods/close/<int:period_id>", methods=["POST"])
@login_required
def close_period(period_id):
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    period = VendorPeriod.query.filter_by(id=period_id, vendor_id=current_user.id).first_or_404()
    if period.status != "open":
        flash("Cette priode est dj ferme.", "info")
        return redirect(url_for("vendor.periods"))

    force = (request.form.get("force") or "").strip() == "1"
    if not force:
        start = period.start_at or datetime.utcnow()
        end = datetime.utcnow()
        if end <= start:
            end = start + timedelta(days=1)

        to_confirm_count = (
            Order.query
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(Product, Product.id == OrderItem.product_id)
            .filter(Product.vendor_id == current_user.id)
            .filter(Product.kind != "service")
            .filter(Order.created_at >= start, Order.created_at < end)
            .filter(Order.status.in_(["shipped", "delivered"]))
            .outerjoin(
                VendorReceipt,
                and_(VendorReceipt.order_id == Order.id, VendorReceipt.vendor_id == current_user.id),
            )
            .filter(VendorReceipt.id.is_(None))
            .with_entities(Order.id)
            .distinct()
            .count()
        )

        if to_confirm_count > 0:
            return render_template(
                "vendor/period_close_confirm.html",
                period=period,
                to_confirm_count=to_confirm_count,
            )

    now = datetime.utcnow()
    period.status = "closed"
    period.end_at = now
    period.closed_at = now
    db.session.commit()
    flash("Priode ferme.", "success")
    return redirect(url_for("vendor.periods"))


# ==================== SCURIT HISTORIQUE (PIN + SUPPRESSION) ====================

def _is_pin_valid(pin: str) -> bool:
    if not pin:
        return False
    pin = pin.strip()
    return pin.isdigit() and 4 <= len(pin) <= 6


@bp.route("/security", methods=["GET"])
@login_required
def security():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    vendor_id = current_user.id
    now = datetime.utcnow()

    closed_periods = (
        VendorPeriod.query
        .filter_by(vendor_id=vendor_id, status="closed")
        .order_by(VendorPeriod.id.desc())
        .all()
    )

    eligible_ids = set()
    cutoff = now - timedelta(days=21)
    for p in closed_periods:
        if p.closed_at and p.closed_at <= cutoff:
            eligible_ids.add(p.id)

    has_pin = bool(getattr(current_user, "vendor_history_pin_hash", None))

    return render_template(
        "vendor/security.html",
        closed_periods=closed_periods,
        eligible_ids=eligible_ids,
        has_pin=has_pin,
        cutoff_date=cutoff.date().isoformat(),
    )


@bp.route("/security/pin", methods=["POST"])
@login_required
def set_security_pin():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    current_pin = (request.form.get("current_pin") or "").strip()
    new_pin = (request.form.get("new_pin") or "").strip()
    confirm_pin = (request.form.get("confirm_pin") or "").strip()

    has_pin = bool(getattr(current_user, "vendor_history_pin_hash", None))
    if has_pin and not current_user.check_vendor_history_pin(current_pin):
        flash("PIN actuel incorrect.", "danger")
        return redirect(url_for("vendor.security"))

    if new_pin != confirm_pin:
        flash("Les deux PIN ne correspondent pas.", "warning")
        return redirect(url_for("vendor.security"))

    if not _is_pin_valid(new_pin):
        flash("PIN invalide. Utilisez 4  6 chiffres.", "warning")
        return redirect(url_for("vendor.security"))

    current_user.set_vendor_history_pin(new_pin)
    db.session.commit()

    flash("PIN historique mis  jour.", "success")
    return redirect(url_for("vendor.security"))


@bp.route("/security/delete-period/<int:period_id>", methods=["POST"])
@login_required
def delete_period(period_id):
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    pin = (request.form.get("pin") or "").strip()
    if not getattr(current_user, "vendor_history_pin_hash", None):
        flash("Veuillez d'abord crer un PIN pour la suppression.", "warning")
        return redirect(url_for("vendor.security"))

    if not current_user.check_vendor_history_pin(pin):
        flash("PIN incorrect.", "danger")
        return redirect(url_for("vendor.security"))

    period = VendorPeriod.query.filter_by(id=period_id, vendor_id=current_user.id).first_or_404()
    if period.status != "closed":
        flash("Seules les priodes fermes peuvent tre supprimes.", "warning")
        return redirect(url_for("vendor.security"))

    if not period.closed_at or datetime.utcnow() - period.closed_at < timedelta(days=21):
        flash("Suppression possible uniquement aprs 21 jours.", "warning")
        return redirect(url_for("vendor.security"))

    VendorReceipt.query.filter_by(vendor_id=current_user.id, period_id=period.id).delete(synchronize_session=False)
    db.session.delete(period)
    db.session.commit()

    flash("Priode supprime dfinitivement.", "success")
    return redirect(url_for("vendor.security"))

# ==================== REVENUS ====================

@bp.route("/earnings")
@login_required
def earnings():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    vendor_id = current_user.id

    open_period = _get_or_create_open_period(vendor_id)
    period_id = request.args.get("period", type=int) or open_period.id

    periods = (
        VendorPeriod.query
        .filter_by(vendor_id=vendor_id)
        .order_by(VendorPeriod.created_at.desc())
        .all()
    )
    selected_period = next((p for p in periods if p.id == period_id), open_period)

    start = selected_period.start_at or datetime.utcnow()
    end = selected_period.end_at or datetime.utcnow()

    date_from_raw = (request.args.get("from") or "").strip()
    date_to_raw = (request.args.get("to") or "").strip()
    date_from = _parse_date(date_from_raw) if date_from_raw else None
    date_to = _parse_date(date_to_raw) if date_to_raw else None

    if date_from and date_from > start:
        start = date_from
    if date_to:
        end_to = date_to + timedelta(days=1)
        if end_to < end:
            end = end_to

    if end <= start:
        end = start + timedelta(days=1)

    # 1) Montant par commande (source: OrderItem.price * qty)
    rows = (
        db.session.query(
            OrderItem.order_id.label("order_id"),
            db.func.sum(OrderItem.price * OrderItem.quantity).label("amount_cents"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(Product.vendor_id == vendor_id)
        .filter(Product.kind != "service")
        .filter(Order.created_at >= start, Order.created_at < end)
        .group_by(OrderItem.order_id)
        .all()
    )
    order_amount_map = {r.order_id: int(r.amount_cents or 0) for r in rows}
    order_ids = list(order_amount_map.keys())

    receipt_map = {}
    if order_ids:
        receipts = VendorReceipt.query.filter(
            VendorReceipt.vendor_id == vendor_id,
            VendorReceipt.order_id.in_(order_ids)
        ).all()
        receipt_map = {r.order_id: r for r in receipts}

    confirmed_ids = set(receipt_map.keys())
    total_confirmed = sum(order_amount_map.get(oid, 0) for oid in confirmed_ids)
    total_pending = sum(amount for oid, amount in order_amount_map.items() if oid not in confirmed_ids)

    # 2) Liste des commandes (avec pagination)
    show = (request.args.get("show") or "all").strip().lower()  # all|pending|confirmed
    list_ids = order_ids
    if show == "pending":
        list_ids = [oid for oid in order_ids if oid not in confirmed_ids]
    elif show == "confirmed":
        list_ids = [oid for oid in order_ids if oid in confirmed_ids]

    base_list_query = (
        Order.query.options(selectinload(Order.items).selectinload(OrderItem.product))
        .filter(Order.id.in_(list_ids or [-1]))
        .order_by(Order.created_at.desc())
    )

    page = page_from_args(request.args)
    pagination = base_list_query.paginate(page=page, per_page=30, error_out=False)
    orders = pagination.items

    return render_template(
        "vendor/earnings.html",
        periods=periods,
        selected_period=selected_period,
        open_period=open_period,
        date_from=date_from_raw,
        date_to=date_to_raw,
        show=show,
        orders=orders,
        pagination=pagination,
        receipt_map=receipt_map,
        order_amount_map=order_amount_map,
        total_confirmed=total_confirmed,
        total_pending=total_pending,
    )


@bp.route("/earnings/history")
@login_required
def earnings_history():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    flash("Historique remplac par les priodes.", "info")
    return redirect(url_for("vendor.periods"))


@bp.route("/earnings/history/export.csv")
@login_required
def earnings_history_export_csv():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    flash("Export dsactiv dans le nouveau livre vendeur.", "info")
    return redirect(url_for("vendor.periods"))


@bp.route("/earnings/history/export.pdf")
@login_required
def earnings_history_export_pdf():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    flash("Export dsactiv dans le nouveau livre vendeur.", "info")
    return redirect(url_for("vendor.periods"))


def _history_query(vendor_id, date_from, date_to):
    cutoff = datetime.utcnow() - timedelta(hours=72)
    query = VendorPayout.query.join(Order).filter(
        VendorPayout.vendor_id == vendor_id,
        VendorPayout.status == "paid",
        VendorPayout.paid_at.isnot(None),
        VendorPayout.paid_at <= cutoff
    ).options(
        selectinload(VendorPayout.order)
        .selectinload(Order.items)
        .selectinload(OrderItem.product)
    )

    try:
        if date_from:
            start = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(VendorPayout.paid_at >= start)
        if date_to:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(VendorPayout.paid_at < end)
    except ValueError:
        pass

    return query.order_by(VendorPayout.paid_at.desc())


def _format_products(order, vendor_id):
    if not order:
        return ""
    parts = []
    for item in order.items:
        if item.product and item.product.vendor_id == vendor_id:
            name = item.product.name or f"Produit #{item.product_id}"
            qty = item.quantity or 0
            parts.append(f"{name} x{qty}")
    return ", ".join(parts)


@bp.route("/earnings/confirm/<int:payout_id>", methods=["POST"])
@login_required
def confirm_payout(payout_id):
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    flash("Cette action a t remplace par Je suis pay sur vos commandes.", "info")
    return redirect(url_for("vendor.earnings"))


# ==================== ROUTES AJAX/API POUR VENDEURS ====================

@bp.route("/api/shop/stats")
@login_required
def shop_stats_api():
    """API pour les statistiques de la boutique"""
    if current_user.role != "vendor":
        return jsonify({"error": "Accs interdit"}), 403

    shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    if not shop:
        return jsonify({"error": "Boutique non trouve"}), 404

    # Statistiques
    product_count = Product.query.filter_by(shop_id=shop.id).count()

    # Commandes du mois
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    orders_this_month = Order.query.join(OrderItem).join(Product).filter(
        Product.shop_id == shop.id,
        Order.created_at >= start_of_month,
        Order.status == "delivered"
    ).count()

    # Revenus du mois
    revenue_this_month_cents = 0
    month_orders = Order.query.join(OrderItem).join(Product).filter(
        Product.shop_id == shop.id,
        Order.created_at >= start_of_month,
        Order.status == "delivered"
    ).all()

    for order in month_orders:
        for item in order.items:
            if item.product.shop_id == shop.id:
                revenue_this_month_cents += (item.price or 0) * (item.quantity or 0)

    return jsonify({
        "shop": {
            "name": shop.name,
            "product_count": product_count,
            "orders_this_month": orders_this_month,
            "revenue_this_month": revenue_this_month_cents / 100,
            "is_active": shop.is_active,
            "rating": shop.rating or 0
        }
    })

@bp.route("/api/products/stock")
@login_required
def products_stock_api():
    """API pour la gestion des stocks"""
    if current_user.role != "vendor":
        return jsonify({"error": "Accs interdit"}), 403

    products = Product.query.filter_by(vendor_id=current_user.id).all()

    stock_data = []
    for product in products:
        stock_data.append({
            "id": product.id,
            "name": product.name,
            "stock": product.stock,
            "price": product.price,
            "is_active": product.is_active,
            "image": product.image_file.split('|')[0] if product.image_file else None
        })

    return jsonify({"products": stock_data})

# ==================== REDIRECTIONS POUR COMPATIBILIT ====================

@bp.route("/shop/setup")
@login_required
def setup_shop_redirect():
    """Redirection pour compatibilit (ancienne route)"""
    return redirect(url_for("vendor.create_shop"))





@bp.route("/products/search")
@login_required
def products_search():
    """Recherche en temps rel des produits"""
    if not hasattr(current_user, "role") or current_user.role not in ("vendor", "admin"):
        return jsonify({"error": "Accs non autoris"}), 403

    if current_user.role == "vendor":
        shop = resolve_vendor_shop(current_user)
        type_flags = _vendor_type_flags(shop)
        if not type_flags["allows_catalog"]:
            return render_template(
                "vendor/partials/_product_grid.html",
                products=[],
                low_stock_threshold=int(PlatformSettings.get().low_stock_threshold or 5),
                search_term="",
                catalog_title="Catalogue",
                catalog_create_label="Nouveau",
            )

    search_term = request.args.get("q", "").strip()
    category_id = request.args.get("category", "")

    # Construire la requte de base
    if current_user.role == "admin":
        query = Product.query
    else:
        query = Product.query.filter_by(vendor_id=current_user.id)
        query = _scope_catalog_query(
            query,
            type_flags["allows_products"],
            type_flags["allows_services"],
        )

    # Appliquer la recherche
    if search_term:
        query = query.filter(
            db.or_(
                Product.name.ilike(f"%{search_term}%"),
                Product.description.ilike(f"%{search_term}%")
            )
        )

    # Appliquer le filtre de catgorie
    if category_id and category_id != "all":
        try:
            category_id_int = int(category_id)
            query = query.filter(Product.category_id == category_id_int)
        except ValueError:
            pass

    # Ordonner et limiter
    query = query.order_by(Product.created_at.desc())
    products = query.limit(100).all()

    # Rcuprer les paramtres pour le seuil de stock
    settings = PlatformSettings.get()
    low_stock_threshold = int(settings.low_stock_threshold or 5)

    return render_template(
        "vendor/partials/_product_grid.html",
        products=products,
        low_stock_threshold=low_stock_threshold,
        search_term=search_term,
        catalog_title=type_flags["catalog_title"] if current_user.role == "vendor" else "Produits",
        catalog_create_label=type_flags["catalog_create_label"] if current_user.role == "vendor" else "Nouveau produit",
    )


@bp.route("/stats/live")
@login_required
def stats_live():
    """Statistiques en temps rel"""
    if not hasattr(current_user, "role") or current_user.role not in ("vendor", "admin"):
        return jsonify({"error": "Accs non autoris"}), 403

    allows_products = True
    if current_user.role == "vendor":
        vendor_shop = resolve_vendor_shop(current_user)
        vendor_flags = _vendor_type_flags(vendor_shop)
        allows_products = vendor_flags["allows_products"]

    open_period = _get_open_period(current_user.id) if allows_products else None
    if current_user.role != "admin" and allows_products and not open_period:
        return jsonify({
            "success": True,
            "total_orders": 0,
            "total_revenue": "0",
            "low_stock": 0
        })

    start = (open_period.start_at if open_period else None) or datetime.utcnow()
    end = (open_period.end_at if open_period else None) or datetime.utcnow()
    if end <= start:
        end = start + timedelta(days=1)

    # Compter les commandes
    if current_user.role == "admin":
        orders_query = db.session.query(db.func.count(db.func.distinct(Order.id))).join(
            OrderItem, OrderItem.order_id == Order.id
        )
    elif allows_products:
        orders_query = (
            db.session.query(db.func.count(db.func.distinct(Order.id)))
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(Product, Product.id == OrderItem.product_id)
            .filter(Product.vendor_id == current_user.id)
            .filter(Product.kind != "service")
            .filter(Order.created_at >= start, Order.created_at < end)
        )
    else:
        total_orders = 0
        orders_query = None

    if orders_query is not None:
        total_orders = int(orders_query.scalar() or 0)

    # Calculer les revenus
    if current_user.role == "admin":
        revenue_query = db.session.query(db.func.sum(OrderItem.price * OrderItem.quantity))
    elif allows_products:
        revenue_query = (
            db.session.query(db.func.sum(OrderItem.price * OrderItem.quantity))
            .join(Order, Order.id == OrderItem.order_id)
            .join(Product, Product.id == OrderItem.product_id)
            .filter(Product.vendor_id == current_user.id)
            .filter(Product.kind != "service")
            .filter(Order.created_at >= start, Order.created_at < end)
        )
    else:
        total_revenue = 0.0
        revenue_query = None

    if revenue_query is not None:
        total_revenue = float((revenue_query.scalar() or 0) / 100)

    # Compter les produits en stock faible
    settings = PlatformSettings.get()
    low_stock_threshold = int(settings.low_stock_threshold or 5)

    if current_user.role == "admin":
        low_stock = Product.query.filter(Product.stock <= low_stock_threshold).count()
    elif allows_products:
        low_stock = Product.query.filter(
            Product.vendor_id == current_user.id,
            Product.kind != "service",
            Product.stock <= low_stock_threshold
        ).count()
    else:
        low_stock = 0

    return jsonify({
        "success": True,
        "total_orders": total_orders,
        "total_revenue": f"{total_revenue:.0f}",
        "low_stock": low_stock
    })
