# app/routes/vendor.py - VERSION CORRIGE
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from ..extensions import db
from ..models.product import Product
from ..models.category import Category
from ..models.shop import SHOP_TYPE_LABELS, Shop, shop_type_from_product_kind
from ..models.promo import Promo
from ..models.order import Order, OrderItem
from ..models.booking import Booking
from ..models.user import User
from ..models.vendor_receipt import VendorReceipt
from ..models.vendor_change_request import VendorChangeRequest
from ..models.vendor_push_subscription import VendorPushSubscription
from ..models.rental import RentalListing
from ..models.platform_settings import PlatformSettings
from ..services.image import MAX_PRODUCT_VIDEO_BYTES, delete_product_video, save_image, save_product_video
from ..services.cache import bump_catalog_version
from ..services.db_session import safe_session_rollback
from ..services.featured_items import active_featured_shop_notice
from ..services.pricing import calculate_promo_price, cents_to_money, get_active_promos_for_products, set_product_price
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy import or_, and_, case
from ..services.audit import log_access
from ..services.shop_access import ensure_shop_allows, ensure_vendor_allows, resolve_vendor_shop, shop_allows_any
from ..services.pagination import page_from_args, paginate_with_clamped_page
from ..services.support_whatsapp import (
    append_support_request,
    build_support_whatsapp_url,
    safe_support_back_target,
    support_user_label,
)
from ..services.vendor_push import (
    deactivate_vendor_push_subscription,
    notify_admin_vendor_change_request,
    send_vendor_push_notification,
    upsert_vendor_push_subscription,
    vendor_push_configuration_status,
    vendor_push_public_key_is_valid,
    vendor_push_is_configured,
    vendor_push_public_key,
)
from ..middleware.security import order_access_required
from datetime import datetime, timedelta
from time import perf_counter
from sqlalchemy.exc import SQLAlchemyError
import re

bp = Blueprint("vendor", __name__)
PROMO_MAX_ACTIVE_PER_SHOP = 5
PROMO_MAX_DURATION_DAYS = 14
PROMO_MIN_PERCENT = 5

ALLOWED = {"png", "jpg", "jpeg", "webp"}
MAX_PRODUCT_IMAGES = 4
MAX_PRODUCT_IMAGES_TOTAL_BYTES = 15 * 1024 * 1024
MAX_PRODUCT_VIDEOS = 1
PRODUCT_PURGE_GRACE_DAYS = 21
ACTIVE_ORDER_STATUSES = {"pending", "paid", "processing", "shipping", "shipped"}
CASHBOOK_EXCLUDED_ORDER_STATUSES = {"cancelled", "draft", "expired"}
NEW_ORDERS_WINDOW_HOURS = 4
DASHBOARD_ORDERS_PER_PAGE_DEFAULT = 8
DASHBOARD_ORDERS_PER_PAGE_MAX = 30
DASHBOARD_BOOKINGS_PER_PAGE_DEFAULT = 8
DASHBOARD_BOOKINGS_PER_PAGE_MAX = 30
LIVE_ENDPOINT_MICROCACHE_TTL_SECONDS = 0.0
_DASHBOARD_ORDERS_LIVE_CACHE: dict[tuple, tuple[float, dict]] = {}
_EMAIL_BASIC_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VENDOR_CHANGE_TYPE_LABELS = {
    VendorChangeRequest.TYPE_ACCOUNT_EMAIL: "Email compte/boutique",
    VendorChangeRequest.TYPE_SHOP_NAME: "Nom de boutique",
}
PUSH_ALLOWED_ROLES = {"vendor", "admin", "manager"}


def _current_user_can_use_push() -> bool:
    return getattr(current_user, "role", None) in PUSH_ALLOWED_ROLES


@bp.route("/support/whatsapp")
@login_required
def support_whatsapp():
    if current_user.role != "vendor":
        flash("Interdit", "danger")
        return redirect(url_for("shop.home"))

    page_name = (request.args.get("page") or "Page vendeur").strip()[:120]
    page_url = (request.args.get("page_url") or "").strip()[:400]
    source = (request.args.get("source") or "").strip()[:160]
    item_name = (request.args.get("item") or "").strip()[:160]
    back_url = safe_support_back_target(request.args.get("back"), url_for("vendor.dashboard"))
    shop = resolve_vendor_shop(current_user)

    lines = [
        "Bonjour, je signale un probleme sur mon espace vendeur.",
        f"Compte: {support_user_label(current_user)} (id: {current_user.id})",
    ]
    if shop and getattr(shop, "name", None):
        lines.append(f"Boutique: {shop.name}")
    lines.append(f"Page: {page_name}")
    if item_name:
        lines.append(f"Element: {item_name}")
    if source:
        lines.append(f"Route: {source}")
    if page_url:
        lines.append(f"URL: {page_url}")
    append_support_request(
        lines,
        issue_type=request.args.get("issue_type"),
        details=request.args.get("details"),
        expected=request.args.get("expected"),
    )

    return render_template(
        "support/open_whatsapp.html",
        wa_url=build_support_whatsapp_url(lines),
        support_scope="Support vendeur",
        support_title="Signaler un probleme vendeur",
        support_copy="Votre message est pret avec la page, l'element et votre compte.",
        back_url=back_url,
        back_label="Retour a la page",
    )


@bp.app_context_processor
def inject_vendor_feature_notice():
    if not getattr(current_user, "is_authenticated", False):
        return {"featured_shop_notice": None}
    if getattr(current_user, "role", None) != "vendor":
        return {"featured_shop_notice": None}
    try:
        shop = resolve_vendor_shop(current_user)
    except Exception:
        shop = None
    return {
        "featured_shop_notice": active_featured_shop_notice(getattr(shop, "id", None)),
    }


def _public_base_url() -> str:
    configured = (current_app.config.get("PUBLIC_BASE_URL") or "").strip()
    if configured:
        return configured.rstrip("/")
    return request.host_url.rstrip("/")


def _public_shop_url(shop_slug: str) -> str:
    normalized_slug = str(shop_slug or "").strip().strip("/")
    if not normalized_slug:
        return _public_base_url()
    return f"{_public_base_url()}/{normalized_slug}"

@bp.before_request
@login_required
def restrict_vendor():
    if getattr(current_user, "role", None) != "vendor":
        flash("Accès réservé aux vendeurs.", "warning")
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


def _catalog_block_reasons(product: Product | None) -> list[str]:
    if not product:
        return []
    reasons: list[str] = []
    if not _parse_product_images(getattr(product, "image_file", None)):
        reasons.append("ajouter au moins une photo")
    if not str(getattr(product, "description", "") or "").strip():
        reasons.append("ajouter une description")
    if getattr(product, "kind", "physical") != "service" and int(getattr(product, "stock", 0) or 0) <= 0:
        reasons.append("mettre un stock superieur a 0")
    return reasons


def _redirect_vendor_shop_admin_only():
    flash("La creation de boutique est geree par l'administration.", "warning")
    return redirect(url_for("vendor.manage_shop"))


def _normalize_optional_email(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if not candidate:
        return ""
    return candidate if _EMAIL_BASIC_RE.match(candidate) else ""


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
        except (OSError, ValueError):
            continue
    return total


def _save_uploaded_product_images(files, *, vendor_id: int | None = None, remaining_slots: int | None = None):
    saved_filenames: list[str] = []
    skipped_invalid: list[str] = []
    skipped_overflow: list[str] = []
    slots_left = None if remaining_slots is None else max(0, int(remaining_slots))

    for file_storage in files or []:
        if not file_storage or not (getattr(file_storage, "filename", "") or "").strip():
            continue

        original_name = str(getattr(file_storage, "filename", "") or "").strip()
        allowed_by_name = allowed_file(original_name)

        current_app.logger.info(
            "[vendor] product.image_file vendor_id=%s filename=%s content_type=%s allowed_by_name=%s",
            vendor_id,
            original_name,
            getattr(file_storage, "content_type", None),
            allowed_by_name,
        )

        if not allowed_by_name:
            skipped_invalid.append(original_name)
            continue

        if slots_left is not None and len(saved_filenames) >= slots_left:
            skipped_overflow.append(original_name)
            continue

        saved = save_image(file_storage)
        current_app.logger.info(
            "[vendor] product.image_save_result vendor_id=%s filename=%s saved=%s",
            vendor_id,
            original_name,
            saved,
        )
        if saved:
            saved_filenames.append(saved)
        else:
            skipped_invalid.append(original_name)

    return saved_filenames, skipped_invalid, skipped_overflow


def _flash_product_image_notice(*, mode: str, skipped_invalid: list[str], skipped_overflow: list[str]):
    notes: list[str] = []
    if skipped_invalid:
        notes.append(
            f"{len(skipped_invalid)} photo(s) ignoree(s) car non prises en charge ou illisibles"
        )
    if skipped_overflow:
        notes.append(
            f"{len(skipped_overflow)} photo(s) ignoree(s) car la limite est de {MAX_PRODUCT_IMAGES}"
        )
    if not notes:
        return

    prefix = "Creation des photos partielle" if mode == "create" else "Mise a jour des photos partielle"
    flash(prefix + " : " + ". ".join(notes) + ".", "warning")


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


def _normalize_positive_int(
    value,
    *,
    default: int,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def _safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _log_perf(endpoint_name: str, started_at: float, **extra):
    duration_ms = round((perf_counter() - started_at) * 1000.0, 2)
    payload = {"endpoint": endpoint_name, "duration_ms": duration_ms}
    if extra:
        payload.update(extra)
    try:
        current_app.logger.info("perf %s", payload)
    except Exception:
        try:
            current_app.logger.exception("perf log failed for %s", endpoint_name)
        except Exception:
            pass


def _orders_live_cache_get(cache_key: tuple):
    if LIVE_ENDPOINT_MICROCACHE_TTL_SECONDS <= 0:
        return None
    cached = _DASHBOARD_ORDERS_LIVE_CACHE.get(cache_key)
    if not cached:
        return None
    ts, payload = cached
    if (datetime.utcnow().timestamp() - ts) > LIVE_ENDPOINT_MICROCACHE_TTL_SECONDS:
        _DASHBOARD_ORDERS_LIVE_CACHE.pop(cache_key, None)
        return None
    return payload


def _orders_live_cache_set(cache_key: tuple, payload: dict):
    if LIVE_ENDPOINT_MICROCACHE_TTL_SECONDS <= 0:
        return
    _DASHBOARD_ORDERS_LIVE_CACHE[cache_key] = (datetime.utcnow().timestamp(), payload)


def _empty_dashboard_orders_page(per_page: int) -> dict:
    return {
        "items": [],
        "count": 0,
        "page": 1,
        "pages": 1,
        "per_page": per_page,
        "has_prev": False,
        "has_next": False,
        "latest_id": 0,
    }


def _empty_dashboard_bookings_page(per_page: int) -> dict:
    return {
        "items": [],
        "count": 0,
        "page": 1,
        "pages": 1,
        "per_page": per_page,
        "has_prev": False,
        "has_next": False,
    }


def _build_dashboard_live_cards_payload(
    vendor_id: int,
    *,
    allows_products: bool,
    allows_services: bool,
    allows_location: bool,
    recent_page: int,
    prepare_page: int,
    bookings_page: int,
    per_page: int,
    bookings_per_page: int,
) -> dict:
    now_utc = datetime.utcnow()
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    recent_start = now_utc - timedelta(hours=NEW_ORDERS_WINDOW_HOURS)

    recent = _empty_dashboard_orders_page(per_page)
    today_prepare = _empty_dashboard_orders_page(per_page)
    today_bookings = _empty_dashboard_bookings_page(bookings_per_page)
    today_locations_count = 0

    if allows_products:
        recent = _pending_orders_page(
            vendor_id,
            start_at=recent_start,
            end_at=now_utc,
            page=recent_page,
            per_page=per_page,
        )
        today_prepare = _pending_orders_page(
            vendor_id,
            start_at=today_start,
            end_at=today_end,
            page=prepare_page,
            per_page=per_page,
        )

    if allows_services:
        today_bookings = _today_bookings_page(
            vendor_id,
            start_at=today_start,
            end_at=today_end,
            page=bookings_page,
            per_page=bookings_per_page,
        )

    if allows_location:
        today_locations_count = (
            RentalListing.query
            .filter(RentalListing.owner_id == vendor_id)
            .filter(RentalListing.is_active == True)
            .filter(RentalListing.status.in_(["active", "reserved"]))
            .count()
        )

    return {
        "server_time": now_utc.isoformat(),
        "recent": recent,
        "today_prepare": today_prepare,
        "today_bookings": today_bookings,
        "today_locations_count": int(today_locations_count or 0),
    }


def _pending_orders_aggregate_query(
    vendor_id: int,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    query = (
        db.session.query(
            Order.id.label("order_id"),
            Order.created_at.label("created_at"),
            db.func.sum(OrderItem.quantity).label("items_qty"),
            db.func.sum(OrderItem.price * OrderItem.quantity).label("amount_cents"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(Product.vendor_id == vendor_id)
        .filter(Product.kind != "service")
        .filter(Order.status == "pending")
    )
    if start_at is not None:
        query = query.filter(Order.created_at >= start_at)
    if end_at is not None:
        query = query.filter(Order.created_at < end_at)
    return query.group_by(Order.id, Order.created_at)


def _serialize_pending_order_row(row) -> dict:
    order_id = int(row.order_id)
    created_at = row.created_at
    amount_cents = int(row.amount_cents or 0)
    return {
        "order_id": order_id,
        "created_at_iso": created_at.isoformat() if created_at else None,
        "created_label": created_at.strftime("%H:%M") if created_at else "",
        "items_qty": int(row.items_qty or 0),
        "amount_cents": amount_cents,
        "amount_mad": round(amount_cents / 100, 2),
        "details_url": url_for("vendor.order_detail", oid=order_id),
    }


def _pending_orders_page(
    vendor_id: int,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    page: int,
    per_page: int,
) -> dict:
    per_page_safe = _normalize_positive_int(
        per_page,
        default=DASHBOARD_ORDERS_PER_PAGE_DEFAULT,
        minimum=1,
        maximum=DASHBOARD_ORDERS_PER_PAGE_MAX,
    )
    base_query = _pending_orders_aggregate_query(
        vendor_id,
        start_at=start_at,
        end_at=end_at,
    )
    aggregate_subquery = base_query.subquery()
    aggregate_row = (
        db.session.query(
            db.func.count(aggregate_subquery.c.order_id),
            db.func.max(aggregate_subquery.c.order_id),
        )
        .first()
    )
    total = int((aggregate_row[0] if aggregate_row else 0) or 0)
    latest_id = int((aggregate_row[1] if aggregate_row else 0) or 0)
    pages = max(1, ((total - 1) // per_page_safe) + 1) if total else 1
    current_page = _normalize_positive_int(page, default=1, minimum=1, maximum=pages)

    rows = []
    if total:
        rows = (
            base_query
            .order_by(Order.created_at.desc(), Order.id.desc())
            .offset((current_page - 1) * per_page_safe)
            .limit(per_page_safe)
            .all()
        )

    return {
        "items": [_serialize_pending_order_row(row) for row in rows],
        "count": total,
        "page": current_page,
        "pages": pages,
        "per_page": per_page_safe,
        "has_prev": current_page > 1,
        "has_next": current_page < pages,
        "latest_id": latest_id,
    }


def _today_bookings_base_query(vendor_id: int, *, start_at: datetime, end_at: datetime):
    return (
        Booking.query
        .join(Product, Product.id == Booking.product_id)
        .filter(Product.vendor_id == vendor_id)
        .filter(Product.kind == "service")
        .filter(Booking.scheduled_for.isnot(None))
        .filter(Booking.scheduled_for >= start_at, Booking.scheduled_for < end_at)
        .filter(Booking.status.in_(["pending", "confirmed"]))
    )


def _serialize_booking_row(booking: Booking) -> dict:
    scheduled_for = getattr(booking, "scheduled_for", None)
    phone = (getattr(booking, "phone", "") or "").strip()
    return {
        "id": int(booking.id),
        "scheduled_for_iso": scheduled_for.isoformat() if scheduled_for else None,
        "scheduled_label": scheduled_for.strftime("%H:%M") if scheduled_for else "",
        "product_name": (booking.product.name if booking.product else "Service"),
        "full_name": (getattr(booking, "full_name", "") or "").strip(),
        "phone": phone,
        "call_url": f"tel:{phone}" if phone else "",
    }


def _today_bookings_page(
    vendor_id: int,
    *,
    start_at: datetime,
    end_at: datetime,
    page: int,
    per_page: int,
) -> dict:
    per_page_safe = _normalize_positive_int(
        per_page,
        default=DASHBOARD_BOOKINGS_PER_PAGE_DEFAULT,
        minimum=1,
        maximum=DASHBOARD_BOOKINGS_PER_PAGE_MAX,
    )
    base_query = _today_bookings_base_query(
        vendor_id,
        start_at=start_at,
        end_at=end_at,
    )
    aggregate_subquery = base_query.with_entities(Booking.id).subquery()
    aggregate_row = (
        db.session.query(
            db.func.count(aggregate_subquery.c.id),
            db.func.max(aggregate_subquery.c.id),
        )
        .first()
    )
    total = int((aggregate_row[0] if aggregate_row else 0) or 0)
    latest_id = int((aggregate_row[1] if aggregate_row else 0) or 0)
    pages = max(1, ((total - 1) // per_page_safe) + 1) if total else 1
    current_page = _normalize_positive_int(page, default=1, minimum=1, maximum=pages)

    rows = []
    if total:
        rows = (
            base_query
            .options(selectinload(Booking.product))
            .order_by(Booking.scheduled_for.asc(), Booking.id.asc())
            .offset((current_page - 1) * per_page_safe)
            .limit(per_page_safe)
            .all()
        )

    return {
        "items": [_serialize_booking_row(row) for row in rows],
        "count": total,
        "page": current_page,
        "pages": pages,
        "per_page": per_page_safe,
        "has_prev": current_page > 1,
        "has_next": current_page < pages,
        "latest_id": latest_id,
    }


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


def _product_promo_snapshot(products) -> dict[int, Promo]:
    product_ids = [int(product.id) for product in (products or []) if getattr(product, "id", None) is not None]
    return get_active_promos_for_products(product_ids)


def _require_physical_vendor_access(strict_forbidden: bool = True):
    return ensure_vendor_allows(
        current_user,
        "products",
        fallback_endpoint="vendor.dashboard",
        strict_forbidden=strict_forbidden,
    )


def _shop_requires_contact_details(shop: Shop | None) -> bool:
    return bool(shop and shop_allows_any(shop, "products", "services"))


def _shop_has_required_contact_details(shop: Shop | None) -> bool:
    if not _shop_requires_contact_details(shop):
        return True
    return bool((getattr(shop, "contact_phone", "") or "").strip() and (getattr(shop, "address", "") or "").strip())


def _require_shop_contact_details(shop: Shop | None):
    if _shop_has_required_contact_details(shop):
        return None
    flash("Pour vendre des produits ou services, telephone et adresse sont obligatoires.", "warning")
    return redirect(url_for("vendor.edit_shop"))

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
        return _redirect_vendor_shop_admin_only()

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

    page = page_from_args(request.args)
    per_page = 20
    product_query = Product.query.filter_by(vendor_id=current_user.id)
    product_query = _scope_catalog_query(product_query, allows_products, allows_services)
    product_query = product_query.order_by(Product.created_at.desc(), Product.id.desc())
    pagination = paginate_with_clamped_page(product_query, page=page, per_page=per_page, error_out=False)
    products = pagination.items
    product_promos = _product_promo_snapshot(products)

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
    if allows_products:
        orders_query = (
            db.session.query(db.func.count(db.func.distinct(Order.id)))
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(Product, Product.id == OrderItem.product_id)
            .filter(Product.vendor_id == current_user.id)
            .filter(Product.kind != "service")
        )
        total_orders = int(orders_query.scalar() or 0)

        revenue_query = (
            db.session.query(db.func.sum(OrderItem.price * OrderItem.quantity))
            .join(Order, Order.id == OrderItem.order_id)
            .join(Product, Product.id == OrderItem.product_id)
            .filter(Product.vendor_id == current_user.id)
            .filter(Product.kind != "service")
        )
        total_revenue = float((revenue_query.scalar() or 0) / 100)

    recent_orders_pagination = _empty_dashboard_orders_page(DASHBOARD_ORDERS_PER_PAGE_DEFAULT)
    today_prepare_pagination = _empty_dashboard_orders_page(DASHBOARD_ORDERS_PER_PAGE_DEFAULT)
    today_bookings_pagination = _empty_dashboard_bookings_page(DASHBOARD_BOOKINGS_PER_PAGE_DEFAULT)
    recent_orders = []
    today_prepare = []
    today_bookings = []
    today_locations_count = 0

    cards_cache_key = (
        int(getattr(current_user, "id", 0) or 0),
        int(DASHBOARD_ORDERS_PER_PAGE_DEFAULT),
        int(DASHBOARD_BOOKINGS_PER_PAGE_DEFAULT),
        1,
        1,
        1,
        bool(allows_products),
        bool(allows_services),
        bool(allows_location),
    )

    try:
        cards_payload = _orders_live_cache_get(cards_cache_key)
        if cards_payload is None:
            cards_payload = _build_dashboard_live_cards_payload(
                current_user.id,
                allows_products=bool(allows_products),
                allows_services=bool(allows_services),
                allows_location=bool(allows_location),
                recent_page=1,
                prepare_page=1,
                bookings_page=1,
                per_page=DASHBOARD_ORDERS_PER_PAGE_DEFAULT,
                bookings_per_page=DASHBOARD_BOOKINGS_PER_PAGE_DEFAULT,
            )
            _orders_live_cache_set(cards_cache_key, cards_payload)

        recent_orders_pagination = cards_payload.get("recent", recent_orders_pagination)
        today_prepare_pagination = cards_payload.get("today_prepare", today_prepare_pagination)
        today_bookings_pagination = cards_payload.get("today_bookings", today_bookings_pagination)
        today_locations_count = int(cards_payload.get("today_locations_count", 0) or 0)
        recent_orders = list(recent_orders_pagination.get("items", []))
        today_prepare = list(today_prepare_pagination.get("items", []))
        today_bookings = list(today_bookings_pagination.get("items", []))
    except SQLAlchemyError:
        current_app.logger.exception(
            "vendor.dashboard.live_cards_query_failed",
            extra={"vendor_id": getattr(current_user, "id", None)},
        )
        recent_orders = []
        recent_orders_pagination = _empty_dashboard_orders_page(DASHBOARD_ORDERS_PER_PAGE_DEFAULT)
        today_prepare = []
        today_prepare_pagination = _empty_dashboard_orders_page(DASHBOARD_ORDERS_PER_PAGE_DEFAULT)
        today_bookings = []
        today_bookings_pagination = _empty_dashboard_bookings_page(DASHBOARD_BOOKINGS_PER_PAGE_DEFAULT)
        today_locations_count = 0

    shop_is_open = _shop_is_currently_open(shop)
    return render_template(
        "vendor/dashboard.html",
        products=products,
        pagination=pagination,
        shop=shop,
        shops=[shop],
        low_stock_threshold=low_stock_threshold,
        low_stock_products=low_stock_products,
        no_image_products=no_image_products,
        low_stock_total=low_stock_total,
        no_image_total=no_image_total,
        total_products=total_products,
        total_orders=total_orders,
        total_revenue=total_revenue,
        shop_is_open=shop_is_open,
        recent_orders=recent_orders,
        recent_orders_count=recent_orders_pagination["count"],
        recent_orders_pagination=recent_orders_pagination,
        recent_orders_window_hours=NEW_ORDERS_WINDOW_HOURS,
        today_prepare=today_prepare,
        today_prepare_pagination=today_prepare_pagination,
        today_bookings=today_bookings,
        today_bookings_pagination=today_bookings_pagination,
        today_locations_count=today_locations_count,
        today_prepare_count=today_prepare_pagination["count"],
        today_bookings_count=today_bookings_pagination["count"],
        allows_products=allows_products,
        allows_services=allows_services,
        allows_location=allows_location,
        allows_catalog=allows_catalog,
        show_stock_alerts=show_stock_alerts,
        catalog_title=type_flags["catalog_title"],
        catalog_placeholder=type_flags["catalog_placeholder"],
        catalog_create_label=type_flags["catalog_create_label"],
        catalog_empty_label=type_flags["catalog_empty_label"],
        product_catalog_block_reasons=_catalog_block_reasons,
        product_promos=product_promos,
        calculate_promo_price=calculate_promo_price,
        password_change_window_active=vendor_user.password_change_window_active(),
        password_change_allowed_until=vendor_user.password_change_allowed_until,
    )


@bp.route("/catalog")
@login_required
def catalog():
    if not hasattr(current_user, "role") or current_user.role != "vendor":
        flash("Accès réservé aux vendeurs.", "warning")
        return redirect(url_for("shop.home"))

    vendor_user = db.session.get(User, current_user.id) or current_user
    shop = resolve_vendor_shop(vendor_user)
    if not shop:
        return _redirect_vendor_shop_admin_only()

    type_flags = _vendor_type_flags(shop)
    allows_products = type_flags["allows_products"]
    allows_services = type_flags["allows_services"]
    allows_location = type_flags["allows_location"]
    allows_catalog = type_flags["allows_catalog"]

    if not allows_catalog:
        if allows_location:
            return redirect(url_for("rentals.owner_locations"))
        flash("Action non autorisée pour ce type de boutique.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    page = page_from_args(request.args)
    per_page = _normalize_positive_int(
        request.args.get("per_page", 24),
        default=24,
        minimum=12,
        maximum=100,
    )

    search_term = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "all").strip().lower()
    kind_filter = (request.args.get("kind") or "all").strip().lower()
    sort_filter = (request.args.get("sort") or "recent").strip().lower()
    stock_filter = (request.args.get("stock") or "all").strip().lower()
    category_id = _safe_int(request.args.get("category_id"))
    partial_only = _is_ajax_request() and request.headers.get("X-Catalog-Partial") == "1"
    search_term_query = search_term if len(search_term) >= 2 else ""

    base_query = Product.query.filter(Product.vendor_id == current_user.id)
    base_query = _scope_catalog_query(base_query, allows_products, allows_services)

    summary_query = base_query

    product_query = (
        base_query.options(selectinload(Product.category))
    )

    if search_term and not search_term_query:
        product_query = product_query.filter(False)
    elif search_term_query:
        like_term = f"%{search_term_query}%"
        product_query = product_query.filter(
            or_(
                Product.name.ilike(like_term),
                Product.description.ilike(like_term),
            )
        )

    if status_filter == "active":
        product_query = product_query.filter(Product.is_active.is_(True))
    elif status_filter == "inactive":
        product_query = product_query.filter(Product.is_active.is_(False))
    else:
        status_filter = "all"

    allowed_kind_values = {"all"}
    if allows_products:
        allowed_kind_values.add("physical")
    if allows_services:
        allowed_kind_values.add("service")
    if kind_filter not in allowed_kind_values:
        kind_filter = "all"
    if kind_filter == "physical":
        product_query = product_query.filter(Product.kind != "service")
    elif kind_filter == "service":
        product_query = product_query.filter(Product.kind == "service")

    if stock_filter == "out":
        product_query = product_query.filter(Product.kind != "service", Product.stock <= 0)
    elif stock_filter == "available":
        product_query = product_query.filter(
            or_(Product.kind == "service", Product.stock > 0)
        )
    elif stock_filter == "low":
        settings = PlatformSettings.get()
        try:
            low_stock_threshold = int(settings.low_stock_threshold or 5)
        except (TypeError, ValueError):
            low_stock_threshold = 5
        if low_stock_threshold < 0:
            low_stock_threshold = 0
        product_query = product_query.filter(
            Product.kind != "service",
            Product.stock > 0,
            Product.stock <= low_stock_threshold,
        )
    else:
        stock_filter = "all"

    category_options = []
    if not partial_only:
        category_options_query = (
            db.session.query(Category.id, Category.name, db.func.count(Product.id).label("count"))
            .join(Product, Product.category_id == Category.id)
            .filter(Product.vendor_id == current_user.id)
        )
        category_options_query = _scope_catalog_query(category_options_query, allows_products, allows_services)
        category_options = (
            category_options_query
            .group_by(Category.id, Category.name)
            .order_by(Category.name.asc())
            .all()
        )
    category_ids = {int(row.id) for row in category_options}
    if category_id and (partial_only or category_id in category_ids):
        product_query = product_query.filter(Product.category_id == category_id)
    else:
        category_id = None

    active_promo_end_at = (
        db.session.query(db.func.max(Promo.end_date))
        .filter(
            Promo.product_id == Product.id,
            Promo.end_date >= datetime.utcnow(),
            Promo.status == Promo.STATUS_APPROVED,
        )
        .correlate(Product)
        .scalar_subquery()
    )
    sort_map = {
        "recent": (Product.created_at.desc(), Product.id.desc()),
        "oldest": (Product.created_at.asc(), Product.id.asc()),
        "name": (Product.name.asc(), Product.id.desc()),
        "price_asc": (Product.price_cents_value.asc(), Product.id.desc()),
        "price_desc": (Product.price_cents_value.desc(), Product.id.desc()),
        "stock_desc": (Product.stock.desc(), Product.id.desc()),
        "stock_asc": (Product.stock.asc(), Product.id.desc()),
        "promo": (
            active_promo_end_at.isnot(None).desc(),
            active_promo_end_at.desc(),
            Product.created_at.desc(),
            Product.id.desc(),
        ),
    }
    if sort_filter not in sort_map:
        sort_filter = "recent"
    product_query = product_query.order_by(*sort_map[sort_filter])

    pagination = paginate_with_clamped_page(product_query, page=page, per_page=per_page, error_out=False)
    products = pagination.items
    product_promos = _product_promo_snapshot(products)

    settings = PlatformSettings.get()
    try:
        low_stock_threshold = int(settings.low_stock_threshold or 5)
    except (TypeError, ValueError):
        low_stock_threshold = 5
    if low_stock_threshold < 0:
        low_stock_threshold = 0

    total_products = active_products = inactive_products = service_total = physical_total = 0
    if not partial_only:
        total_products = int(summary_query.count())
        active_products = int(summary_query.filter(Product.is_active.is_(True)).count())
        inactive_products = max(0, total_products - active_products)
        service_total = int(summary_query.filter(Product.kind == "service").count()) if allows_services else 0
        physical_total = (
            int(summary_query.filter(Product.kind != "service").count())
            if allows_products else 0
        )

    pagination_args = request.args.to_dict(flat=True)
    pagination_args.pop("page", None)
    prev_page_url = url_for("vendor.catalog", page=pagination.prev_num, **pagination_args) if pagination.has_prev else None
    next_page_url = url_for("vendor.catalog", page=pagination.next_num, **pagination_args) if pagination.has_next else None

    context = dict(
        shop=shop,
        products=products,
        pagination=pagination,
        total_products=total_products,
        active_products=active_products,
        inactive_products=inactive_products,
        service_total=service_total,
        physical_total=physical_total,
        category_options=category_options,
        low_stock_threshold=low_stock_threshold,
        allows_products=allows_products,
        allows_services=allows_services,
        allows_location=allows_location,
        allows_catalog=allows_catalog,
        catalog_title="Catalogue",
        catalog_create_label=type_flags["catalog_create_label"],
        catalog_empty_label=type_flags["catalog_empty_label"],
        product_catalog_block_reasons=_catalog_block_reasons,
        product_promos=product_promos,
        calculate_promo_price=calculate_promo_price,
        search_term=search_term,
        selected_status=status_filter,
        selected_kind=kind_filter,
        selected_sort=sort_filter,
        selected_stock=stock_filter,
        selected_category_id=category_id,
        per_page=per_page,
        prev_page_url=prev_page_url,
        next_page_url=next_page_url,
    )
    if partial_only:
        return jsonify(
            success=True,
            html=render_template("vendor/partials/_catalog_results.html", **context),
            total=pagination.total,
            page=pagination.page,
            pages=pagination.pages,
        )

    return render_template(
        "vendor/catalog.html",
        **context,
    )


@bp.route("/dashboard/orders-live")
@login_required
def dashboard_orders_live():
    started_at = perf_counter()

    if not hasattr(current_user, "role") or current_user.role != "vendor":
        return jsonify({"success": False, "error": "forbidden"}), 403

    shop = resolve_vendor_shop(current_user)
    type_flags = _vendor_type_flags(shop)
    allows_products = bool(type_flags["allows_products"])
    allows_services = bool(type_flags["allows_services"])

    per_page = _normalize_positive_int(
        request.args.get("per_page", type=int),
        default=DASHBOARD_ORDERS_PER_PAGE_DEFAULT,
        minimum=4,
        maximum=DASHBOARD_ORDERS_PER_PAGE_MAX,
    )
    bookings_per_page = _normalize_positive_int(
        request.args.get("bookings_per_page", type=int),
        default=DASHBOARD_BOOKINGS_PER_PAGE_DEFAULT,
        minimum=4,
        maximum=DASHBOARD_BOOKINGS_PER_PAGE_MAX,
    )
    recent_page = _normalize_positive_int(
        request.args.get("recent_page", type=int),
        default=1,
        minimum=1,
    )
    prepare_page = _normalize_positive_int(
        request.args.get("prepare_page", type=int),
        default=1,
        minimum=1,
    )
    bookings_page = _normalize_positive_int(
        request.args.get("bookings_page", type=int),
        default=1,
        minimum=1,
    )

    empty_orders_page = _empty_dashboard_orders_page(per_page)
    empty_bookings_page = _empty_dashboard_bookings_page(bookings_per_page)

    if not allows_products and not allows_services and not type_flags["allows_location"]:
        payload = dict(
            success=True,
            window_hours=NEW_ORDERS_WINDOW_HOURS,
            server_time=datetime.utcnow().isoformat(),
            recent=empty_orders_page,
            today_prepare=empty_orders_page,
            today_bookings=empty_bookings_page,
            today_locations_count=0,
        )
        response = jsonify(payload)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        _log_perf(
            "vendor.dashboard_orders_live",
            started_at,
            vendor_id=getattr(current_user, "id", None),
            cache="none",
            allows_products=False,
            allows_services=False,
        )
        return response

    cache_key = (
        int(getattr(current_user, "id", 0) or 0),
        int(per_page),
        int(bookings_per_page),
        int(recent_page),
        int(prepare_page),
        int(bookings_page),
        bool(allows_products),
        bool(allows_services),
        bool(type_flags["allows_location"]),
    )

    try:
        cached_payload = _orders_live_cache_get(cache_key)
    except Exception:
        current_app.logger.exception(
            "vendor.dashboard_orders_live.cache_read_error",
            extra={"vendor_id": getattr(current_user, "id", None)},
        )
        cached_payload = None

    if cached_payload is not None:
        response = jsonify(
            success=True,
            window_hours=NEW_ORDERS_WINDOW_HOURS,
            server_time=cached_payload.get("server_time"),
            recent=cached_payload.get("recent", empty_orders_page),
            today_prepare=cached_payload.get("today_prepare", empty_orders_page),
            today_bookings=cached_payload.get("today_bookings", empty_bookings_page),
            today_locations_count=int(cached_payload.get("today_locations_count", 0) or 0),
        )
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["X-Live-Cache"] = "HIT"
        _log_perf(
            "vendor.dashboard_orders_live",
            started_at,
            vendor_id=getattr(current_user, "id", None),
            cache="hit",
        )
        return response

    try:
        cards_payload = _build_dashboard_live_cards_payload(
            current_user.id,
            allows_products=bool(allows_products),
            allows_services=bool(allows_services),
            allows_location=bool(type_flags["allows_location"]),
            recent_page=recent_page,
            prepare_page=prepare_page,
            bookings_page=bookings_page,
            per_page=per_page,
            bookings_per_page=bookings_per_page,
        )
    except SQLAlchemyError:
        safe_session_rollback(remove=True)
        current_app.logger.exception(
            "vendor.dashboard_orders_live.db_error",
            extra={"vendor_id": getattr(current_user, "id", None)},
        )
        _log_perf(
            "vendor.dashboard_orders_live",
            started_at,
            vendor_id=getattr(current_user, "id", None),
            error="database_error",
        )
        return jsonify({"success": False, "error": "database_error"}), 500
    except Exception:
        current_app.logger.exception(
            "vendor.dashboard_orders_live.unexpected_error",
            extra={"vendor_id": getattr(current_user, "id", None)},
        )
        _log_perf(
            "vendor.dashboard_orders_live",
            started_at,
            vendor_id=getattr(current_user, "id", None),
            error="unexpected_error",
        )
        return jsonify({"success": False, "error": "unexpected_error"}), 500

    try:
        _orders_live_cache_set(cache_key, cards_payload)
    except Exception:
        current_app.logger.exception(
            "vendor.dashboard_orders_live.cache_write_error",
            extra={"vendor_id": getattr(current_user, "id", None)},
        )

    payload = dict(
        success=True,
        window_hours=NEW_ORDERS_WINDOW_HOURS,
        server_time=cards_payload.get("server_time"),
        recent=cards_payload.get("recent", empty_orders_page),
        today_prepare=cards_payload.get("today_prepare", empty_orders_page),
        today_bookings=cards_payload.get("today_bookings", empty_bookings_page),
        today_locations_count=int(cards_payload.get("today_locations_count", 0) or 0),
    )
    response = jsonify(payload)
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Live-Cache"] = "MISS"
    _log_perf(
        "vendor.dashboard_orders_live",
        started_at,
        vendor_id=getattr(current_user, "id", None),
        cache="miss",
        recent_count=payload["recent"].get("count", 0),
        prepare_count=payload["today_prepare"].get("count", 0),
        bookings_count=payload["today_bookings"].get("count", 0),
    )
    return response

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
        flash("Demandez à l’admin d’ouvrir la fenêtre de changement.", "warning")
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
        flash("Nouveau mot de passe trop court. Minimum : 8 caractères.", "warning")
        return redirect(url_for("vendor.dashboard"))
    if new_password != confirm_password:
        flash("La confirmation du mot de passe ne correspond pas.", "warning")
        return redirect(url_for("vendor.dashboard"))

    vendor_user.set_password(new_password)
    vendor_user.password_change_allowed_until = None
    db.session.commit()
    log_access("vendor_change_password", "user", vendor_user.id, success=True)
    flash("Mot de passe mis à jour.", "success")
    return redirect(url_for("vendor.dashboard"))


@bp.route("/product/new", methods=["GET", "POST"])
@login_required
def product_new():
    if current_user.role != "vendor":
        flash("Accès réservé aux vendeurs.", "warning")
        return redirect(url_for("shop.home"))

    # Vrifier que le vendeur a une boutique
    shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    if not shop:
        return _redirect_vendor_shop_admin_only()

    if not shop_allows_any(shop, "products", "services"):
        flash("Cette boutique ne permet pas d’ajouter des produits ou services.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    contact_guard = _require_shop_contact_details(shop)
    if contact_guard:
        return contact_guard

    categories_by_kind = _load_categories_by_kind()
    type_flags = _vendor_type_flags(shop)
    allows_products = type_flags["allows_products"]
    allows_services = type_flags["allows_services"]

    if request.method == "POST":
        current_app.logger.info(
            "[vendor] create_product.start vendor_id=%s",
            current_user.id,
        )
        try:
            name = request.form["name"].strip()
            description = request.form.get("description", "").strip()
            kind = (request.form.get("kind") or "physical").strip().lower()
            current_app.logger.info(
                "[vendor] create_product.payload vendor_id=%s name=%s shop_id=%s category_id=%s kind=%s",
                current_user.id,
                request.form.get("name"),
                request.form.get("shop_id"),
                request.form.get("category_id"),
                request.form.get("kind"),
            )
            if not name:
                current_app.logger.warning(
                    "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                    current_user.id,
                    "name_empty",
                )
                flash("Offre non créée : le nom est obligatoire.", "warning")
                return redirect(url_for("vendor.product_new"))
            if kind not in ("physical", "service"):
                current_app.logger.warning(
                    "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                    current_user.id,
                    "kind_invalid",
                )
                kind = "physical"
            access_guard = ensure_shop_allows(
                shop,
                shop_type_from_product_kind(kind),
                fallback_endpoint="vendor.manage_shop",
            )
            if access_guard:
                current_app.logger.warning(
                    "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                    current_user.id,
                    "shop_invalid",
                )
                return access_guard
            price = request.form["price"]
            if kind == "service":
                stock = 0
            else:
                stock = int(request.form.get("stock", 0))

            try:
                category_id = int(request.form["category_id"])
            except (TypeError, ValueError):
                current_app.logger.warning(
                    "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                    current_user.id,
                    "category_missing",
                )
                flash("Offre non créée : catégorie invalide.", "danger")
                return redirect(url_for("vendor.product_new"))

            category = _validate_category_for_kind(category_id, kind)
            if not category:
                current_app.logger.warning(
                    "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                    current_user.id,
                    "category_invalid",
                )
                expected_label = "Services" if kind == "service" else "Produits"
                flash(f"Offre non créée : choisissez une catégorie valide ({expected_label}).", "warning")
                return redirect(url_for("vendor.product_new"))

            files = [f for f in request.files.getlist("images") if f and (f.filename or "").strip()]

            uploaded_total_bytes = _uploaded_files_total_bytes(files)
            if uploaded_total_bytes > MAX_PRODUCT_IMAGES_TOTAL_BYTES:
                current_app.logger.warning(
                    "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                    current_user.id,
                    "image_total_bytes_exceeded",
                )
                flash("Offre non créée : la taille totale des photos dépasse 15 MB.", "warning")
                return redirect(url_for("vendor.product_new"))

            filenames, skipped_invalid_images, skipped_overflow_images = _save_uploaded_product_images(
                files,
                vendor_id=current_user.id,
                remaining_slots=MAX_PRODUCT_IMAGES,
            )
            image_file = "|".join(filenames) if filenames else None
            if not image_file:
                current_app.logger.warning(
                    "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                    current_user.id,
                    "image_missing",
                )
            video_files = [f for f in request.files.getlist("video") if f and (f.filename or "").strip()]
            if len(video_files) > MAX_PRODUCT_VIDEOS:
                current_app.logger.warning(
                    "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                    current_user.id,
                    "video_limit_exceeded",
                )
                flash("Offre non créée : une seule vidéo est autorisée.", "warning")
                return redirect(url_for("vendor.product_new"))

            video_file = None
            if video_files:
                try:
                    video_file = save_product_video(video_files[0])
                except ValueError as exc:
                    current_app.logger.warning(
                        "[vendor] create_product.validation_failed vendor_id=%s reason=%s",
                        current_user.id,
                        "video_invalid",
                    )
                    flash(f"Offre non créée : {exc}", "warning")
                    return redirect(url_for("vendor.product_new"))

            product = Product(
                kind=kind,
                name=name,
                description=description,
                price=0,
                stock=stock,
                category_id=category.id,
                image_file=image_file,
                video_file=video_file,
                vendor_id=current_user.id,
                shop_id=shop.id
            )
            try:
                set_product_price(product, price)
            except ValueError:
                flash("Offre non créée : prix invalide.", "warning")
                return redirect(url_for("vendor.product_new"))
            db.session.add(product)
            current_app.logger.info(
                "[vendor] create_product.before_commit vendor_id=%s product_name=%s",
                current_user.id,
                product.name,
            )
            db.session.commit()
            current_app.logger.info(
                "[vendor] create_product.success vendor_id=%s product_id=%s",
                current_user.id,
                product.id,
            )
            bump_catalog_version()

            log_access(
                "create_product",
                "product",
                product.id,
                success=True,
                changes={"price": product.price, "stock": product.stock, "shop_id": product.shop_id}
            )

            flash("Offre créée avec succès.", "success")
            _flash_product_image_notice(
                mode="create",
                skipped_invalid=skipped_invalid_images,
                skipped_overflow=skipped_overflow_images,
            )
            return redirect(url_for("vendor.dashboard"))
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "[vendor] create_product.failed vendor_id=%s",
                current_user.id,
            )
            raise

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
        max_video_mb=int(MAX_PRODUCT_VIDEO_BYTES / 1024 / 1024),
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
        "video_file": getattr(product, "video_file", None),
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
        contact_guard = _require_shop_contact_details(shop)
        if contact_guard:
            return contact_guard

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
        try:
            set_product_price(product, request.form["price"])
        except ValueError:
            flash("Mise à jour échouée : prix invalide.", "warning")
            return redirect(url_for("vendor.product_edit", pid=product.id))

        try:
            category_id = int(request.form["category_id"])
        except (TypeError, ValueError):
            flash("Mise à jour échouée : catégorie invalide.", "danger")
            return redirect(url_for("vendor.product_edit", pid=product.id))

        category = _validate_category_for_kind(category_id, kind)
        if not category:
            expected_label = "Services" if kind == "service" else "Produits"
            flash(f"Mise à jour échouée : choisissez une catégorie valide ({expected_label}).", "warning")
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

        uploaded_total_bytes = _uploaded_files_total_bytes(files)
        if uploaded_total_bytes > MAX_PRODUCT_IMAGES_TOTAL_BYTES:
            flash("Mise à jour échouée : la taille totale des nouvelles photos dépasse 15 MB.", "warning")
            return redirect(url_for("vendor.product_edit", pid=product.id))

        remaining_slots = max(0, MAX_PRODUCT_IMAGES - len(kept_existing_images))
        new_filenames, skipped_invalid_images, skipped_overflow_images = _save_uploaded_product_images(
            files,
            vendor_id=current_user.id,
            remaining_slots=remaining_slots,
        )
        all_images = (kept_existing_images + new_filenames)[:MAX_PRODUCT_IMAGES]
        product.image_file = "|".join(all_images) if all_images else None

        remove_video = (request.form.get("remove_video") or "").strip() == "1"
        existing_video = (getattr(product, "video_file", None) or "").strip() or None
        video_files = [f for f in request.files.getlist("video") if f and (f.filename or "").strip()]
        if len(video_files) > MAX_PRODUCT_VIDEOS:
            flash("Mise à jour échouée : une seule vidéo est autorisée.", "warning")
            return redirect(url_for("vendor.product_edit", pid=product.id))

        replacement_video = existing_video
        if remove_video:
            replacement_video = None
        if video_files:
            try:
                replacement_video = save_product_video(video_files[0])
            except ValueError as exc:
                flash(f"Mise à jour échouée : {exc}", "warning")
                return redirect(url_for("vendor.product_edit", pid=product.id))

        old_video_file = existing_video
        product.video_file = replacement_video

        auto_reactivated = False
        catalog_block_reasons = _catalog_block_reasons(product)
        if (
            current_user.role == "vendor"
            and not bool(product.is_active)
            and not catalog_block_reasons
            and shop
            and bool(getattr(shop, "is_active", True))
        ):
            product.is_active = True
            auto_reactivated = True

        db.session.commit()
        video_cleanup_failed = False
        if old_video_file and old_video_file != product.video_file and (remove_video or video_files):
            try:
                delete_product_video(old_video_file)
            except Exception:
                video_cleanup_failed = True
                current_app.logger.exception(
                    "[vendor] product_edit.video_cleanup_failed vendor_id=%s product_id=%s old_video_file=%s",
                    current_user.id,
                    product.id,
                    old_video_file,
                )
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
                    "has_video": bool(product.video_file),
                },
            )
        if auto_reactivated:
            flash("Offre mise à jour avec succès et réactivée automatiquement.", "success")
        else:
            flash("Offre mise à jour avec succès.", "success")
        if video_cleanup_failed:
            flash("L'offre a bien ete mise a jour, mais l'ancienne video n'a pas pu etre nettoyee tout de suite.", "warning")
        _flash_product_image_notice(
            mode="edit",
            skipped_invalid=skipped_invalid_images,
            skipped_overflow=skipped_overflow_images,
        )
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
        catalog_block_reasons=_catalog_block_reasons(product),
        max_video_mb=int(MAX_PRODUCT_VIDEO_BYTES / 1024 / 1024),
    )


@bp.route("/product/<int:pid>/promotion", methods=["GET", "POST"])
@login_required
def product_promotion(pid):
    product = Product.query.get_or_404(pid)
    if current_user.role != "vendor" or product.vendor_id != current_user.id:
        flash("Interdit", "danger")
        return redirect(url_for("vendor.dashboard"))

    shop = product.shop or Shop.query.filter_by(vendor_id=product.vendor_id).first()
    listing_guard = ensure_shop_allows(
        shop,
        shop_type_from_product_kind(getattr(product, "kind", "physical")),
        fallback_endpoint="vendor.manage_shop",
    )
    if listing_guard:
        return listing_guard

    now = datetime.utcnow()
    latest_promo = (
        Promo.query
        .filter(Promo.product_id == product.id)
        .order_by(Promo.end_date.desc(), Promo.id.desc())
        .first()
    )
    active_promo = (
        Promo.query
        .filter(
            Promo.product_id == product.id,
            Promo.end_date >= now,
            Promo.status == Promo.STATUS_APPROVED,
        )
        .order_by(Promo.end_date.asc(), Promo.id.asc())
        .first()
    )
    promo = active_promo or latest_promo

    def _format_promo_value(value) -> str:
        if value in (None, ""):
            return ""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.2f}".rstrip("0").rstrip(".")

    suggested_end_date = (
        active_promo.end_date
        if active_promo and active_promo.end_date and active_promo.end_date >= now
        else now + timedelta(days=7)
    )
    form_state = {
        "promo_type": getattr(promo, "type", "percentage") or "percentage",
        "promo_value": _format_promo_value(getattr(promo, "value", "")),
        "end_date": suggested_end_date.strftime("%Y-%m-%dT%H:%M") if suggested_end_date else "",
    }
    form_error = None
    item_label = "service" if getattr(product, "kind", "physical") == "service" else "produit"

    if request.method == "POST":
        form_state = {
            "promo_type": (request.form.get("promo_type") or "").strip().lower() or "percentage",
            "promo_value": (request.form.get("promo_value") or "").strip(),
            "end_date": (request.form.get("end_date") or "").strip(),
        }
        promo_type = form_state["promo_type"]
        if promo_type not in ("percentage", "fixed"):
            form_error = "Choisissez un type de remise valide."
            flash(form_error, "warning")
        else:
            try:
                promo_value = float((form_state["promo_value"] or "0").replace(",", "."))
            except (TypeError, ValueError):
                promo_value = 0.0
            if promo_value <= 0:
                form_error = "Entrez une valeur de remise supérieure à 0."
                flash(form_error, "warning")
            elif promo_type == "percentage" and promo_value >= 100:
                form_error = "Le pourcentage doit rester en dessous de 100%."
                flash(form_error, "warning")

        end_date = None
        if not form_error:
            if form_state["end_date"]:
                try:
                    end_date = datetime.fromisoformat(form_state["end_date"])
                except ValueError:
                    form_error = "La date de fin n'est pas valide."
                    flash(form_error, "warning")
            else:
                end_date = now + timedelta(days=7)

        if not form_error and end_date <= now:
            form_error = "Choisissez une date de fin dans le futur."
            flash(form_error, "warning")

        if not form_error and end_date > now + timedelta(days=PROMO_MAX_DURATION_DAYS):
            end_date = now + timedelta(days=PROMO_MAX_DURATION_DAYS)

        if not form_error:
            current_price_for_validation = cents_to_money(
                getattr(product, "price_cents", None)
                if getattr(product, "price_cents", None) is not None
                else getattr(product, "price_cents_value", 0)
            )
            min_discount = current_price_for_validation * (PROMO_MIN_PERCENT / 100)
            if promo_type == "percentage" and promo_value < PROMO_MIN_PERCENT:
                form_error = f"La remise minimale est de {PROMO_MIN_PERCENT}%."
                flash(form_error, "warning")
            elif promo_type == "fixed" and promo_value < min_discount:
                form_error = f"La remise fixe doit valoir au moins {PROMO_MIN_PERCENT}% du prix."
                flash(form_error, "warning")

        if not form_error:
            active_shop_promo_count = (
                Promo.query
                .join(Product, Product.id == Promo.product_id)
                .filter(
                    Product.shop_id == shop.id,
                    Promo.end_date >= now,
                    Promo.status.in_((Promo.STATUS_PENDING, Promo.STATUS_APPROVED)),
                    Promo.product_id != product.id,
                )
                .count()
            )
            if active_shop_promo_count >= PROMO_MAX_ACTIVE_PER_SHOP:
                form_error = f"Limite atteinte: {PROMO_MAX_ACTIVE_PER_SHOP} promotions actives ou en validation par boutique."
                flash(form_error, "warning")

        if not form_error:
            promo_record = active_promo or latest_promo
            next_status = Promo.STATUS_APPROVED if shop.promo_trusted else Promo.STATUS_PENDING
            success_message = (
                "Promotion activée automatiquement. Le nouveau prix est visible côté client."
                if next_status == Promo.STATUS_APPROVED
                else "Promotion envoyée à l'admin pour validation."
            )
            if promo_record is None:
                promo_record = Promo(
                    product_id=product.id,
                    type=promo_type,
                    value=promo_value,
                    end_date=end_date,
                    status=next_status,
                )
                db.session.add(promo_record)
                # Ensure the new promo gets an id before older promos are disabled.
                db.session.flush()
                action_name = "create_product_promo"
            else:
                promo_record.type = promo_type
                promo_record.value = promo_value
                promo_record.end_date = end_date
                promo_record.status = next_status
                promo_record.review_note = None
                promo_record.reviewed_by_id = None
                promo_record.reviewed_at = None
                action_name = "update_product_promo"
            (
                Promo.query
                .filter(Promo.product_id == product.id, Promo.id != promo_record.id, Promo.end_date >= now)
                .update({"end_date": now - timedelta(seconds=1)}, synchronize_session=False)
            )

            db.session.commit()
            bump_catalog_version()
            log_access(
                action_name,
                "promo",
                promo_record.id,
                success=True,
                changes={
                    "product_id": product.id,
                    "type": promo_record.type,
                    "value": promo_record.value,
                    "end_date": promo_record.end_date.isoformat(),
                    "status": promo_record.status,
                },
            )
            flash(success_message, "success")
            return redirect(url_for("vendor.product_promotion", pid=product.id))

    current_price = cents_to_money(
        getattr(product, "price_cents", None)
        if getattr(product, "price_cents", None) is not None
        else getattr(product, "price_cents_value", 0)
    )
    final_price = calculate_promo_price(product, active_promo) if active_promo else current_price
    return render_template(
        "vendor/product_promotion_form.html",
        product=product,
        promo=promo,
        active_promo=active_promo,
        final_price=final_price,
        current_price=current_price,
        form_state=form_state,
        form_error=form_error,
        item_label=item_label,
    )


@bp.route("/product/<int:pid>/promotion/disable", methods=["POST"])
@login_required
def product_promotion_disable(pid):
    product = Product.query.get_or_404(pid)
    if current_user.role != "vendor" or product.vendor_id != current_user.id:
        flash("Interdit", "danger")
        return redirect(url_for("vendor.dashboard"))

    promo = (
        Promo.query
        .filter(
            Promo.product_id == product.id,
            Promo.end_date >= datetime.utcnow(),
            Promo.status.in_((Promo.STATUS_PENDING, Promo.STATUS_APPROVED)),
        )
        .order_by(Promo.end_date.asc(), Promo.id.asc())
        .first()
    )
    if not promo:
        flash("Aucune promotion active à désactiver.", "info")
        return redirect(url_for("vendor.product_promotion", pid=product.id))

    promo.end_date = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    bump_catalog_version()
    log_access(
        "disable_product_promo",
        "promo",
        promo.id,
        success=True,
        changes={"product_id": product.id},
    )
    flash("Promotion désactivée.", "success")
    return redirect(url_for("vendor.product_promotion", pid=product.id))

@bp.route("/product/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    product = Product.query.get_or_404(pid)

    # Vérifier les permissions
    if current_user.role != "admin" and product.vendor_id != current_user.id:
        if _is_ajax_request():
            return jsonify(success=False, message="Interdit"), 403
        flash("Interdit", "danger")
        return redirect(url_for("vendor.dashboard"))

    # Vérifier si le produit a déjà été commandé (peu importe le statut)
    a_deja_ete_vendu = db.session.query(OrderItem.id).filter(
        OrderItem.product_id == product.id
    ).first() is not None

    if a_deja_ete_vendu:
        # Cas 1 : Le produit a déjà été vendu → on désactive seulement
        ancien_etat = product.is_active
        product.is_active = False
        db.session.commit()
        bump_catalog_version()
        
        # Log de l'action
        try:
            log_access(
                "disable_product",
                "product",
                product.id,
                success=True,
                changes={"name": product.name, "was_active": ancien_etat, "now_active": False}
            )
        except (SQLAlchemyError, ValueError):
            current_app.logger.exception(
                "vendor.product_disable.audit_log_failed",
                extra={"product_id": product.id, "vendor_id": product.vendor_id},
            )
        
        if _is_ajax_request():
            return jsonify(success=True, product_id=product.id, disabled=True, message="Produit désactivé (historique conservé)")
        
        flash("Produit désactivé (historique des commandes conservé)", "success")
        return redirect(url_for("vendor.dashboard"))
    
    # Cas 2 : Le produit n'a JAMAIS été commandé → on peut supprimer
    # Note : pas besoin de supprimer les order_item car ils n'existent pas
    
    # Sauvegarde des infos pour le log avant suppression
    product_name = product.name
    product_price = product.price
    
    db.session.delete(product)
    db.session.commit()
    bump_catalog_version()

    try:
        log_access(
            "delete_product",
            "product",
            pid,  # Note: on utilise pid car product.id n'est plus disponible après commit
            success=True,
            changes={"name": product_name, "price": product_price}
        )
    except (SQLAlchemyError, ValueError):
        current_app.logger.exception(
            "vendor.product_delete.audit_log_failed",
            extra={"product_id": pid, "vendor_id": product.vendor_id if product else None},
        )

    if _is_ajax_request():
        return jsonify(success=True, product_id=pid, message="Produit supprimé définitivement")

    flash("Produit supprimé définitivement (aucune commande associée).", "success")
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
    if shop:
        type_flags = _vendor_type_flags(shop)
        shop_public_url = _public_shop_url(shop.slug)
    else:
        shop_public_url = ""
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
        shop_public_url=shop_public_url,
        shop_type_labels=SHOP_TYPE_LABELS,
        allows_products=type_flags["allows_products"],
        allows_services=type_flags["allows_services"],
        allows_location=type_flags["allows_location"],
        allows_catalog=type_flags["allows_catalog"],
        catalog_title=type_flags["catalog_title"],
        catalog_create_label=type_flags["catalog_create_label"],
        product_catalog_block_reasons=_catalog_block_reasons,
    )

@bp.route("/shop/create", methods=["GET", "POST"])
@login_required
def create_shop():
    """Ancienne route de creation vendeur : desactivee."""
    if current_user.role != "vendor":
        flash("Accs rserv aux vendeurs", "warning")
        return redirect(url_for("shop.home"))
    return _redirect_vendor_shop_admin_only()

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
        return _redirect_vendor_shop_admin_only()

    recent_change_requests = (
        VendorChangeRequest.query
        .filter_by(vendor_id=current_user.id, shop_id=shop.id)
        .order_by(VendorChangeRequest.created_at.desc())
        .limit(8)
        .all()
    )
    locked_contact_email = (shop.contact_email or current_user.email or "").strip()

    if request.method == "POST":
        before = {
            "description": shop.description,
            "contact_phone": shop.contact_phone,
            "address": shop.address,
            "logo": shop.logo,
        }
        try:
            shop.description = request.form.get("description", "").strip()
            shop.contact_phone = request.form.get("contact_phone", "").strip()
            shop.address = request.form.get("address", "").strip()
            if _shop_requires_contact_details(shop) and not _shop_has_required_contact_details(shop):
                flash("Pour vendre des produits ou services, telephone et adresse sont obligatoires.", "warning")
                return redirect(url_for("vendor.edit_shop"))

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

        except (SQLAlchemyError, ValueError, TypeError, OSError):
            db.session.rollback()
            current_app.logger.exception(
                "vendor.edit_shop.failed",
                extra={"vendor_id": getattr(current_user, "id", None), "shop_id": getattr(shop, "id", None)},
            )
            flash("Erreur lors de la mise  jour", "danger")

    return render_template(
        "vendor/edit_shop.html",
        shop=shop,
        shop_public_url=_public_shop_url(shop.slug),
        locked_contact_email=locked_contact_email,
        recent_change_requests=recent_change_requests,
        change_request_type_labels=VENDOR_CHANGE_TYPE_LABELS,
        allowed_change_types=VendorChangeRequest.allowed_types(),
    )


@bp.route("/shop/change-request", methods=["POST"])
@login_required
def request_locked_shop_change():
    if current_user.role != "vendor":
        flash("Acces reserve aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    if not shop:
        return _redirect_vendor_shop_admin_only()

    request_type = VendorChangeRequest.normalize_type(request.form.get("request_type"))
    if not request_type:
        flash("Type de demande invalide.", "warning")
        return redirect(url_for("vendor.edit_shop"))

    requested_value_raw = (request.form.get("requested_value") or "").strip()
    reason = (request.form.get("reason") or "").strip()[:1000]
    if len(reason) < 8:
        flash("Merci d'ajouter un motif plus detaille (au moins 8 caracteres).", "warning")
        return redirect(url_for("vendor.edit_shop"))

    pending_request = (
        VendorChangeRequest.query
        .filter_by(
            vendor_id=current_user.id,
            shop_id=shop.id,
            request_type=request_type,
            status=VendorChangeRequest.STATUS_PENDING,
        )
        .first()
    )
    if pending_request:
        flash("Une demande du meme type est deja en attente.", "warning")
        return redirect(url_for("vendor.edit_shop"))

    current_value = ""
    requested_value = ""

    if request_type == VendorChangeRequest.TYPE_ACCOUNT_EMAIL:
        requested_email = _normalize_optional_email(requested_value_raw)
        if not requested_email:
            flash("Email invalide.", "warning")
            return redirect(url_for("vendor.edit_shop"))
        if requested_email == (current_user.email or "").strip().lower():
            flash("Le nouvel email est identique a l'email actuel.", "warning")
            return redirect(url_for("vendor.edit_shop"))
        existing = User.query.filter(User.email == requested_email, User.id != current_user.id).first()
        if existing:
            flash("Cet email est deja utilise.", "danger")
            return redirect(url_for("vendor.edit_shop"))

        current_value = (current_user.email or "").strip()
        requested_value = requested_email

    elif request_type == VendorChangeRequest.TYPE_SHOP_NAME:
        requested_name = requested_value_raw
        if len(requested_name) < 3 or len(requested_name) > 100:
            flash("Le nom de boutique doit contenir entre 3 et 100 caracteres.", "warning")
            return redirect(url_for("vendor.edit_shop"))
        if requested_name.casefold() == (shop.name or "").strip().casefold():
            flash("Le nouveau nom est identique au nom actuel.", "warning")
            return redirect(url_for("vendor.edit_shop"))

        current_value = (shop.name or "").strip()
        requested_value = requested_name

    else:
        flash("Type de demande non pris en charge.", "warning")
        return redirect(url_for("vendor.edit_shop"))

    try:
        change_request = VendorChangeRequest(
            vendor_id=current_user.id,
            shop_id=shop.id,
            request_type=request_type,
            current_value=current_value[:255],
            requested_value=requested_value[:255],
            reason=reason,
            status=VendorChangeRequest.STATUS_PENDING,
        )
        db.session.add(change_request)
        db.session.commit()
        try:
            notify_admin_vendor_change_request(change_request)
        except Exception:
            current_app.logger.exception(
                "vendor_push.change_request_notify_failed",
                extra={"change_request_id": getattr(change_request, "id", None)},
            )
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "vendor.request_locked_shop_change.failed",
            extra={"vendor_id": current_user.id, "shop_id": shop.id, "request_type": request_type},
        )
        flash("Impossible d'envoyer la demande pour le moment.", "danger")
        return redirect(url_for("vendor.edit_shop"))

    log_access(
        "vendor_change_request_create",
        "vendor_change_request",
        change_request.id,
        success=True,
        changes={"request_type": request_type},
    )
    flash("Demande envoyee a l'administration.", "success")
    return redirect(url_for("vendor.edit_shop"))


@bp.route("/shop/service-location", methods=["POST"])
@login_required
def update_service_location():
    if current_user.role != "vendor":
        if _is_ajax_request():
            return jsonify(success=False, message="Acces reserve aux vendeurs"), 403
        flash("Acces reserve aux vendeurs", "warning")
        return redirect(url_for("shop.home"))

    shop = Shop.query.filter_by(vendor_id=current_user.id).first()
    if not shop:
        if _is_ajax_request():
            return jsonify(success=False, message="Boutique non trouvee"), 404
        return _redirect_vendor_shop_admin_only()

    if not shop_allows_any(shop, "services", "products"):
        if _is_ajax_request():
            return jsonify(
                success=False,
                message="Point de retrait disponible uniquement pour les boutiques produits/services.",
            ), 400
        flash("Point de retrait disponible uniquement pour les boutiques produits/services.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    shop.address = (request.form.get("service_address") or "").strip()
    shop.service_location_note = (request.form.get("service_location_note") or "").strip()[:255]
    if _shop_requires_contact_details(shop) and not (shop.address or "").strip():
        if _is_ajax_request():
            return jsonify(success=False, message="Adresse obligatoire pour les boutiques produits/services."), 400
        flash("Adresse obligatoire pour les boutiques produits/services.", "warning")
        return redirect(url_for("vendor.manage_shop"))

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

    if _is_ajax_request():
        return jsonify(
            success=True,
            message="Point de retrait mis a jour.",
            service_latitude=shop.service_latitude,
            service_longitude=shop.service_longitude,
            service_address=shop.address,
            service_location_note=shop.service_location_note,
        )

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

    # Vérifie que la commande contient bien au moins un produit physique
    # appartenant à ce vendeur.
    physical_order_line = (
        db.session.query(OrderItem.id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(OrderItem.order_id == oid)
        .filter(Product.vendor_id == vendor_id)
        .filter(Product.kind != "service")
        .first()
    )
    if not physical_order_line:
        flash(
            "Cette commande ne contient aucun produit physique pouvant être confirmé pour votre boutique.",
            "warning",
        )
        return redirect(request.referrer or url_for("vendor.earnings"))

    # Empêche un double encaissement sur la même commande pour ce vendeur
    existing = VendorReceipt.query.filter_by(vendor_id=vendor_id, order_id=oid).first()
    if existing:
        flash(
            "Cet encaissement a déjà été confirmé pour cette commande.",
            "info",
        )
        return redirect(request.referrer or url_for("vendor.earnings"))

    note = (request.form.get("note") or "").strip()[:255] or None

    try:
        receipt = VendorReceipt(
            vendor_id=vendor_id,
            order_id=oid,
            received_at=datetime.utcnow(),
            note=note,
            created_at=datetime.utcnow(),
        )
        db.session.add(receipt)
        db.session.commit()

    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "vendor.confirm_receipt.failed",
            extra={"vendor_id": vendor_id, "order_id": oid},
        )
        flash(
            "Une erreur est survenue pendant la confirmation de l'encaissement. "
            "Veuillez réessayer.",
            "danger",
        )
        return redirect(request.referrer or url_for("vendor.earnings"))

    flash(
        "Encaissement confirme.",
        "success",
    )
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


@bp.route("/notifications/push/config")
@login_required
def vendor_push_config():
    if not _current_user_can_use_push():
        return jsonify({"enabled": False, "publicKey": ""}), 403
    public_key = vendor_push_public_key()
    config_status = vendor_push_configuration_status()
    return jsonify(
        {
            "enabled": bool(public_key),
            **config_status,
            "validPublicKey": vendor_push_public_key_is_valid(public_key),
            "publicKey": public_key,
        }
    )


@bp.route("/notifications/push/status")
@login_required
def vendor_push_status():
    if not _current_user_can_use_push():
        return jsonify({"success": False, "message": "forbidden"}), 403
    active_count = (
        VendorPushSubscription.query
        .filter_by(vendor_id=current_user.id, is_active=True)
        .count()
    )
    return jsonify(
        {
            "success": True,
            **vendor_push_configuration_status(),
            "activeSubscriptions": int(active_count or 0),
        }
    )


@bp.route("/notifications/push/subscribe", methods=["POST"])
@login_required
def vendor_push_subscribe():
    if not _current_user_can_use_push():
        return jsonify({"success": False, "message": "forbidden"}), 403
    payload = request.get_json(silent=True) or {}
    subscription_payload = payload.get("subscription") if isinstance(payload, dict) else None
    try:
        subscription = upsert_vendor_push_subscription(
            current_user.id,
            subscription_payload or payload,
            request.headers.get("User-Agent", ""),
        )
    except ValueError:
        return jsonify({"success": False, "message": "invalid_subscription"}), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "vendor_push.subscribe_failed",
            extra={"vendor_id": getattr(current_user, "id", None)},
        )
        return jsonify({"success": False, "message": "subscribe_failed"}), 500
    test_sent = 0
    if payload.get("send_test"):
        try:
            test_sent = send_vendor_push_notification(
                current_user.id,
                {
                    "type": "vendor_push_test",
                    "title": "Alertes Baba Market activees",
                    "body": "Votre telephone est pret a recevoir les nouvelles demandes.",
                    "url": url_for("vendor.dashboard", _external=False),
                    "tag": "vendor-push-test",
                },
            )
        except Exception:
            current_app.logger.exception(
                "vendor_push.subscribe_test_failed",
                extra={"vendor_id": getattr(current_user, "id", None)},
            )
    return jsonify(
        {
            "success": True,
            "subscription_id": subscription.id,
            "configured": vendor_push_is_configured(),
            "test_sent": test_sent,
        }
    )


@bp.route("/notifications/push/unsubscribe", methods=["POST"])
@login_required
def vendor_push_unsubscribe():
    if not _current_user_can_use_push():
        return jsonify({"success": False, "message": "forbidden"}), 403
    payload = request.get_json(silent=True) or {}
    endpoint = str(payload.get("endpoint") or "").strip()
    removed = deactivate_vendor_push_subscription(endpoint, vendor_id=current_user.id)
    return jsonify({"success": True, "removed": removed})


@bp.route("/notifications/push/test", methods=["POST"])
@login_required
def vendor_push_test():
    if not _current_user_can_use_push():
        return jsonify({"success": False, "message": "forbidden"}), 403
    sent = send_vendor_push_notification(
        current_user.id,
        {
            "type": "vendor_push_test",
            "title": "Test notification Baba Market",
            "body": "Si vous voyez ceci, les alertes vendeur sont actives.",
            "url": url_for("vendor.dashboard", _external=False),
            "tag": "vendor-push-test",
        },
    )
    return jsonify({"success": True, "configured": vendor_push_is_configured(), "sent": sent})

@bp.route("/order/<int:oid>")
@login_required
@order_access_required
def order_detail(oid):
    try:
        order = (
            Order.query
            .options(
                selectinload(Order.items).selectinload(OrderItem.product)
            )
            .get_or_404(oid)
        )
    except Exception:
        current_app.logger.exception(
            "order_detail.load_error — oid=%s vendor_id=%s",
            oid,
            getattr(current_user, "id", None),
        )
        flash("Impossible de charger cette commande. Merci de réessayer.", "danger")
        return redirect(url_for("vendor.earnings"))

    # Audit (accès autorisé)
    try:
        log_access("view_order", "order", order.id, success=True)
    except Exception:
        # Non bloquant : si le log échoue, la page continue de s'afficher
        current_app.logger.warning(
            "order_detail.audit_log_failed — oid=%s", oid
        )

    # Numéros de contact depuis la configuration (plus de numéros fictifs)
    admin_phone = (
        current_app.config.get("ADMIN_PHONE")
        or current_app.config.get("SUPPORT_WHATSAPP_NUMBER")
        or ""
    )
    delivery_phone = (
        current_app.config.get("DELIVERY_WHATSAPP_NUMBER")
        or current_app.config.get("ADMIN_PHONE")
        or ""
    )

    return render_template(
        "vendor/order_detail.html",
        order=order,
        admin_phone=admin_phone,
        delivery_phone=delivery_phone,
    )

# ==================== ANCIENNES ROUTES VENDEUR ====================

def _parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _resolve_earnings_filter(args, *, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    next_year = year_start.replace(year=year_start.year + 1)

    range_filter = (args.get("range") or "month").strip().lower()
    if range_filter not in {"today", "month", "year", "custom"}:
        range_filter = "month"

    show = (args.get("show") or "all").strip().lower()
    if show not in {"all", "pending", "confirmed"}:
        show = "all"

    date_from_raw = (args.get("from") or "").strip()
    date_to_raw = (args.get("to") or "").strip()
    date_from = _parse_date(date_from_raw) if date_from_raw else None
    date_to = _parse_date(date_to_raw) if date_to_raw else None

    normalized_from = ""
    normalized_to = ""

    if range_filter == "today":
        start = today_start
        end = today_start + timedelta(days=1)
        date_range_label = "Aujourd'hui"
    elif range_filter == "year":
        start = year_start
        end = next_year
        date_range_label = "Cette année"
    elif range_filter == "custom":
        if date_from and date_to and date_from > date_to:
            date_from, date_to = date_to, date_from
        if date_from and date_to:
            start = date_from
            end = date_to + timedelta(days=1)
            normalized_from = date_from.strftime("%Y-%m-%d")
            normalized_to = date_to.strftime("%Y-%m-%d")
        elif date_from:
            start = date_from
            end = today_start + timedelta(days=1)
            if end <= start:
                end = start + timedelta(days=1)
            normalized_from = date_from.strftime("%Y-%m-%d")
        elif date_to:
            start = date_to
            end = date_to + timedelta(days=1)
            normalized_to = date_to.strftime("%Y-%m-%d")
        else:
            range_filter = "month"
            start = month_start
            end = next_month
            date_range_label = "Ce mois"
        if range_filter == "custom":
            date_range_label = "Dates choisies"
    else:
        start = month_start
        end = next_month
        date_range_label = "Ce mois"

    if range_filter == "today":
        normalized_from = ""
        normalized_to = ""
    elif range_filter == "month":
        normalized_from = ""
        normalized_to = ""
    elif range_filter == "year":
        normalized_from = ""
        normalized_to = ""

    if end <= start:
        end = start + timedelta(days=1)

    return {
        "range_filter": range_filter,
        "date_range_label": date_range_label,
        "date_from": normalized_from,
        "date_to": normalized_to,
        "show": show,
        "start": start,
        "end": end,
    }


@bp.route("/security", methods=["GET"])
@login_required
def security():
    return redirect(url_for("vendor.earnings"), code=302)


@bp.route("/security/pin", methods=["POST"])
@login_required
def set_security_pin():
    return redirect(url_for("vendor.earnings"), code=302)


# ==================== REVENUS ====================

@bp.route("/earnings")
@login_required
def earnings():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    vendor_id = current_user.id
    now = datetime.utcnow()
    earnings_filter = _resolve_earnings_filter(request.args, now=now)
    range_filter = earnings_filter["range_filter"]
    date_range_label = earnings_filter["date_range_label"]
    date_from = earnings_filter["date_from"]
    date_to = earnings_filter["date_to"]
    show = earnings_filter["show"]
    start = earnings_filter["start"]
    end = earnings_filter["end"]

    order_amounts_subquery = (
        db.session.query(
            OrderItem.order_id.label("order_id"),
            db.func.sum(OrderItem.price * OrderItem.quantity).label("amount_cents"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(Product.vendor_id == vendor_id)
        .filter(Product.kind != "service")
        .filter(Order.created_at >= start, Order.created_at < end)
        .filter(~Order.status.in_(CASHBOOK_EXCLUDED_ORDER_STATUSES))
        .group_by(OrderItem.order_id)
        .subquery()
    )

    receipt_order_subquery = (
        db.session.query(VendorReceipt.order_id.label("order_id"))
        .filter(
            VendorReceipt.vendor_id == vendor_id,
            VendorReceipt.order_id.isnot(None),
        )
        .group_by(VendorReceipt.order_id)
        .subquery()
    )

    totals_query = (
        db.session.query(
            db.func.coalesce(
                db.func.sum(
                    case(
                        (
                            receipt_order_subquery.c.order_id.isnot(None),
                            order_amounts_subquery.c.amount_cents,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("confirmed_cents"),
            db.func.coalesce(
                db.func.sum(
                    case(
                        (
                            receipt_order_subquery.c.order_id.is_(None),
                            order_amounts_subquery.c.amount_cents,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("pending_cents"),
            db.func.count(order_amounts_subquery.c.order_id).label("orders_count"),
        )
        .select_from(order_amounts_subquery)
        .outerjoin(
            receipt_order_subquery,
            receipt_order_subquery.c.order_id == order_amounts_subquery.c.order_id,
        )
    )
    if show == "pending":
        totals_query = totals_query.filter(receipt_order_subquery.c.order_id.is_(None))
    elif show == "confirmed":
        totals_query = totals_query.filter(receipt_order_subquery.c.order_id.isnot(None))
    totals_row = totals_query.one()
    total_confirmed = int(totals_row.confirmed_cents or 0)
    total_pending = int(totals_row.pending_cents or 0)
    total_orders_count = int(totals_row.orders_count or 0)

    base_list_query = (
        Order.query.options(
            load_only(Order.id, Order.created_at, Order.status),
            selectinload(Order.items)
            .load_only(OrderItem.id, OrderItem.order_id, OrderItem.product_id, OrderItem.quantity)
            .selectinload(OrderItem.product)
            .load_only(Product.id, Product.vendor_id, Product.name),
        )
        .join(order_amounts_subquery, order_amounts_subquery.c.order_id == Order.id)
        .outerjoin(receipt_order_subquery, receipt_order_subquery.c.order_id == Order.id)
    )
    if show == "pending":
        base_list_query = base_list_query.filter(receipt_order_subquery.c.order_id.is_(None))
    elif show == "confirmed":
        base_list_query = base_list_query.filter(receipt_order_subquery.c.order_id.isnot(None))
    base_list_query = base_list_query.order_by(Order.created_at.desc(), Order.id.desc())

    page = page_from_args(request.args)
    pagination = paginate_with_clamped_page(base_list_query, page=page, per_page=30, error_out=False)
    orders = pagination.items

    page_order_ids = [int(order.id) for order in orders if getattr(order, "id", None) is not None]
    order_amount_map = {}
    if page_order_ids:
        amount_rows = (
            db.session.query(
                order_amounts_subquery.c.order_id,
                order_amounts_subquery.c.amount_cents,
            )
            .filter(order_amounts_subquery.c.order_id.in_(page_order_ids))
            .all()
        )
        order_amount_map = {
            int(order_id): int(amount_cents or 0)
            for order_id, amount_cents in amount_rows
            if order_id is not None
        }

    receipt_map = {}
    if page_order_ids:
        page_receipts = (
            VendorReceipt.query
            .options(load_only(VendorReceipt.order_id, VendorReceipt.note))
            .filter(
                VendorReceipt.vendor_id == vendor_id,
                VendorReceipt.order_id.in_(page_order_ids),
            )
            .all()
        )
        receipt_map = {receipt.order_id: receipt for receipt in page_receipts}

    return render_template(
        "vendor/earnings.html",
        range_filter=range_filter,
        date_range_label=date_range_label,
        date_from=date_from,
        date_to=date_to,
        show=show,
        orders=orders,
        pagination=pagination,
        receipt_map=receipt_map,
        order_amount_map=order_amount_map,
        total_confirmed=total_confirmed,
        total_pending=total_pending,
        total_orders_count=total_orders_count,
    )


@bp.route("/earnings/history")
@login_required
def earnings_history():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    return redirect(url_for("vendor.earnings"), code=302)


@bp.route("/earnings/history/export.csv")
@login_required
def earnings_history_export_csv():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    return redirect(url_for("vendor.earnings"), code=302)


@bp.route("/earnings/history/export.pdf")
@login_required
def earnings_history_export_pdf():
    access_guard = _require_physical_vendor_access(strict_forbidden=True)
    if access_guard:
        return access_guard

    return redirect(url_for("vendor.earnings"), code=302)


# ==================== ROUTES AJAX/API POUR VENDEURS ====================

@bp.route("/api/shop/stats")
@login_required
def shop_stats_api():
    """API pour les statistiques de la boutique"""
    started_at = perf_counter()
    if current_user.role != "vendor":
        return jsonify({"error": "Accs interdit"}), 403

    try:
        shop = Shop.query.filter_by(vendor_id=current_user.id).first()
        if not shop:
            return jsonify({"error": "Boutique non trouve"}), 404

        product_count = Product.query.filter_by(shop_id=shop.id).count()
        start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_stats_row = (
            db.session.query(
                db.func.count(db.func.distinct(Order.id)).label("orders_count"),
                db.func.coalesce(db.func.sum(OrderItem.price * OrderItem.quantity), 0).label("revenue_cents"),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(Product, Product.id == OrderItem.product_id)
            .filter(
                Product.shop_id == shop.id,
                Order.created_at >= start_of_month,
                Order.status == "delivered",
            )
            .first()
        )
        orders_this_month = int((month_stats_row.orders_count if month_stats_row else 0) or 0)
        revenue_this_month_cents = int((month_stats_row.revenue_cents if month_stats_row else 0) or 0)
    except SQLAlchemyError:
        current_app.logger.exception(
            "vendor.shop_stats_api.db_error",
            extra={"vendor_id": getattr(current_user, "id", None)},
        )
        _log_perf(
            "vendor.shop_stats_api",
            started_at,
            vendor_id=getattr(current_user, "id", None),
            error="database_error",
        )
        return jsonify({"error": "database_error"}), 500

    response = jsonify({
        "shop": {
            "name": shop.name,
            "product_count": product_count,
            "orders_this_month": orders_this_month,
            "revenue_this_month": revenue_this_month_cents / 100,
            "is_active": shop.is_active,
            "rating": shop.rating or 0,
        }
    })
    response.headers["Cache-Control"] = f"private, max-age={int(LIVE_ENDPOINT_MICROCACHE_TTL_SECONDS)}"
    _log_perf(
        "vendor.shop_stats_api",
        started_at,
        vendor_id=getattr(current_user, "id", None),
        product_count=product_count,
        orders_this_month=orders_this_month,
    )
    return response


@bp.route("/api/products/stock")
@login_required
def products_stock_api():
    """API pour la gestion des stocks"""
    if current_user.role != "vendor":
        return jsonify({"error": "Accs interdit"}), 403

    page = _normalize_positive_int(
        _safe_int(request.args.get("page"), 1),
        default=1,
        minimum=1,
    )
    per_page = _normalize_positive_int(
        _safe_int(request.args.get("per_page"), 50),
        default=50,
        minimum=1,
        maximum=100,
    )

    stock_query = (
        Product.query
        .filter_by(vendor_id=current_user.id)
        .order_by(Product.created_at.desc(), Product.id.desc())
    )
    pagination = (
        paginate_with_clamped_page(stock_query, page=page, per_page=per_page, error_out=False)
    )
    products = pagination.items

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

    return jsonify({
        "products": stock_data,  # legacy key for compatibility
        "items": stock_data,
        "page": pagination.page,
        "pages": pagination.pages,
        "total": pagination.total,
        "per_page": pagination.per_page,
    })

# ==================== REDIRECTIONS POUR COMPATIBILIT ====================

@bp.route("/shop/setup")
@login_required
def setup_shop_redirect():
    """Redirection pour compatibilit (ancienne route)"""
    return redirect(url_for("vendor.manage_shop"))





@bp.route("/products/search")
@login_required
def products_search():
    """Recherche en temps rel des produits"""
    started_at = perf_counter()
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
                product_catalog_block_reasons=_catalog_block_reasons,
            )

    search_term_raw = (request.args.get("q") or "").strip()
    search_term = search_term_raw if len(search_term_raw) >= 2 else ""
    category_id = request.args.get("category", "")

    # Min-length guard: vite les ILIKE '%x%' trs coteux sur 1 caractre.
    if search_term_raw and not search_term:
        settings = PlatformSettings.get()
        low_stock_threshold = int(settings.low_stock_threshold or 5)
        return render_template(
            "vendor/partials/_product_grid.html",
            products=[],
            low_stock_threshold=low_stock_threshold,
            search_term=search_term_raw,
            catalog_title=type_flags["catalog_title"] if current_user.role == "vendor" else "Produits",
            catalog_create_label=type_flags["catalog_create_label"] if current_user.role == "vendor" else "Nouveau produit",
            product_catalog_block_reasons=_catalog_block_reasons,
        )

    if current_user.role == "admin":
        query = Product.query
    else:
        query = Product.query.filter_by(vendor_id=current_user.id)
        query = _scope_catalog_query(
            query,
            type_flags["allows_products"],
            type_flags["allows_services"],
        )

    if search_term:
        query = query.filter(
            db.or_(
                Product.name.ilike(f"%{search_term}%"),
                Product.description.ilike(f"%{search_term}%")
            )
        )

    if category_id and category_id != "all":
        try:
            category_id_int = int(category_id)
            query = query.filter(Product.category_id == category_id_int)
        except (TypeError, ValueError):
            pass

    result_limit = 20 if search_term else 100
    products = query.order_by(Product.created_at.desc()).limit(result_limit).all()
    product_promos = _product_promo_snapshot(products)

    settings = PlatformSettings.get()
    low_stock_threshold = int(settings.low_stock_threshold or 5)
    _log_perf(
        "vendor.products_search",
        started_at,
        vendor_id=getattr(current_user, "id", None),
        q_len=len(search_term_raw),
        results=len(products),
    )

    return render_template(
        "vendor/partials/_product_grid.html",
        products=products,
        low_stock_threshold=low_stock_threshold,
        search_term=search_term,
        catalog_title=type_flags["catalog_title"] if current_user.role == "vendor" else "Produits",
        catalog_create_label=type_flags["catalog_create_label"] if current_user.role == "vendor" else "Nouveau produit",
        product_catalog_block_reasons=_catalog_block_reasons,
        product_promos=product_promos,
        calculate_promo_price=calculate_promo_price,
    )


@bp.route("/stats/live")
@login_required
def stats_live():
    """Statistiques en temps réel"""
    started_at = perf_counter()

    if not hasattr(current_user, "role") or current_user.role not in ("vendor", "admin"):
        return jsonify({"error": "Accès non autorisé"}), 403

    allows_products = True
    if current_user.role == "vendor":
        vendor_shop = resolve_vendor_shop(current_user)
        vendor_flags = _vendor_type_flags(vendor_shop)
        allows_products = vendor_flags["allows_products"]

    now = datetime.utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    try:
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

        if current_user.role == "admin" or allows_products:
            settings = PlatformSettings.get()
            low_stock_threshold = int(settings.low_stock_threshold or 5)
        else:
            low_stock_threshold = 5

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

    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "vendor.stats_live.db_error",
            extra={
                "vendor_id": getattr(current_user, "id", None),
                "role": getattr(current_user, "role", None),
            },
        )
        _log_perf(
            "vendor.stats_live",
            started_at,
            vendor_id=getattr(current_user, "id", None),
            error="database_error",
        )
        return jsonify({"success": False, "error": "database_error"}), 500

    payload = {
        "success": True,
        "total_orders": total_orders,
        "total_revenue": f"{total_revenue:.0f}",
        "low_stock": low_stock,
    }
    response = jsonify(payload)
    response.headers["Cache-Control"] = f"private, max-age={int(LIVE_ENDPOINT_MICROCACHE_TTL_SECONDS)}"
    _log_perf(
        "vendor.stats_live",
        started_at,
        vendor_id=getattr(current_user, "id", None),
        total_orders=total_orders,
        low_stock=low_stock,
    )
    return response

