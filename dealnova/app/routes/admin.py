import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, session
from flask_login import login_required, current_user, logout_user
from datetime import date, datetime, timedelta
from urllib.parse import quote
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models.order import Order, OrderItem
from ..models.order_period import OrderPeriod
from ..models.financial import FinancialEntry
from ..models.maintenance import ErrorLog, MaintenanceRun
from ..models.product import Product
from ..models.featured_item import FeaturedItem
from ..models.shop import Shop
from ..models.user import User
from ..models.vendor_fulfillment import VendorFulfillment
from ..models.vendor_payout import VendorPayout
from ..models.vendor_receipt import VendorReceipt
from ..models.rental import RentalListing
from ..services.audit import log_access
from sqlalchemy.orm import selectinload
from sqlalchemy import case, or_
from sqlalchemy.exc import SQLAlchemyError  # ✅ AJOUT
from ..services.cache import bump_catalog_version
from ..services.featured_items import (
    disable_featured_item,
    featured_duration_choices,
    normalize_featured_duration,
    upsert_featured_item,
)

from ..models.platform_settings import PlatformSettings
from ..services.maintenance import (
    DB_SIZE_MB_DANGER,
    DB_SIZE_MB_WARNING,
    ERROR_LOG_RETENTION_DAYS_DEFAULT,
    EXPIRED_LOCATIONS_GT_DAYS_DANGER,
    EXPIRED_LOCATIONS_GT_DAYS_WARNING,
    ORPHAN_MEDIA_COUNT_DANGER,
    ORPHAN_MEDIA_COUNT_WARNING,
    collect_system_health,
    localize_http_error_message,
    UPLOADS_SIZE_GB_DANGER,
    UPLOADS_SIZE_GB_WARNING,
    create_pre_reset_backup,
    reset_database_keep_admins,
)
from ..services.maintenance_mode import (
    disable_maintenance_mode,
    enable_maintenance_mode,
    format_maintenance_datetime,
    get_maintenance_state,
    parse_maintenance_datetime,
    schedule_maintenance_mode,
)
from ..services.pagination import page_from_args
from ..services.order_periods import (
    CLOSED_STATUS,
    OPEN_STATUS,
    ORDER_DELETE_RETENTION_DAYS,
    create_order_period,
    close_order_period,
    order_delete_guard,
    period_bounds,
)
from ..services.financial_periods import (
    ENTRY_TYPE_DELIVERY_FEE,
    ENTRY_TYPE_RENTAL_COMMISSION,
    ENTRY_TYPE_SUBSCRIPTION,
    ensure_financial_period_for_order_period,
    record_delivery_fee_entry,
)
from ..services.delivery_context import (
    DELIVERY_SOURCE_MARKETPLACE,
    DELIVERY_SOURCE_SPECIAL,
    build_courier_whatsapp_message,
    enrich_order_delivery_context,
    enrich_orders_delivery_context,
    normalize_delivery_source,
    normalize_phone_for_wa,
)
from ..services.traffic_stats import get_live_traffic_metrics


bp = Blueprint("admin", __name__, url_prefix="/admin")
MAINTENANCE_PANEL_SESSION_KEY = "maintenance_panel_unlock_until"
MAINTENANCE_PANEL_DEFAULT_UNLOCK_MINUTES = 90

FINAL_DELIVERY_ORDER_STATUSES = {"delivered", "cancelled", "archived"}
COURIER_ASSIGNMENT_FILTERS = {"", "unassigned", "assigned", "delivered"}
COURIER_DELIVERY_IN_PROGRESS = {"new", "assigned", "picked_up", "delivering"}
COURIER_DELIVERY_COMPLETED = {"delivered", "canceled"}
DELIVERY_SOURCE_FILTERS = {"", DELIVERY_SOURCE_MARKETPLACE, DELIVERY_SOURCE_SPECIAL}
ORDER_STATUS_FILTERS = {"", "pending", "delivered", "cancelled"}
DELIVERY_STATUS_FILTERS = {"", "new", "assigned", "picked_up", "delivering", "delivered", "canceled"}
FEATURED_SEARCH_LIMIT = 18
FEATURED_STATUS_FILTERS = {"all", "active", "expired", "stopped"}
FEATURED_VIEW_FILTERS = {"overview", "history"}
ADMIN_ROLE = "admin"
MANAGER_ROLE = "manager"
MANAGER_BLOCKED_ADMIN_ENDPOINTS = {
    "admin.maintenance",
    "admin.maintenance_unlock",
    "admin.maintenance_error_delete",
    "admin.maintenance_errors_purge",
    "admin.maintenance_mode_enable",
    "admin.maintenance_mode_disable",
    "admin.maintenance_mode_schedule",
    "admin.run_maintenance",
    "admin.maintenance_reset_data",
}


def _current_admin_role() -> str:
    return (getattr(current_user, "role", "") or "").strip().lower()


def _is_manager_user() -> bool:
    return _current_admin_role() == MANAGER_ROLE


def _sensitive_admin_forbidden_response():
    message = "Acces reserve aux administrateurs principaux."
    if _is_ajax_request():
        return jsonify(success=False, message=message), 403
    flash(message, "danger")
    return redirect(url_for("admin_users.admin_dashboard"))

def _is_ajax_request() -> bool:
    return (
        request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )


def _parse_days(raw_value, default: int = 6, minimum: int = 1, maximum: int = 365) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_iso_date(raw_value: str | None) -> date | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _bool_arg(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _order_period_choices() -> list[OrderPeriod]:
    return (
        OrderPeriod.query
        .order_by(
            db.case((OrderPeriod.status == OPEN_STATUS, 0), else_=1),
            OrderPeriod.opened_at.desc(),
            OrderPeriod.id.desc(),
        )
        .all()
    )


def _period_selection_from_request(default_to_open: bool = True) -> dict:
    periods = _order_period_choices()
    open_period = next((period for period in periods if period.status == OPEN_STATUS), None)

    requested_period_id = request.args.get("period_id", type=int)
    selected_period = None
    selected_period_id = None

    if requested_period_id:
        selected_period = db.session.get(OrderPeriod, requested_period_id)
        if selected_period is not None:
            selected_period_id = selected_period.id
    if selected_period is None and default_to_open and open_period is not None:
        selected_period = open_period
        selected_period_id = open_period.id

    include_legacy = _bool_arg(request.args.get("include_legacy"))
    read_only = bool(selected_period and selected_period.status == CLOSED_STATUS)
    return {
        "periods": periods,
        "open_period": open_period,
        "selected_period": selected_period,
        "selected_period_id": selected_period_id,
        "include_legacy": include_legacy,
        "read_only": read_only,
    }


def _orders_query_for_period(*, selected_period_id: int | None, include_legacy: bool):
    query = Order.query
    if selected_period_id is not None:
        if include_legacy:
            return query.filter(or_(Order.period_id == selected_period_id, Order.period_id.is_(None)))
        return query.filter(Order.period_id == selected_period_id)
    if include_legacy:
        return query.filter(Order.period_id.is_(None))
    return query.filter(db.text("1=0"))


def _archived_orders_query():
    return (
        Order.query
        .join(OrderPeriod, Order.period_id == OrderPeriod.id)
        .filter(OrderPeriod.status == CLOSED_STATUS)
    )


def _archived_orders_context(source=None) -> dict:
    source = source or request.args
    archives_page = page_from_args(source, key="archives_page", default=1)
    archive_period_id = source.get("archive_period_id", type=int)

    query = _archived_orders_query().options(
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.period),
    )
    if archive_period_id:
        query = query.filter(Order.period_id == archive_period_id)

    archives_pagination = query.order_by(Order.created_at.desc()).paginate(
        page=archives_page, per_page=50, error_out=False
    )
    archive_orders = archives_pagination.items

    closed_periods = (
        OrderPeriod.query
        .filter(OrderPeriod.status == CLOSED_STATUS)
        .order_by(OrderPeriod.closed_at.desc(), OrderPeriod.id.desc())
        .all()
    )

    now = datetime.utcnow()
    archive_delete_guards = {}
    for order in archive_orders:
        allowed, message, available_at = order_delete_guard(order, now=now)
        archive_delete_guards[order.id] = {
            "allowed": allowed,
            "message": message,
            "available_at": available_at,
        }

    return {
        "archive_orders": archive_orders,
        "archives_pagination": archives_pagination,
        "archive_period_id": archive_period_id,
        "closed_periods": closed_periods,
        "archive_delete_guards": archive_delete_guards,
        "retention_days": ORDER_DELETE_RETENTION_DAYS,
    }


def _order_periods_context() -> dict:
    periods = (
        OrderPeriod.query
        .order_by(OrderPeriod.opened_at.desc(), OrderPeriod.id.desc())
        .all()
    )
    open_period = next((period for period in periods if period.status == OPEN_STATUS), None)

    period_counts = {
        row.period_id: int(row.count)
        for row in (
            db.session.query(Order.period_id, db.func.count(Order.id).label("count"))
            .group_by(Order.period_id)
            .all()
        )
        if row.period_id is not None
    }

    return {
        "periods": periods,
        "open_period": open_period,
        "period_counts": period_counts,
    }


def _apply_delivery_filters(
    base_query,
    *,
    order_status_filter: str = "",
    delivery_status_filter: str = "",
    source_filter: str = "",
    city_filter: str = "",
    client_filter: str = "",
    phone_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    product_filter: str = "",
    shop_filter: str = "",
):
    query = base_query
    if order_status_filter:
        query = query.filter(Order.status == order_status_filter)
    if delivery_status_filter:
        query = query.filter(Order.delivery_status == delivery_status_filter)
    if source_filter:
        query = query.filter(Order.delivery_source == source_filter)
    if city_filter:
        query = query.filter(or_(Order.city == city_filter, Order.delivery_city == city_filter))
    if client_filter:
        query = query.filter(Order.full_name.ilike(f"%{client_filter}%"))
    if phone_filter:
        query = query.filter(Order.phone.ilike(f"%{phone_filter}%"))

    if date_from:
        try:
            start_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Order.created_at >= start_dt)
        except ValueError:
            pass
    if date_to:
        try:
            end_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Order.created_at < end_dt)
        except ValueError:
            pass

    if product_filter or shop_filter:
        query = query.join(OrderItem, OrderItem.order_id == Order.id).join(
            Product, OrderItem.product_id == Product.id
        )
        if shop_filter:
            query = query.join(Shop, Product.shop_id == Shop.id)
            query = query.filter(Shop.name.ilike(f"%{shop_filter}%"))
        if product_filter:
            query = query.filter(Product.name.ilike(f"%{product_filter}%"))
        query = query.distinct()
    return query


def _available_couriers() -> list[User]:
    couriers = (
        User.query
        .filter(
            User.role == "courier",
            User.is_active.is_(True),
            User.courier_is_active.is_(True),
            User.courier_is_available.is_(True),
        )
        .order_by(User.username.asc())
        .all()
    )
    return _attach_courier_delivery_counts(couriers)


def _available_couriers_count() -> int:
    return int(
        User.query
        .filter(
            User.role == "courier",
            User.is_active.is_(True),
            User.courier_is_active.is_(True),
            User.courier_is_available.is_(True),
        )
        .count()
    )


def _courier_filter_choices() -> list[User]:
    couriers = (
        User.query
        .filter(User.role == "courier")
        .order_by(User.username.asc())
        .all()
    )
    return _attach_courier_delivery_counts(couriers)


def _attach_courier_delivery_counts(couriers: list[User]) -> list[User]:
    courier_ids = [courier.id for courier in couriers]
    counts = {}
    if courier_ids:
        rows = (
            db.session.query(
                Order.courier_id.label("courier_id"),
                db.func.count(Order.id).label("delivered_count"),
            )
            .filter(
                Order.courier_id.in_(courier_ids),
                Order.delivery_status == "delivered",
            )
            .group_by(Order.courier_id)
            .all()
        )
        counts = {int(row.courier_id): int(row.delivered_count or 0) for row in rows if row.courier_id is not None}

    for courier in couriers:
        courier.delivered_count = counts.get(courier.id, 0)
    return couriers


def _normalize_courier_assignment_filter(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in COURIER_ASSIGNMENT_FILTERS else ""


def _normalize_delivery_source_filter(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    if value not in DELIVERY_SOURCE_FILTERS:
        return ""
    if not value:
        return ""
    return normalize_delivery_source(value)


def _normalize_order_status_filter(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in ORDER_STATUS_FILTERS else ""


def _normalize_delivery_status_filter(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in DELIVERY_STATUS_FILTERS else ""


def _apply_courier_assignment_filter(query, assignment_filter: str):
    if assignment_filter == "unassigned":
        return query.filter(Order.courier_id.is_(None))
    if assignment_filter == "assigned":
        return query.filter(
            Order.courier_id.isnot(None),
            Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS)),
        )
    if assignment_filter == "delivered":
        return query.filter(Order.delivery_status == "delivered")
    return query


def _sync_courier_availability(courier: User | None) -> None:
    if courier is None:
        return
    if not courier.is_active or not courier.courier_is_active:
        courier.courier_is_available = False
        return
    has_active_delivery = (
        Order.query
        .filter(
            Order.courier_id == courier.id,
            Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS)),
        )
        .first()
        is not None
    )
    courier.courier_is_available = not has_active_delivery


def _operational_deliveries_query(base_query, *, now: datetime | None = None, window_hours: int = 24):
    current_time = now or datetime.utcnow()
    cutoff = current_time - timedelta(hours=window_hours)
    return base_query.filter(
        or_(
            Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS)),
            Order.created_at >= cutoff,
            Order.delivered_at >= cutoff,
        )
    )


def _maintenance_health_placeholder(days: int, note: str = "metrics moved to CLI") -> dict:
    return {
        "uploads_size": "N/A",
        "uploads_size_bytes": None,
        "uploads_size_gb": None,
        "uploads_file_count": "N/A",
        "expired_locations_count": None,
        "expired_locations_gt_days": None,
        "orphan_media_count": "N/A",
        "cache_status": "N/A",
        "db_size": "N/A",
        "db_size_bytes": None,
        "db_size_mb": None,
        "db_engine": "N/A",
        "errors": [note] if note else [],
        "days_threshold": days,
    }


# ======================
# MAINTENANCE HELPERS
# ======================

def _to_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_datetime_local(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M")


def _maintenance_status(value, warning: float, danger: float) -> dict:
    numeric = _to_float_or_none(value)
    if numeric is None:
        return {"level": "na", "label": "N/A", "class_name": "status-na"}
    if numeric > danger:
        return {"level": "danger", "label": "🔴 Danger", "class_name": "status-danger"}
    if numeric > warning:
        return {"level": "warning", "label": "⚠️ A surveiller", "class_name": "status-warn"}
    return {"level": "ok", "label": "✅ OK", "class_name": "status-ok"}


def _maintenance_badges(health: dict) -> dict[str, dict]:
    uploads_size_gb = _to_float_or_none(health.get("uploads_size_gb"))
    orphan_media_count = _to_float_or_none(health.get("orphan_media_count"))
    expired_locations = _to_float_or_none(
        health.get("expired_locations_gt_days", health.get("expired_locations_count"))
    )
    db_size_mb = _to_float_or_none(health.get("db_size_mb"))

    return {
        "uploads_size_gb": _maintenance_status(uploads_size_gb, UPLOADS_SIZE_GB_WARNING, UPLOADS_SIZE_GB_DANGER),
        "orphan_media_count": _maintenance_status(
            orphan_media_count, ORPHAN_MEDIA_COUNT_WARNING, ORPHAN_MEDIA_COUNT_DANGER
        ),
        "expired_locations_gt_days": _maintenance_status(
            expired_locations, EXPIRED_LOCATIONS_GT_DAYS_WARNING, EXPIRED_LOCATIONS_GT_DAYS_DANGER
        ),
        "db_size_mb": _maintenance_status(db_size_mb, DB_SIZE_MB_WARNING, DB_SIZE_MB_DANGER),
    }


def _maintenance_view_context(days: int, reset_result=None, errors_page: int = 1) -> dict:
    health = _maintenance_health_placeholder(
        days,
        note="Aucun rapport enregistre. Lancez flask cleanup --mode quick --days %d." % days,
    )
    report = None
    report_cleanup = None
    last_run = None
    last_quick_run = None
    last_full_run = None

    try:
        last_run = MaintenanceRun.query.order_by(MaintenanceRun.started_at.desc()).first()
        last_quick_run = (
            MaintenanceRun.query.filter_by(mode="quick").order_by(MaintenanceRun.started_at.desc()).first()
        )
        last_full_run = (
            MaintenanceRun.query.filter_by(mode="full").order_by(MaintenanceRun.started_at.desc()).first()
        )

        if last_run and isinstance(last_run.result_counts, dict):
            report = last_run.result_counts
            report_health = report.get("health")
            if isinstance(report_health, dict):
                health = report_health
                if health.get("days_threshold") is None:
                    health["days_threshold"] = report.get("days", days)
            if isinstance(report.get("cleanup"), dict):
                report_cleanup = report.get("cleanup")
            else:
                report_cleanup = report
    except Exception:
        db.session.rollback()
        health = _maintenance_health_placeholder(
            days,
            note="N/A: rapport maintenance indisponible. Lancez `flask db upgrade` puis `flask cleanup --mode quick --days %d`." % days,
        )
        report = None
        report_cleanup = None
        last_run = None
        last_quick_run = None
        last_full_run = None

    try:
        live_health = collect_system_health(expired_days=days)
        for key in ("db_size", "db_size_bytes", "db_size_mb", "db_engine"):
            health[key] = live_health.get(key)
    except Exception:
        db.session.rollback()

    health_badges = _maintenance_badges(health)

    errors_block = {
        "available": True,
        "window_days": ERROR_LOG_RETENTION_DAYS_DEFAULT,
        "total_500_last_24h": "N/A",
        "items": [],
        "page": max(1, int(errors_page or 1)),
        "per_page": 20,
        "pagination": None,
        "note": "",
    }
    try:
        since = datetime.utcnow() - timedelta(days=ERROR_LOG_RETENTION_DAYS_DEFAULT)
        errors_query = (
            ErrorLog.query
            .filter(ErrorLog.status_code == 500, ErrorLog.created_at >= since)
            .order_by(ErrorLog.created_at.desc(), ErrorLog.id.desc())
        )
        errors_pagination = errors_query.paginate(
            page=errors_block["page"],
            per_page=errors_block["per_page"],
            error_out=False,
        )
        errors_block["total_500_last_24h"] = int(errors_pagination.total)
        errors_block["items"] = errors_pagination.items
        for err in errors_block["items"]:
            try:
                err.display_short_message = (
                    localize_http_error_message(getattr(err, "status_code", None), getattr(err, "short_message", None))
                    or getattr(err, "short_message", None)
                )
            except Exception:
                err.display_short_message = getattr(err, "short_message", None)
        errors_block["pagination"] = errors_pagination
        errors_block["page"] = int(errors_pagination.page)
    except Exception:
        db.session.rollback()
        errors_block["available"] = False
        errors_block["total_500_last_24h"] = "N/A"
        errors_block["items"] = []
        errors_block["note"] = "N/A: source de logs indisponible. Verifiez la migration `flask db upgrade`."

    last_run_label = "N/A"
    if last_run:
        last_dt = last_run.finished_at or last_run.started_at
        date_label = last_dt.strftime("%d/%m/%Y %H:%M:%S") if last_dt else "N/A"
        mode_label = (last_run.mode or "N/A").lower()
        duration_label = f"{last_run.duration_ms} ms" if last_run.duration_ms is not None else "N/A"
        last_run_label = f"{date_label} ({mode_label}, {duration_label})"

    maintenance_mode = get_maintenance_state(force_refresh=True)
    maintenance_mode["enabled_at_label"] = format_maintenance_datetime(maintenance_mode.get("enabled_at"))
    maintenance_mode["starts_at_label"] = format_maintenance_datetime(maintenance_mode.get("starts_at"))
    maintenance_mode["ends_at_label"] = format_maintenance_datetime(maintenance_mode.get("ends_at"))
    maintenance_mode["starts_at_local"] = _format_datetime_local(maintenance_mode.get("starts_at"))
    maintenance_mode["ends_at_local"] = _format_datetime_local(maintenance_mode.get("ends_at"))
    live_traffic = get_live_traffic_metrics()

    return {
        "health": health,
        "health_badges": health_badges,
        "days": days,
        "report": report,
        "report_cleanup": report_cleanup,
        "last_run": last_run,
        "last_quick_run": last_quick_run,
        "last_full_run": last_full_run,
        "last_run_label": last_run_label,
        "maintenance_mode": maintenance_mode,
        "live_traffic": live_traffic,
        "errors_block": errors_block,
        "reset_result": reset_result,
    }


def _featured_search_results(source=None):
    source = source or request.args
    shop_q = (source.get("shop_q") or "").strip()
    product_q = (source.get("product_q") or "").strip()
    location_q = (source.get("location_q") or "").strip()

    shop_results = []
    product_results = []
    location_results = []

    if len(shop_q) >= 2:
        shop_results = (
            Shop.query
            .options(selectinload(Shop.vendor).load_only(User.id, User.username))
            .filter(Shop.name.ilike(f"%{shop_q}%"))
            .order_by(Shop.name.asc())
            .limit(FEATURED_SEARCH_LIMIT)
            .all()
        )

    if len(product_q) >= 2:
        product_results = (
            Product.query
            .options(
                selectinload(Product.shop).load_only(Shop.id, Shop.name),
                selectinload(Product.vendor).load_only(User.id, User.username),
            )
            .filter(Product.name.ilike(f"%{product_q}%"))
            .order_by(Product.created_at.desc())
            .limit(FEATURED_SEARCH_LIMIT)
            .all()
        )

    if len(location_q) >= 2:
        like_term = f"%{location_q}%"
        location_results = (
            RentalListing.query
            .options(selectinload(RentalListing.shop).load_only(Shop.id, Shop.name))
            .filter(
                or_(
                    RentalListing.title.ilike(like_term),
                    RentalListing.city.ilike(like_term),
                    RentalListing.area.ilike(like_term),
                )
            )
            .order_by(RentalListing.created_at.desc())
            .limit(FEATURED_SEARCH_LIMIT)
            .all()
        )

    return {
        "shop_q": shop_q,
        "product_q": product_q,
        "location_q": location_q,
        "shop_results": shop_results,
        "product_results": product_results,
        "location_results": location_results,
    }


def _normalize_featured_status(raw_value: str | None) -> str:
    value = (raw_value or "all").strip().lower()
    return value if value in FEATURED_STATUS_FILTERS else "all"


def _normalize_featured_view(raw_value: str | None) -> str:
    value = (raw_value or "overview").strip().lower()
    return value if value in FEATURED_VIEW_FILTERS else "overview"


def _featured_items_url_from_context(context: dict) -> str:
    params = {}
    if context.get("featured_view") and context["featured_view"] != "overview":
        params["view"] = context["featured_view"]
    if context.get("status_filter") and context["status_filter"] != "all":
        params["status"] = context["status_filter"]
    if context.get("shop_q"):
        params["shop_q"] = context["shop_q"]
    if context.get("product_q"):
        params["product_q"] = context["product_q"]
    if context.get("location_q"):
        params["location_q"] = context["location_q"]
    return url_for("admin.featured_items", **params)


def _build_featured_items_context(source=None) -> dict:
    source = source or request.args
    featured_view = _normalize_featured_view(source.get("view"))
    status_filter = _normalize_featured_status(source.get("status"))
    now = datetime.utcnow()
    latest_rows_query = (
        FeaturedItem.query
        .options(
            selectinload(FeaturedItem.shop).selectinload(Shop.vendor),
            selectinload(FeaturedItem.product).selectinload(Product.shop),
            selectinload(FeaturedItem.location).selectinload(RentalListing.shop),
            selectinload(FeaturedItem.vendor),
            selectinload(FeaturedItem.created_by_admin),
        )
        .order_by(
            FeaturedItem.is_active.desc(),
            case(
                (FeaturedItem.target_type == FeaturedItem.TARGET_SHOP, 0),
                (FeaturedItem.target_type == FeaturedItem.TARGET_PRODUCT, 1),
                (FeaturedItem.target_type == FeaturedItem.TARGET_LOCATION, 2),
                else_=3,
            ),
            FeaturedItem.ends_at.desc(),
            FeaturedItem.created_at.desc(),
        )
    )
    latest_rows = []
    history_items = []
    seen_targets = set()
    for item in latest_rows_query.all():
        target_key = (item.target_type, item.target_id)
        if target_key in seen_targets:
            item.ui_status = "history"
            item.can_delete_after = item.created_at + timedelta(days=30)
            item.can_delete_now = item.can_delete_after <= now
            history_items.append(item)
            continue
        seen_targets.add(target_key)
        if item.ends_at < now:
            item.ui_status = "expired"
        elif item.is_active and item.starts_at <= now <= item.ends_at:
            item.ui_status = "active"
        else:
            item.ui_status = "stopped"
        if item.ui_status == "active":
            latest_rows.append(item)
        else:
            item.can_delete_after = item.created_at + timedelta(days=30)
            item.can_delete_now = item.can_delete_after <= now
            history_items.append(item)

    history_items.sort(key=lambda item: (item.created_at, item.id), reverse=True)

    if status_filter == "active":
        active_items = latest_rows
    elif status_filter in {"expired", "stopped"}:
        active_items = []
    else:
        active_items = latest_rows

    total_count = len(latest_rows)
    active_count = sum(1 for item in latest_rows if item.ui_status == "active")
    expiring_soon = sorted(
        [
            item for item in latest_rows
            if item.ui_status == "active" and item.ends_at <= now + timedelta(days=3)
        ],
        key=lambda item: item.ends_at,
    )
    counts_by_type = {
        "shop": 0,
        "product": 0,
        "location": 0,
    }
    active_target_keys = set()
    for item in latest_rows:
        if item.ui_status == "active" and item.target_type in counts_by_type:
            counts_by_type[item.target_type] += 1
            active_target_keys.add((item.target_type, item.target_id))

    context = {
        "active_items": active_items,
        "history_items": history_items,
        "history_count": len(history_items),
        "active_target_keys": active_target_keys,
        "featured_view": featured_view,
        "status_filter": status_filter,
        "total_count": total_count,
        "active_count": active_count,
        "expiring_soon": expiring_soon,
        "counts_by_type": counts_by_type,
        "duration_choices": featured_duration_choices(),
        "now_utc": now,
    }
    context.update(_featured_search_results(source))
    return context


def _maintenance_panel_password_hash() -> str:
    configured = current_app.config.get("MAINTENANCE_PANEL_PASSWORD_HASH")
    if configured:
        return str(configured).strip()
    return (os.getenv("MAINTENANCE_PANEL_PASSWORD_HASH") or "").strip()


def _maintenance_panel_unlock_minutes() -> int:
    raw_value = current_app.config.get("MAINTENANCE_PANEL_UNLOCK_MINUTES")
    if raw_value in (None, ""):
        raw_value = os.getenv("MAINTENANCE_PANEL_UNLOCK_MINUTES", str(MAINTENANCE_PANEL_DEFAULT_UNLOCK_MINUTES))
    try:
        return max(1, min(1440, int(raw_value)))
    except (TypeError, ValueError):
        return MAINTENANCE_PANEL_DEFAULT_UNLOCK_MINUTES


def _maintenance_panel_enabled() -> bool:
    return bool(_maintenance_panel_password_hash())


def _maintenance_panel_unlock_until() -> datetime | None:
    raw_value = session.get(MAINTENANCE_PANEL_SESSION_KEY)
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value))
    except (TypeError, ValueError):
        session.pop(MAINTENANCE_PANEL_SESSION_KEY, None)
        return None


def _maintenance_panel_is_unlocked() -> bool:
    if not _maintenance_panel_enabled():
        return True
    unlock_until = _maintenance_panel_unlock_until()
    if unlock_until is None:
        return False
    if unlock_until <= datetime.utcnow():
        session.pop(MAINTENANCE_PANEL_SESSION_KEY, None)
        return False
    return True


def _set_maintenance_panel_unlock() -> datetime:
    unlock_until = datetime.utcnow() + timedelta(minutes=_maintenance_panel_unlock_minutes())
    session[MAINTENANCE_PANEL_SESSION_KEY] = unlock_until.isoformat()
    session.modified = True
    return unlock_until


def _maintenance_protected_redirect(days: int | None = None, errors_page: int | None = None):
    if _is_ajax_request():
        return (
            jsonify(
                {
                    "success": False,
                    "error": "maintenance_unlock_required",
                    "unlock_url": url_for("admin.maintenance"),
                }
            ),
            423,
        )

    flash("Déverrouillez d'abord la page maintenance avec le mot de passe dédié.", "warning")
    route_args = {}
    if days is not None:
        route_args["days"] = days
    if errors_page is not None:
        route_args["errors_page"] = errors_page
    return redirect(url_for("admin.maintenance", **route_args))


def _maintenance_runtime_context() -> dict:
    now = datetime.utcnow()
    next_maintenance = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now >= next_maintenance:
        next_maintenance = next_maintenance + timedelta(days=1)

    time_until = next_maintenance - now
    hours = int(time_until.total_seconds() // 3600)
    minutes = int((time_until.total_seconds() % 3600) // 60)

    last_maintenance = MaintenanceRun.query.order_by(MaintenanceRun.finished_at.desc()).first()
    maintenance_mode = get_maintenance_state(force_refresh=True)
    maintenance_mode["enabled_at_label"] = format_maintenance_datetime(maintenance_mode.get("enabled_at"))
    maintenance_mode["starts_at_label"] = format_maintenance_datetime(maintenance_mode.get("starts_at"))
    maintenance_mode["ends_at_label"] = format_maintenance_datetime(maintenance_mode.get("ends_at"))
    maintenance_mode["starts_at_local"] = _format_datetime_local(maintenance_mode.get("starts_at"))
    maintenance_mode["ends_at_local"] = _format_datetime_local(maintenance_mode.get("ends_at"))

    unlock_until = _maintenance_panel_unlock_until()
    return {
        "next_maintenance_time": next_maintenance.strftime("%H:%M"),
        "next_maintenance_in": f"{hours}h {minutes:02d}min",
        "last_maintenance": last_maintenance,
        "now": now,
        "maintenance_mode": maintenance_mode,
        "maintenance_panel_password_enabled": _maintenance_panel_enabled(),
        "maintenance_panel_locked": not _maintenance_panel_is_unlocked(),
        "maintenance_unlock_minutes": _maintenance_panel_unlock_minutes(),
        "maintenance_unlock_until_label": format_maintenance_datetime(unlock_until),
    }


# ======================
# ADMIN ONLY
# ======================
@bp.before_request
@login_required
def restrict_admin():
    role = _current_admin_role()
    if role in {ADMIN_ROLE, MANAGER_ROLE}:
        return None

    if role == "courier":
        return render_template("errors/403.html"), 403

    flash("Accès réservé aux administrateurs", "danger")
    return redirect(url_for("shop.home"))


@bp.before_request
def restrict_sensitive_pages_for_manager():
    if _is_manager_user() and request.endpoint in MANAGER_BLOCKED_ADMIN_ENDPOINTS:
        return _sensitive_admin_forbidden_response()


# ======================
# 📦 LIVRAISONS
# ======================
@bp.route("/deliveries")
def deliveries():
    now = datetime.utcnow()
    couriers = _available_couriers()
    courier_filters = _courier_filter_choices()

    def enrich_orders(orders):
        for order in orders:
            product_names = []
            shop_names = []
            for item in order.items:
                if item.product:
                    if item.product.name and item.product.name not in product_names:
                        product_names.append(item.product.name)
                    if item.product.shop and item.product.shop.name and item.product.shop.name not in shop_names:
                        shop_names.append(item.product.shop.name)
            order._product_names = product_names
            order._shop_names = shop_names
        return orders

    selection = _period_selection_from_request(default_to_open=True)
    selected_period_id = selection["selected_period_id"]
    include_legacy = selection["include_legacy"]
    read_only = selection["read_only"]
    period_base = _orders_query_for_period(
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
    )
    source_filter = _normalize_delivery_source_filter(request.args.get("source"))
    if source_filter:
        period_base = period_base.filter(Order.delivery_source == source_filter)
    delivery_scope = _normalize_courier_assignment_filter(request.args.get("delivery_scope"))
    courier_id_filter = request.args.get("courier_id", type=int)
    order_status_filter = _normalize_order_status_filter(request.args.get("order_status") or request.args.get("status"))
    delivery_status_filter = _normalize_delivery_status_filter(request.args.get("delivery_status"))
    scoped_base = _apply_courier_assignment_filter(period_base, delivery_scope)
    if courier_id_filter:
        scoped_base = scoped_base.filter(Order.courier_id == courier_id_filter)
    if order_status_filter:
        scoped_base = scoped_base.filter(Order.status == order_status_filter)
    if delivery_status_filter:
        scoped_base = scoped_base.filter(Order.delivery_status == delivery_status_filter)
    operational_base = _operational_deliveries_query(scoped_base, now=now, window_hours=24)

    pending_query = (
        operational_base.filter(Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS)))
        .options(
            selectinload(Order.courier),
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
        )
        .order_by(Order.created_at.desc())
    )
    pending = enrich_orders(pending_query.limit(25).all())

    delivered_recent_query = (
        operational_base.filter(Order.delivery_status == "delivered")
        .filter(Order.delivered_at.is_(None) | (Order.delivered_at >= (now - timedelta(hours=24))))
    )
    total_baba_fee = (
        delivered_recent_query.with_entities(
            db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)
        ).scalar() or 0
    ) / 100
    pending_count = operational_base.filter(Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS))).count()
    delivered_recent_count = delivered_recent_query.count()
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    product_filter = request.args.get("product", "")
    shop_filter = request.args.get("shop", "")
    city_filter = request.args.get("city", "")
    client_filter = request.args.get("client", "")
    phone_filter = request.args.get("phone", "")
    page = page_from_args(request.args)

    history_query = _apply_delivery_filters(
        operational_base,
        order_status_filter=order_status_filter,
        delivery_status_filter=delivery_status_filter,
        source_filter=source_filter,
        city_filter=city_filter,
        client_filter=client_filter,
        phone_filter=phone_filter,
        date_from=date_from,
        date_to=date_to,
        product_filter=product_filter,
        shop_filter=shop_filter,
    )

    history_query = history_query.options(
        selectinload(Order.courier),
        selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
    )

    pagination = history_query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=30, error_out=False
    )
    history_orders = enrich_orders(pagination.items)
    enrich_orders_delivery_context(pending)
    enrich_orders_delivery_context(history_orders)

    if request.args.get("export") == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "Date", "Statut", "Source", "Client", "Telephone", "Ville",
            "Produits", "Boutiques", "Livreur", "DeliveryStatus", "Total(MAD)",
            "Livraison(MAD)", "PartBaba(MAD)", "NetLivreur(MAD)", "RemiseBaba"
        ])

        for order in history_orders:
            writer.writerow([
                order.id,
                order.created_at.strftime("%d/%m/%Y %H:%M") if order.created_at else "",
                order.status,
                order.delivery_source or DELIVERY_SOURCE_MARKETPLACE,
                order.full_name,
                order.phone,
                order.delivery_city or order.city,
                " | ".join(order._product_names),
                " | ".join(order._shop_names),
                order.courier.username if order.courier else "",
                order.delivery_status,
                f"{(order.total or 0) / 100:.2f}",
                f"{(order.delivery_price_cents or order.shipping or 0) / 100:.2f}",
                f"{(order.delivery_platform_fee_cents or 0) / 100:.2f}",
                f"{(order.delivery_courier_net_cents or 0) / 100:.2f}",
                "remis" if order.baba_fee_settled_at else "a_remettre",
            ])

        response = current_app.response_class(
            output.getvalue(),
            mimetype="text/csv; charset=utf-8"
        )
        response.headers["Content-Disposition"] = "attachment; filename=deliveries_operational.csv"
        return response

    return render_template(
        "admin/deliveries.html",
        pending=pending,
        total_baba_fee=total_baba_fee,
        total_commission=total_baba_fee,
        pending_count=pending_count,
        delivered_recent_count=delivered_recent_count,
        pagination=pagination,
        history_orders=history_orders,
        source_filter=source_filter,
        order_status_filter=order_status_filter,
        delivery_status_filter=delivery_status_filter,
        date_from=date_from,
        date_to=date_to,
        product_filter=product_filter,
        shop_filter=shop_filter,
        city_filter=city_filter,
        client_filter=client_filter,
        phone_filter=phone_filter,
        delivery_scope=delivery_scope,
        courier_id_filter=courier_id_filter,
        couriers=couriers,
        courier_filters=courier_filters,
        available_couriers_count=_available_couriers_count(),
        cities=Order.CITIES,
        periods=selection["periods"],
        selected_period=selection["selected_period"],
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
        read_only=read_only,
        notify_url=url_for(
            "admin.orders_notifications",
            period_id=selected_period_id,
            include_legacy=1 if include_legacy else None,
            source=source_filter or None,
            delivery_scope=delivery_scope or None,
            courier_id=courier_id_filter or None,
            order_status=order_status_filter or None,
            delivery_status=delivery_status_filter or None,
        ),
    )


@bp.route("/deliver/<int:oid>", methods=["POST"])
def mark_delivered(oid):
    order = Order.query.get_or_404(oid)
    if order.period_id is not None and order.period and order.period.status == CLOSED_STATUS:
        message = "Cette commande est dans une periode fermee (archive)."
        if _is_ajax_request():
            return jsonify(success=False, message=message), 403
        flash("Cette commande est dans une periode fermee (archive).", "warning")
        return redirect(request.args.get("next") or url_for("admin.deliveries"))
    order.status = "delivered"
    order.delivery_status = "delivered"
    order.delivered_at = datetime.utcnow()
    if order.courier is not None:
        _sync_courier_availability(order.courier)
    record_delivery_fee_entry(order, note="order delivered by admin")
    db.session.commit()

    log_access(
        "update_order_status",
        "order",
        order.id,
        success=True,
        changes={"status": order.status}
    )

    if _is_ajax_request():
        return jsonify(success=True, order_id=order.id, status=order.status)


    flash(
        (
            f"Commande {oid} livree - part Baba: "
            f"{(order.delivery_platform_fee_cents or 0) / 100:.2f} MAD"
        ),
        "success",
    )
    next_url = request.args.get("next")
    if next_url and next_url.endswith("?"):
        next_url = next_url[:-1]
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("admin.deliveries"))


@bp.route("/order/<int:oid>/cancel", methods=["POST"])
def cancel_order(oid):
    order = Order.query.get_or_404(oid)
    if order.period_id is not None and order.period and order.period.status == CLOSED_STATUS:
        message = "Cette commande est dans une periode fermee (archive)."
        if _is_ajax_request():
            return jsonify(success=False, message=message), 403
        flash("Cette commande est dans une periode fermee (archive).", "warning")
        return redirect(request.args.get("next") or url_for("admin.deliveries"))
    order.status = "cancelled"
    order.delivery_status = "canceled"
    order.delivered_at = None
    order.baba_fee_settled_at = None
    order.baba_fee_settled_by_user_id = None
    if order.courier is not None:
        _sync_courier_availability(order.courier)
    FinancialEntry.query.filter(
        FinancialEntry.entry_type == ENTRY_TYPE_DELIVERY_FEE,
        FinancialEntry.order_id == order.id,
    ).delete(synchronize_session=False)
    db.session.commit()

    log_access(
        "cancel_order",
        "order",
        order.id,
        success=True,
        changes={"status": order.status}
    )

    if _is_ajax_request():
        return jsonify(success=True, order_id=order.id, status=order.status)


    flash(f"Commande {oid} annulee", "warning")
    next_url = request.args.get("next")
    if next_url and next_url.endswith("?"):
        next_url = next_url[:-1]
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("admin.all_orders"))


@bp.route("/deliveries/<int:oid>/assign", methods=["POST"])
def assign_courier(oid: int):
    order = Order.query.options(
        selectinload(Order.period),
        selectinload(Order.courier),
        selectinload(Order.assigned_by_user),
    ).get_or_404(oid)
    next_url = (request.args.get("next") or request.form.get("next") or "").strip()

    def _redirect_default():
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("admin.deliveries"))

    if order.period_id is not None and order.period and order.period.status == CLOSED_STATUS:
        message = "Cette commande est dans une periode fermee (archive)."
        if _is_ajax_request():
            return jsonify(success=False, message=message), 403
        flash(message, "warning")
        return _redirect_default()
    if order.delivery_status in COURIER_DELIVERY_COMPLETED:
        message = "Cette livraison est deja finalisee."
        if _is_ajax_request():
            return jsonify(success=False, message=message), 400
        flash(message, "warning")
        return _redirect_default()

    courier_id_raw = (request.form.get("courier_id") or "").strip()
    courier = None
    if courier_id_raw:
        try:
            courier_id = int(courier_id_raw)
        except ValueError:
            if _is_ajax_request():
                return jsonify(success=False, message="Livreur invalide."), 400
            flash("Livreur invalide.", "warning")
            return _redirect_default()
        courier = db.session.get(User, courier_id)
        if courier is None or (courier.role or "").lower() != "courier":
            if _is_ajax_request():
                return jsonify(success=False, message="Livreur introuvable."), 404
            flash("Livreur introuvable.", "warning")
            return _redirect_default()
        if not courier.is_active or not courier.courier_is_active:
            if _is_ajax_request():
                return jsonify(success=False, message="Ce livreur est inactif."), 400
            flash("Ce livreur est inactif.", "warning")
            return _redirect_default()
        if (not courier.courier_is_available) and order.courier_id != courier.id:
            if _is_ajax_request():
                return jsonify(success=False, message="Ce livreur n'est pas disponible."), 400
            flash("Ce livreur n'est pas disponible.", "warning")
            return _redirect_default()

    old_courier_id = order.courier_id
    old_courier = order.courier
    order.courier_id = courier.id if courier else None

    if courier:
        now = datetime.utcnow()
        if order.delivery_status in {"new", ""}:
            order.delivery_status = "assigned"
        order.assigned_at = now
        order.assigned_by_user_id = current_user.id if current_user.is_authenticated else None
        courier.courier_last_seen_at = now
    else:
        if order.delivery_status in {"assigned", "picked_up", "delivering"}:
            order.delivery_status = "new"
            order.picked_up_at = None
        order.assigned_by_user_id = None

    if old_courier is not None and (courier is None or old_courier.id != courier.id):
        _sync_courier_availability(old_courier)
    if courier is not None:
        _sync_courier_availability(courier)

    db.session.commit()

    message = (
        f"Livraison #{order.id} assignee a {courier.username}."
        if courier else
        f"Livraison #{order.id} desassignee."
    )
    log_access(
        "assign_courier",
        "order",
        order.id,
        success=True,
        changes={
            "old_courier_id": old_courier_id,
            "new_courier_id": order.courier_id,
            "assigned_at": order.assigned_at.isoformat() if order.assigned_at else None,
            "assigned_by_user_id": order.assigned_by_user_id,
            "delivery_status": order.delivery_status,
        },
    )

    if _is_ajax_request():
        return jsonify(
            success=True,
            message=message,
            order_id=order.id,
            courier_id=order.courier_id,
            courier_name=(courier.username if courier else ""),
            delivery_status=order.delivery_status,
        )

    flash(message, "success")
    return _redirect_default()


@bp.route("/deliveries/<int:oid>/courier-whatsapp")
def courier_whatsapp(oid: int):
    next_url = (request.args.get("next") or request.referrer or "").strip()

    def _redirect_default():
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("admin.deliveries"))

    order = (
        Order.query.options(
            selectinload(Order.courier),
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
        ).filter(Order.id == oid).first()
    )
    if order is None:
        return render_template("errors/404.html"), 404

    courier = order.courier
    courier_phone = normalize_phone_for_wa(getattr(courier, "phone", None))
    if not courier_phone:
        flash("Numero WhatsApp livreur indisponible.", "warning")
        return _redirect_default()

    message = build_courier_whatsapp_message(order)
    wa_url = f"https://wa.me/{courier_phone}?text={quote(message)}"
    return redirect(wa_url)


# ======================
# 📋 COMMANDES
# ======================
@bp.route("/orders")
def all_orders():
    page = page_from_args(request.args)
    selection = _period_selection_from_request(default_to_open=True)
    selected_period_id = selection["selected_period_id"]
    include_legacy = selection["include_legacy"]
    read_only = selection["read_only"]
    couriers = _available_couriers()
    courier_filters = _courier_filter_choices()
    source_filter = _normalize_delivery_source_filter(request.args.get("source"))
    courier_id_filter = request.args.get("courier_id", type=int)

    period_base = _orders_query_for_period(
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
    )
    if source_filter:
        period_base = period_base.filter(Order.delivery_source == source_filter)
    scoped_base = period_base.filter(Order.delivery_status == "delivered")
    if courier_id_filter:
        scoped_base = scoped_base.filter(Order.courier_id == courier_id_filter)

    pagination = scoped_base.options(
        selectinload(Order.courier),
        selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
        selectinload(Order.period),
    ).order_by(Order.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    orders = pagination.items
    enrich_orders_delivery_context(orders)
    total_baba_fee = (
        scoped_base.with_entities(
            db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)
        ).scalar() or 0
    ) / 100
    pending_count = pagination.total
    latest_order = scoped_base.order_by(Order.created_at.desc()).first()
    latest_order_id = latest_order.id if latest_order else 0

    return render_template(
        "admin/all_orders.html",
        orders=orders,
        total_baba_fee=total_baba_fee,
        total_commission=total_baba_fee,
        pagination=pagination,
        pending_count=pending_count,
        total_orders=pagination.total,
        latest_order_id=latest_order_id,
        periods=selection["periods"],
        selected_period=selection["selected_period"],
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
        source_filter=source_filter,
        delivery_scope="",
        courier_id_filter=courier_id_filter,
        order_status_filter="delivered",
        delivery_status_filter="delivered",
        couriers=couriers,
        courier_filters=courier_filters,
        read_only=read_only,
        notify_url=url_for(
            "admin.orders_notifications",
            period_id=selected_period_id,
            include_legacy=1 if include_legacy else None,
            source=source_filter or None,
            courier_id=courier_id_filter or None,
            order_status="delivered",
            delivery_status="delivered",
        ),
    )


@bp.route("/orders/notifications")
def orders_notifications():
    selection = _period_selection_from_request(default_to_open=True)
    period_base = _orders_query_for_period(
        selected_period_id=selection["selected_period_id"],
        include_legacy=selection["include_legacy"],
    )
    source_filter = _normalize_delivery_source_filter(request.args.get("source"))
    if source_filter:
        period_base = period_base.filter(Order.delivery_source == source_filter)
    courier_id_filter = request.args.get("courier_id", type=int)
    scoped_base = period_base.filter(Order.delivery_status == "delivered")
    if courier_id_filter:
        scoped_base = scoped_base.filter(Order.courier_id == courier_id_filter)
    latest_order = scoped_base.order_by(Order.created_at.desc()).first()
    latest_order_id = latest_order.id if latest_order else 0
    pending_count = scoped_base.count()
    return jsonify(
        latest_id=latest_order_id,
        pending_count=pending_count
    )


@bp.route("/orders/live")
def orders_live():
    page = page_from_args(request.args)
    selection = _period_selection_from_request(default_to_open=True)
    selected_period_id = selection["selected_period_id"]
    include_legacy = selection["include_legacy"]
    source_filter = _normalize_delivery_source_filter(request.args.get("source"))
    courier_id_filter = request.args.get("courier_id", type=int)

    period_base = _orders_query_for_period(
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
    )
    if source_filter:
        period_base = period_base.filter(Order.delivery_source == source_filter)
    scoped_base = period_base.filter(Order.delivery_status == "delivered")
    if courier_id_filter:
        scoped_base = scoped_base.filter(Order.courier_id == courier_id_filter)

    pagination = scoped_base.options(
        selectinload(Order.courier),
        selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
        selectinload(Order.period),
    ).order_by(Order.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    orders = pagination.items
    pending_count = pagination.total
    total_orders = pagination.total
    total_baba_fee = (
        scoped_base.with_entities(
            db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)
        ).scalar() or 0
    ) / 100

    def format_order(o):
        next_url = url_for(
            "admin.all_orders",
            period_id=selected_period_id,
            include_legacy=1 if include_legacy else None,
            source=source_filter or None,
            courier_id=courier_id_filter or None,
            order_status="delivered",
            delivery_status="delivered",
            page=page,
        )
        items = []
        for item in o.items:
            name = item.product.name if item.product and item.product.name else f"Produit #{item.product_id}"
            items.append({
                "name": name,
                "price": round((item.price or 0) / 100, 2),
                "qty": item.quantity or 0
            })
        return {
            "id": o.id,
            "full_name": o.full_name,
            "phone": o.phone,
            "city": o.delivery_city or o.city,
            "delivery_source": o.delivery_source or DELIVERY_SOURCE_MARKETPLACE,
            "total": round((o.total or 0) / 100, 2),
            "delivery_price": round((o.delivery_price_cents or o.shipping or 0) / 100, 2),
            "delivery_platform_fee": round((o.delivery_platform_fee_cents or 0) / 100, 2),
            "delivery_courier_net": round((o.delivery_courier_net_cents or 0) / 100, 2),
            "baba_fee_settled": bool(o.baba_fee_settled_at),
            "items": items,
            "status": o.status,
            "delivery_status": o.delivery_status,
            "courier_id": o.courier_id,
            "courier_name": o.courier.username if o.courier else "",
            "created_at": o.created_at.strftime("%d/%m/%Y %H:%M") if o.created_at else "",
            "detail_url": url_for("admin.order_detail", oid=o.id, next=next_url),
            "deliver_url": url_for("admin.mark_delivered", oid=o.id, next=next_url),
            "cancel_url": url_for("admin.cancel_order", oid=o.id, next=next_url),
            "assign_url": url_for("admin.assign_courier", oid=o.id, next=next_url),
            "call_url": f"tel:{o.phone}"
        }

    return jsonify(
        pending_count=pending_count,
        total_orders=total_orders,
        total_baba_fee=round(total_baba_fee, 2),
        total_commission=round(total_baba_fee, 2),
        read_only=selection["read_only"],
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
        source_filter=source_filter,
        delivery_scope="",
        courier_id_filter=courier_id_filter,
        order_status_filter="delivered",
        delivery_status_filter="delivered",
        orders=[format_order(o) for o in orders]
    )


@bp.route("/orders/archives")
def order_archives():
    archives_page = page_from_args(request.args, key="page", default=1)
    period_id = request.args.get("period_id", type=int)
    return redirect(
        url_for(
            "admin.pricing_settings",
            section="archives",
            archive_period_id=period_id or None,
            archives_page=archives_page if archives_page > 1 else None,
        )
    )


@bp.route("/order-periods")
def order_periods():
    return redirect(url_for("admin.pricing_settings", section="periods"))


@bp.route("/order-periods/create", methods=["POST"])
def order_period_create():
    name = (request.form.get("name") or "").strip()
    try:
        period = create_order_period(
            name=name or None,
            created_by=current_user.id if current_user.is_authenticated else None,
        )
        ensure_financial_period_for_order_period(period, create_if_missing=True)
        db.session.commit()
        log_access(
            "create_order_period",
            "order_period",
            period.id,
            success=True,
            changes={"name": period.name, "status": period.status},
        )
        flash(f"Periode creee: {period.name}", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec creation periode: {exc}", "danger")
    return redirect(url_for("admin.pricing_settings", section="periods"))


@bp.route("/order-periods/<int:period_id>/close", methods=["POST"])
def order_period_close(period_id: int):
    period = db.session.get(OrderPeriod, period_id)
    if period is None:
        return render_template("errors/404.html"), 404
    if period.status == CLOSED_STATUS:
        flash("Cette periode est deja fermee.", "info")
        return redirect(url_for("admin.pricing_settings", section="periods"))

    try:
        close_order_period(period)
        linked_financial_period = ensure_financial_period_for_order_period(period, create_if_missing=True)
        db.session.commit()
        log_access(
            "close_order_period",
            "order_period",
            period.id,
            success=True,
            changes={
                "closed_at": period.closed_at.isoformat() if period.closed_at else None,
                "financial_period_id": getattr(linked_financial_period, "id", None),
            },
        )
        flash(f"Periode fermee: {period.name}", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec fermeture periode: {exc}", "danger")
    return redirect(url_for("admin.pricing_settings", section="periods"))


@bp.route("/financial-periods")
@bp.route("/finance")
def finance():
    page = page_from_args(request.args)
    requested_period_id = request.args.get("period_id", type=int)
    entry_type = (request.args.get("entry_type") or "").strip().lower()
    if entry_type not in {ENTRY_TYPE_DELIVERY_FEE, ENTRY_TYPE_SUBSCRIPTION, ENTRY_TYPE_RENTAL_COMMISSION}:
        entry_type = ""

    date_from_raw = (request.args.get("date_from") or request.args.get("from") or "").strip()
    date_to_raw = (request.args.get("date_to") or request.args.get("to") or "").strip()
    date_from = _parse_iso_date(date_from_raw)
    date_to = _parse_iso_date(date_to_raw)

    periods = _order_period_choices()
    open_period = next((period for period in periods if period.status == OPEN_STATUS), None)

    selected_period = None
    if requested_period_id is not None:
        selected_period = next((period for period in periods if period.id == requested_period_id), None)

    if selected_period is None and open_period is not None:
        selected_period = open_period
    elif selected_period is None and periods:
        selected_period = periods[0]

    selected_period_id = selected_period.id if selected_period else None

    # ✅ CORRECTION : période_stats calculé par SQL au lieu de charger tout en mémoire
    period_stats = {
        int(period.id): {
            "delivery_total_cents": 0,
            "subscription_total_cents": 0,
            "rental_total_cents": 0,
            "total_cents": 0,
            "entry_count": 0,
            "delivery_count": 0,
            "subscription_count": 0,
            "rental_count": 0,
        }
        for period in periods
    }

    if periods:
        try:
            from sqlalchemy import case as sa_case, func

            rows = (
                db.session.query(
                    FinancialEntry.entry_type,
                    func.count(FinancialEntry.id).label("cnt"),
                    func.coalesce(func.sum(FinancialEntry.amount_cents), 0).label("total"),
                )
                .filter(FinancialEntry.deleted_at.is_(None))
                .group_by(FinancialEntry.entry_type)
                .all()
            )
            # Totaux globaux (toutes périodes confondues) par type
            global_by_type = {row.entry_type: {"cnt": int(row.cnt), "total": int(row.total)} for row in rows}

            # Pour chaque période, on fait une requête SQL ciblée
            for period in periods:
                start_at, end_at = period_bounds(period)
                if start_at is None:
                    continue
                stats = period_stats.get(int(period.id))
                if not stats:
                    continue

                q = (
                    db.session.query(
                        FinancialEntry.entry_type,
                        func.count(FinancialEntry.id).label("cnt"),
                        func.coalesce(func.sum(FinancialEntry.amount_cents), 0).label("total"),
                    )
                    .filter(
                        FinancialEntry.deleted_at.is_(None),
                        FinancialEntry.created_at >= start_at,
                    )
                )
                if end_at is not None:
                    q = q.filter(FinancialEntry.created_at < end_at)

                period_rows = q.group_by(FinancialEntry.entry_type).all()

                for row in period_rows:
                    cnt = int(row.cnt or 0)
                    total = int(row.total or 0)
                    stats["entry_count"] += cnt
                    if row.entry_type == ENTRY_TYPE_DELIVERY_FEE:
                        stats["delivery_total_cents"] = total
                        stats["delivery_count"] = cnt
                    elif row.entry_type == ENTRY_TYPE_SUBSCRIPTION:
                        stats["subscription_total_cents"] = total
                        stats["subscription_count"] = cnt
                    elif row.entry_type == ENTRY_TYPE_RENTAL_COMMISSION:
                        stats["rental_total_cents"] = total
                        stats["rental_count"] = cnt

                stats["total_cents"] = (
                    stats["delivery_total_cents"]
                    + stats["subscription_total_cents"]
                    + stats["rental_total_cents"]
                )

        except Exception:
            # ✅ Fallback : si la requête SQL échoue, la page reste affichable
            # avec des zéros plutôt que de planter
            current_app.logger.exception("finance.period_stats_error")

    # --- Tout ce qui suit est IDENTIQUE à l'original ---

    selected_totals = {
        "delivery_total_cents": 0,
        "subscription_total_cents": 0,
        "rental_total_cents": 0,
        "total_cents": 0,
        "delivery_count": 0,
        "subscription_count": 0,
        "rental_count": 0,
        "entry_count": 0,
    }
    if selected_period is not None:
        selected_totals = dict(period_stats.get(int(selected_period.id), selected_totals))

    entries_query = (
        FinancialEntry.query
        .options(
            selectinload(FinancialEntry.order),
            selectinload(FinancialEntry.rental_archive),
            selectinload(FinancialEntry.subscription_payment),
            selectinload(FinancialEntry.courier),
        )
        .filter(FinancialEntry.deleted_at.is_(None))
    )
    if selected_period is not None:
        start_at, end_at = period_bounds(selected_period)
        if start_at is not None:
            entries_query = entries_query.filter(FinancialEntry.created_at >= start_at)
        if end_at is not None:
            entries_query = entries_query.filter(FinancialEntry.created_at < end_at)
    else:
        entries_query = entries_query.filter(FinancialEntry.id == -1)

    if entry_type:
        entries_query = entries_query.filter(FinancialEntry.entry_type == entry_type)
    if date_from is not None:
        entries_query = entries_query.filter(
            FinancialEntry.created_at >= datetime.combine(date_from, datetime.min.time())
        )
    if date_to is not None:
        entries_query = entries_query.filter(
            FinancialEntry.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        )

    entries_pagination = entries_query.order_by(
        FinancialEntry.created_at.desc(),
        FinancialEntry.id.desc(),
    ).paginate(page=page, per_page=50, error_out=False)

    unassigned_row = (
        db.session.query(
            db.func.coalesce(db.func.sum(FinancialEntry.amount_cents), 0).label("amount"),
            db.func.count(FinancialEntry.id).label("count"),
        )
        .filter(
            FinancialEntry.deleted_at.is_(None),
            FinancialEntry.period_id.is_(None),
        )
        .first()
    )
    unassigned_total_cents = int((unassigned_row.amount if unassigned_row else 0) or 0)
    unassigned_count = int((unassigned_row.count if unassigned_row else 0) or 0)

    delete_allowed = False
    delete_message = "La finance suit maintenant la periode globale admin. Ouvrez, fermez et archivez depuis Periodes commandes."
    delete_available_at = None

    entry_type_labels = {
        ENTRY_TYPE_DELIVERY_FEE: "Livraison (Part Baba)",
        ENTRY_TYPE_SUBSCRIPTION: "Abonnement",
        ENTRY_TYPE_RENTAL_COMMISSION: "Location (commission)",
    }

    return render_template(
        "admin/finance.html",
        periods=periods,
        open_period=open_period,
        selected_period=selected_period,
        selected_period_id=selected_period_id,
        period_stats=period_stats,
        selected_totals=selected_totals,
        entries=entries_pagination.items,
        entries_pagination=entries_pagination,
        entry_type=entry_type,
        date_from=date_from_raw,
        date_to=date_to_raw,
        unassigned_total_cents=unassigned_total_cents,
        unassigned_count=unassigned_count,
        delete_allowed=delete_allowed,
        delete_message=delete_message,
        delete_available_at=delete_available_at,
        entry_type_labels=entry_type_labels,
        retention_days=ORDER_DELETE_RETENTION_DAYS,
    )

@bp.route("/finance/periods/open", methods=["POST"])
def finance_period_open():
    flash("La finance suit la periode globale admin. Ouvrez une periode depuis Periodes commandes.", "info")
    return redirect(url_for("admin.pricing_settings", section="periods"))


@bp.route("/finance/periods/<int:period_id>/close", methods=["POST"])
def finance_period_close(period_id: int):
    flash("La finance suit la periode globale admin. Fermez la periode depuis Periodes commandes.", "info")
    return redirect(url_for("admin.pricing_settings", section="periods"))


@bp.route("/finance/periods/<int:period_id>/delete", methods=["POST"])
def finance_period_delete(period_id: int):
    flash("La finance n'a plus de suppression separee. Gere la periode globale depuis Periodes commandes.", "info")
    return redirect(url_for("admin.pricing_settings", section="periods"))


@bp.route("/orders/<int:oid>/delete", methods=["POST"])
def delete_archived_order(oid: int):
    next_url = (request.args.get("next") or request.form.get("next") or "").strip()

    def _redirect_after_delete(default_endpoint: str = "admin.pricing_settings"):
        if next_url.startswith("/"):
            return redirect(next_url)
        if default_endpoint == "admin.pricing_settings":
            return redirect(url_for(default_endpoint, section="archives"))
        return redirect(url_for(default_endpoint))

    order = (
        Order.query
        .options(selectinload(Order.period))
        .filter(Order.id == oid)
        .first()
    )
    if order is None:
        return render_template("errors/404.html"), 404
    allowed, message, available_at = order_delete_guard(order)
    if not allowed:
        if not message and available_at:
            message = f"Suppression possible a partir du {available_at.strftime('%d/%m/%Y %H:%M')}."
        flash(message or "Suppression refusee.", "warning")
        return _redirect_after_delete()

    if (order.status or "").lower() not in FINAL_DELIVERY_ORDER_STATUSES:
        flash(
            f"Suppression refusee: livraison non finalisee (statut {order.status}).",
            "warning",
        )
        return _redirect_after_delete()

    try:
        VendorPayout.query.filter_by(order_id=order.id).delete(synchronize_session=False)
        VendorReceipt.query.filter_by(order_id=order.id).delete(synchronize_session=False)
        VendorFulfillment.query.filter_by(order_id=order.id).delete(synchronize_session=False)
        db.session.delete(order)
        db.session.commit()
        log_access(
            "delete_archived_order",
            "order",
            oid,
            success=True,
            changes={"period_id": order.period_id},
        )
        flash(f"Commande #{oid} supprimee definitivement.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec suppression commande #{oid}: {exc}", "danger")

    return _redirect_after_delete()


@bp.route("/deliveries/live")
def deliveries_live():
    now = datetime.utcnow()
    selection = _period_selection_from_request(default_to_open=True)
    selected_period_id = selection["selected_period_id"]
    include_legacy = selection["include_legacy"]
    read_only = selection["read_only"]
    source_filter = _normalize_delivery_source_filter(request.args.get("source"))
    delivery_scope = _normalize_courier_assignment_filter(request.args.get("delivery_scope"))
    courier_id_filter = request.args.get("courier_id", type=int)
    order_status_filter = _normalize_order_status_filter(request.args.get("order_status") or request.args.get("status"))
    delivery_status_filter = _normalize_delivery_status_filter(request.args.get("delivery_status"))
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    product_filter = request.args.get("product", "")
    shop_filter = request.args.get("shop", "")
    city_filter = request.args.get("city", "")
    client_filter = request.args.get("client", "")
    phone_filter = request.args.get("phone", "")
    page = page_from_args(request.args)

    def list_products_shops(order):
        product_names = []
        shop_names = []
        for item in order.items:
            if item.product:
                if item.product.name and item.product.name not in product_names:
                    product_names.append(item.product.name)
                if item.product.shop and item.product.shop.name and item.product.shop.name not in shop_names:
                    shop_names.append(item.product.shop.name)
        return product_names, shop_names

    period_base = _orders_query_for_period(
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
    )
    if source_filter:
        period_base = period_base.filter(Order.delivery_source == source_filter)
    scoped_base = _apply_courier_assignment_filter(period_base, delivery_scope)
    if courier_id_filter:
        scoped_base = scoped_base.filter(Order.courier_id == courier_id_filter)
    if order_status_filter:
        scoped_base = scoped_base.filter(Order.status == order_status_filter)
    if delivery_status_filter:
        scoped_base = scoped_base.filter(Order.delivery_status == delivery_status_filter)
    operational_base = _operational_deliveries_query(scoped_base, now=now, window_hours=24)

    pending_query = (
        operational_base.filter(Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS)))
        .options(
            selectinload(Order.courier),
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
        )
        .order_by(Order.created_at.desc())
    )
    pending_orders = pending_query.limit(25).all()

    delivered_recent_query = (
        operational_base.filter(Order.delivery_status == "delivered")
        .filter(Order.delivered_at.is_(None) | (Order.delivered_at >= (now - timedelta(hours=24))))
    )
    delivered_recent_count = delivered_recent_query.count()
    total_baba_fee = (
        delivered_recent_query.with_entities(
            db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)
        ).scalar() or 0
    ) / 100

    history_query = _apply_delivery_filters(
        operational_base,
        order_status_filter=order_status_filter,
        delivery_status_filter=delivery_status_filter,
        source_filter=source_filter,
        city_filter=city_filter,
        client_filter=client_filter,
        phone_filter=phone_filter,
        date_from=date_from,
        date_to=date_to,
        product_filter=product_filter,
        shop_filter=shop_filter,
    )

    history_query = history_query.options(
        selectinload(Order.courier),
        selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
    )

    pagination = history_query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=30, error_out=False
    )

    def to_json(order):
        product_names, shop_names = list_products_shops(order)
        can_mutate = (not read_only) and (order.delivery_status in COURIER_DELIVERY_IN_PROGRESS)
        next_params = {
            "period_id": selected_period_id,
            "include_legacy": 1 if include_legacy else None,
            "source": source_filter or None,
            "delivery_scope": delivery_scope or None,
            "courier_id": courier_id_filter or None,
            "order_status": order_status_filter or None,
            "delivery_status": delivery_status_filter or None,
            "from": date_from or None,
            "to": date_to or None,
            "product": product_filter or None,
            "shop": shop_filter or None,
            "city": city_filter or None,
            "client": client_filter or None,
            "phone": phone_filter or None,
            "page": page,
        }
        next_url = url_for(
            "admin.deliveries",
            **next_params,
        )
        return {
            "id": order.id,
            "full_name": order.full_name,
            "phone": order.phone,
            "city": order.delivery_city or order.city,
            "delivery_source": order.delivery_source or DELIVERY_SOURCE_MARKETPLACE,
            "total": round((order.total or 0) / 100, 2),
            "delivery_price": round((order.delivery_price_cents or order.shipping or 0) / 100, 2),
            "delivery_platform_fee": round((order.delivery_platform_fee_cents or 0) / 100, 2),
            "delivery_courier_net": round((order.delivery_courier_net_cents or 0) / 100, 2),
            "baba_fee_settled": bool(order.baba_fee_settled_at),
            "status": order.status,
            "delivery_status": order.delivery_status,
            "courier_id": order.courier_id,
            "courier_name": order.courier.username if order.courier else "",
            "can_mutate": can_mutate,
            "created_at": order.created_at.strftime("%d/%m/%Y %H:%M") if order.created_at else "",
            "product_names": product_names,
            "shop_names": shop_names,
            "detail_url": url_for("admin.order_detail", oid=order.id, next=next_url),
            "deliver_url": url_for("admin.mark_delivered", oid=order.id, next=next_url),
            "cancel_url": url_for("admin.cancel_order", oid=order.id, next=next_url),
            "assign_url": url_for("admin.assign_courier", oid=order.id, next=next_url),
            "call_url": f"tel:{order.phone}"
        }

    return jsonify(
        pending_count=operational_base.filter(Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS))).count(),
        delivered_recent_count=delivered_recent_count,
        total_baba_fee=round(total_baba_fee, 2),
        total_commission=round(total_baba_fee, 2),
        available_couriers_count=_available_couriers_count(),
        read_only=read_only,
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
        source_filter=source_filter,
        delivery_scope=delivery_scope,
        courier_id_filter=courier_id_filter,
        order_status_filter=order_status_filter,
        delivery_status_filter=delivery_status_filter,
        history_total=pagination.total,
        page=pagination.page,
        pages=pagination.pages,
        pending_orders=[to_json(o) for o in pending_orders],
        history_orders=[to_json(o) for o in pagination.items]
    )


@bp.route("/deliveries/available-count")
def deliveries_available_count():
    return jsonify(available_couriers_count=_available_couriers_count())


@bp.route("/deliveries/archives")
def deliveries_archives():
    def enrich_orders(orders):
        for order in orders:
            product_names = []
            shop_names = []
            for item in order.items:
                if item.product:
                    if item.product.name and item.product.name not in product_names:
                        product_names.append(item.product.name)
                    if item.product.shop and item.product.shop.name and item.product.shop.name not in shop_names:
                        shop_names.append(item.product.shop.name)
            order._product_names = product_names
            order._shop_names = shop_names
        return orders

    status_filter = request.args.get("status", "")
    source_filter = _normalize_delivery_source_filter(request.args.get("source"))
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    product_filter = request.args.get("product", "")
    shop_filter = request.args.get("shop", "")
    city_filter = request.args.get("city", "")
    client_filter = request.args.get("client", "")
    phone_filter = request.args.get("phone", "")
    period_id = request.args.get("period_id", type=int)
    page = page_from_args(request.args)

    try:
        base_archived = _archived_orders_query()
        if period_id:
            base_archived = base_archived.filter(Order.period_id == period_id)
        if source_filter:
            base_archived = base_archived.filter(Order.delivery_source == source_filter)

        history_query = _apply_delivery_filters(
            base_archived,
            order_status_filter=status_filter,  # ✅ CORRECTION : était status_filter=
            source_filter=source_filter,
            city_filter=city_filter,
            client_filter=client_filter,
            phone_filter=phone_filter,
            date_from=date_from,
            date_to=date_to,
            product_filter=product_filter,
            shop_filter=shop_filter,
        ).options(
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
            selectinload(Order.period),
        )

        pagination = history_query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=30, error_out=False
        )
        history_orders = enrich_orders(pagination.items)
        enrich_orders_delivery_context(history_orders)

        closed_periods = (
            OrderPeriod.query
            .filter(OrderPeriod.status == CLOSED_STATUS)
            .order_by(OrderPeriod.closed_at.desc(), OrderPeriod.id.desc())
            .all()
        )

        now = datetime.utcnow()
        delete_guards = {}
        for order in history_orders:
            allowed, message, available_at = order_delete_guard(order, now=now)
            if allowed and (order.status or "").lower() not in FINAL_DELIVERY_ORDER_STATUSES:
                allowed = False
                message = f"Suppression refusee: livraison non finalisee (statut {order.status})."
            delete_guards[order.id] = {
                "allowed": allowed,
                "message": message,
                "available_at": available_at,
            }

    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "deliveries_archives.db_error — period_id=%s source=%s page=%s",
            period_id, source_filter, page,
        )
        flash("Erreur lors du chargement des archives. Merci de réessayer.", "danger")
        return redirect(url_for("admin.deliveries"))

    except Exception:
        current_app.logger.exception(
            "deliveries_archives.unexpected_error — period_id=%s source=%s page=%s",
            period_id, source_filter, page,
        )
        flash("Une erreur inattendue s'est produite.", "danger")
        return redirect(url_for("admin.deliveries"))

    return render_template(
        "admin/deliveries_archives.html",
        pagination=pagination,
        history_orders=history_orders,
        source_filter=source_filter,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        product_filter=product_filter,
        shop_filter=shop_filter,
        city_filter=city_filter,
        client_filter=client_filter,
        phone_filter=phone_filter,
        cities=Order.CITIES,
        period_id=period_id,
        closed_periods=closed_periods,
        delete_guards=delete_guards,
    )


@bp.route("/order/<int:oid>")
def order_detail(oid):
    order = Order.query.options(
        selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
        selectinload(Order.period),
        selectinload(Order.courier),
        selectinload(Order.assigned_by_user),
    ).get_or_404(oid)
    enrich_order_delivery_context(order)
    payouts = (
        VendorPayout.query
        .filter_by(order_id=order.id)
        .options(
            selectinload(VendorPayout.shop),
            selectinload(VendorPayout.vendor)
        )
        .order_by(VendorPayout.id.asc())
        .all()
    )
    log_access("view_order", "order", order.id, success=True)
    return render_template("admin/order_detail.html", order=order, payouts=payouts)


# ======================
# 💰 COMMISSIONS
# ======================



# ======================
# PARAMETRES PLATEFORME
# ======================
@bp.route("/pricing", methods=["GET", "POST"])
def pricing_settings():
    settings = PlatformSettings.get()
    archives_context = _archived_orders_context()
    periods_context = _order_periods_context()

    if request.method == "POST":
        def _to_float(field_name: str, default_value: float = 0.0) -> float:
            raw = (request.form.get(field_name, "") or "").strip().replace(",", ".")
            if raw == "":
                return float(default_value)
            return float(raw)

        try:
            settings.shipping_kenitra = int(
                round(max(0.0, _to_float("shipping_kenitra", settings.shipping_kenitra / 100)) * 100)
            )
            settings.shipping_temara = int(
                round(max(0.0, _to_float("shipping_temara", settings.shipping_temara / 100)) * 100)
            )
            settings.shipping_rabat = int(
                round(max(0.0, _to_float("shipping_rabat", settings.shipping_rabat / 100)) * 100)
            )
            settings.shipping_sale = int(
                round(max(0.0, _to_float("shipping_sale", settings.shipping_sale / 100)) * 100)
            )
            settings.delivery_platform_fee_fixed_cents = int(
                round(
                    max(
                        0.0,
                        _to_float(
                            "delivery_platform_fee_fixed_dh",
                            (settings.delivery_platform_fee_fixed_cents or 0) / 100,
                        ),
                    ) * 100
                )
            )
            settings.low_stock_threshold = max(
                0,
                int(_to_float("low_stock_threshold", settings.low_stock_threshold)),
            )

            rental_rate_percent = max(
                0.0,
                min(100.0, _to_float("rental_success_commission_percent", settings.rental_success_commission_bps / 100)),
            )
            rental_rate_bps = int(round(rental_rate_percent * 100))
            settings.rental_success_commission_bps = rental_rate_bps
            settings.rental_success_commission_fixed_cents = 0
            settings.rental_success_commission_mode = "percent"
        except ValueError:
            flash("Valeurs invalides. Vérifiez les nombres saisis.", "warning")
            return render_template("admin/pricing.html", settings=settings, **archives_context, **periods_context)

        db.session.commit()
        log_access(
            "update_pricing",
            "platform_settings",
            settings.id,
            success=True,
            changes={
                "shipping_kenitra": settings.shipping_kenitra,
                "shipping_temara": settings.shipping_temara,
                "shipping_rabat": settings.shipping_rabat,
                "shipping_sale": settings.shipping_sale,
                "delivery_platform_fee_fixed_cents": settings.delivery_platform_fee_fixed_cents,
                "low_stock_threshold": settings.low_stock_threshold,
                "rental_success_commission_bps": settings.rental_success_commission_bps,
                "rental_success_commission_percent": round(settings.rental_success_commission_bps / 100, 2),
            }
        )
        flash("Paramètres mis à jour", "success")

    return render_template("admin/pricing.html", settings=settings, **archives_context, **periods_context)


@bp.route("/highlights", methods=["GET"])
def featured_items():
    context = _build_featured_items_context()
    if _is_ajax_request() and request.headers.get("X-Highlights-Partial") == "1":
        return jsonify(
            success=True,
            html=render_template("admin/partials/_highlights_content.html", **context),
            url=_featured_items_url_from_context(context),
        )
    return render_template("admin/highlights.html", **context)


@bp.route("/highlights/activate", methods=["POST"])
def featured_items_activate():
    target_type = (request.form.get("target_type") or "").strip().lower()
    target_id = request.form.get("target_id", type=int)
    duration_days = normalize_featured_duration(request.form.get("duration_days"))
    note = (request.form.get("note") or "").strip()

    if target_type not in FeaturedItem.TARGET_TYPES or not target_id:
        if _is_ajax_request():
            return jsonify(success=False, message="Selection invalide pour la mise en avant."), 400
        flash("Selection invalide pour la mise en avant.", "warning")
        return redirect(url_for("admin.featured_items"))

    vendor_id = None
    if target_type == FeaturedItem.TARGET_SHOP:
        target = db.session.get(Shop, target_id)
        vendor_id = getattr(target, "vendor_id", None)
    elif target_type == FeaturedItem.TARGET_PRODUCT:
        target = db.session.get(Product, target_id)
        vendor_id = getattr(target, "vendor_id", None)
    else:
        target = db.session.get(RentalListing, target_id)
        vendor_id = getattr(target, "owner_id", None)

    if target is None:
        if _is_ajax_request():
            return jsonify(success=False, message="Element introuvable."), 404
        flash("Element introuvable.", "warning")
        return redirect(url_for("admin.featured_items"))

    try:
        upsert_featured_item(
            target_type=target_type,
            target_id=target_id,
            vendor_id=vendor_id,
            created_by_admin_id=getattr(current_user, "id", None),
            duration_days=duration_days,
            note=note,
        )
        db.session.commit()
        bump_catalog_version()
        if _is_ajax_request():
            context = _build_featured_items_context(request.form)
            return jsonify(
                success=True,
                message="Mise en avant activee.",
                message_type="success",
                html=render_template("admin/partials/_highlights_content.html", **context),
                url=_featured_items_url_from_context(context),
            )
        flash("Mise en avant activee.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "admin.featured_items.activate_failed",
            extra={"target_type": target_type, "target_id": target_id},
        )
        if _is_ajax_request():
            return jsonify(success=False, message="Impossible d'activer la mise en avant."), 500
        flash("Impossible d'activer la mise en avant.", "danger")

    return redirect(url_for("admin.featured_items"))


@bp.route("/highlights/<int:item_id>/disable", methods=["POST"])
def featured_items_disable(item_id: int):
    item = db.session.get(FeaturedItem, item_id)
    if item is None:
        if _is_ajax_request():
            return jsonify(success=False, message="Mise en avant introuvable."), 404
        flash("Mise en avant introuvable.", "warning")
        return redirect(url_for("admin.featured_items"))

    try:
        disable_featured_item(item)
        db.session.commit()
        bump_catalog_version()
        if _is_ajax_request():
            context = _build_featured_items_context(request.form)
            return jsonify(
                success=True,
                message="Mise en avant arretee.",
                message_type="success",
                html=render_template("admin/partials/_highlights_content.html", **context),
                url=_featured_items_url_from_context(context),
            )
        flash("Mise en avant arretee.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "admin.featured_items.disable_failed",
            extra={"item_id": item_id},
        )
        if _is_ajax_request():
            return jsonify(success=False, message="Impossible d'arreter cette mise en avant."), 500
        flash("Impossible d'arreter cette mise en avant.", "danger")

    return redirect(url_for("admin.featured_items"))


@bp.route("/highlights/<int:item_id>/extend", methods=["POST"])
def featured_items_extend(item_id: int):
    item = db.session.get(FeaturedItem, item_id)
    if item is None:
        if _is_ajax_request():
            return jsonify(success=False, message="Mise en avant introuvable."), 404
        flash("Mise en avant introuvable.", "warning")
        return redirect(url_for("admin.featured_items"))

    extra_days = normalize_featured_duration(request.form.get("duration_days"))
    now = datetime.utcnow()
    base_end = item.ends_at if item.ends_at and item.ends_at > now else now
    item.is_active = True
    item.starts_at = item.starts_at if item.starts_at and item.starts_at <= now else now
    item.ends_at = base_end + timedelta(days=extra_days)

    try:
        db.session.commit()
        bump_catalog_version()
        if _is_ajax_request():
            context = _build_featured_items_context(request.form)
            return jsonify(
                success=True,
                message="Mise en avant prolongee.",
                message_type="success",
                html=render_template("admin/partials/_highlights_content.html", **context),
                url=_featured_items_url_from_context(context),
            )
        flash("Mise en avant prolongee.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "admin.featured_items.extend_failed",
            extra={"item_id": item_id, "extra_days": extra_days},
        )
        if _is_ajax_request():
            return jsonify(success=False, message="Impossible de prolonger cette mise en avant."), 500
        flash("Impossible de prolonger cette mise en avant.", "danger")

    return redirect(url_for("admin.featured_items"))


@bp.route("/highlights/cleanup-duplicates", methods=["POST"])
def featured_items_cleanup_duplicates():
    now = datetime.utcnow()
    ordered_items = (
        FeaturedItem.query
        .order_by(
            FeaturedItem.is_active.desc(),
            FeaturedItem.ends_at.desc(),
            FeaturedItem.created_at.desc(),
            FeaturedItem.id.desc(),
        )
        .all()
    )
    seen_targets = set()
    cleaned_count = 0

    try:
        for item in ordered_items:
            target_key = (item.target_type, item.target_id)
            if target_key in seen_targets:
                if item.is_active:
                    item.is_active = False
                    if item.ends_at > now:
                        item.ends_at = now
                    item.updated_at = now
                    cleaned_count += 1
                continue
            seen_targets.add(target_key)

        if cleaned_count:
            db.session.commit()
            bump_catalog_version()
        else:
            db.session.rollback()

        if _is_ajax_request():
            context = _build_featured_items_context(request.form)
            return jsonify(
                success=True,
                message=f"{cleaned_count} doublon(s) ranges dans l'historique.",
                message_type="success",
                html=render_template("admin/partials/_highlights_content.html", **context),
                url=_featured_items_url_from_context(context),
            )
        flash(f"{cleaned_count} doublon(s) ranges dans l'historique.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("admin.featured_items.cleanup_duplicates_failed")
        if _is_ajax_request():
            return jsonify(success=False, message="Impossible de nettoyer les doublons."), 500
        flash("Impossible de nettoyer les doublons.", "danger")

    return redirect(url_for("admin.featured_items"))


@bp.route("/highlights/<int:item_id>/delete", methods=["POST"])
def featured_items_delete(item_id: int):
    item = db.session.get(FeaturedItem, item_id)
    if item is None:
        if _is_ajax_request():
            return jsonify(success=False, message="Element introuvable."), 404
        flash("Element introuvable.", "warning")
        return redirect(url_for("admin.featured_items", view="history"))

    can_delete_after = item.created_at + timedelta(days=30)
    if can_delete_after > datetime.utcnow():
        if _is_ajax_request():
            return jsonify(
                success=False,
                message=f"Suppression possible a partir du {can_delete_after.strftime('%d/%m/%Y')}.",
            ), 400
        flash(f"Suppression possible a partir du {can_delete_after.strftime('%d/%m/%Y')}.", "warning")
        return redirect(url_for("admin.featured_items", view="history"))

    try:
        db.session.delete(item)
        db.session.commit()
        if _is_ajax_request():
            context = _build_featured_items_context(request.form)
            return jsonify(
                success=True,
                message="Element supprime de l'historique.",
                message_type="success",
                html=render_template("admin/partials/_highlights_content.html", **context),
                url=_featured_items_url_from_context(context),
            )
        flash("Element supprime de l'historique.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("admin.featured_items.delete_failed", extra={"item_id": item_id})
        if _is_ajax_request():
            return jsonify(success=False, message="Impossible de supprimer cet historique."), 500
        flash("Impossible de supprimer cet historique.", "danger")

    return redirect(url_for("admin.featured_items", view="history"))


# ======================
# MAINTENANCE SYSTEME
# ======================
from datetime import datetime, timedelta
from ..models.maintenance import MaintenanceRun  # ← Import à ajouter en haut

@bp.route("/maintenance", methods=["GET"])
def maintenance():
    days = _parse_days(request.args.get("days"), default=6, minimum=1, maximum=365)
    errors_page = page_from_args(request.args, key="errors_page", default=1)
    runtime_context = _maintenance_runtime_context()

    if runtime_context.get("maintenance_panel_locked"):
        hidden_health = _maintenance_health_placeholder(
            days,
            note="Déverrouillage requis pour afficher les métriques maintenance.",
        )
        context = {
            "health": hidden_health,
            "health_badges": _maintenance_badges(hidden_health),
            "days": days,
            "report": None,
            "report_cleanup": None,
            "last_run": None,
            "last_quick_run": None,
            "last_full_run": None,
            "last_run_label": "Déverrouillage requis",
            "live_traffic": {"available": False},
            "errors_block": {
                "available": False,
                "window_days": ERROR_LOG_RETENTION_DAYS_DEFAULT,
                "total_500_last_24h": "Masqué",
                "items": [],
                "page": errors_page,
                "per_page": 20,
                "pagination": None,
                "note": "Déverrouillage requis pour consulter le journal 500.",
            },
            "reset_result": None,
        }
    else:
        context = _maintenance_view_context(days=days, errors_page=errors_page)

    context.update(runtime_context)
    return render_template("admin/maintenance.html", **context)


@bp.route("/maintenance/unlock", methods=["POST"])
def maintenance_unlock():
    if not _maintenance_panel_enabled():
        return redirect(url_for("admin.maintenance"))

    password = (request.form.get("maintenance_password") or "").strip()
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    errors_page = page_from_args(request.form, key="errors_page", default=1)
    password_hash = _maintenance_panel_password_hash()

    if not password_hash or not password or not check_password_hash(password_hash, password):
        flash("Mot de passe maintenance invalide.", "danger")
        return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))

    unlock_until = _set_maintenance_panel_unlock()
    flash(
        f"Page maintenance déverrouillée pour {_maintenance_panel_unlock_minutes()} minutes, jusqu'à {format_maintenance_datetime(unlock_until)}.",
        "success",
    )
    return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))

@bp.route("/maintenance/errors/<int:error_id>/delete", methods=["POST"])
def maintenance_error_delete(error_id: int):
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    errors_page = page_from_args(request.form, key="errors_page", default=1)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days, errors_page=errors_page)
    error_log = db.session.get(ErrorLog, error_id)
    if error_log is None:
        flash("Erreur introuvable ou deja supprimee.", "warning")
        return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))

    try:
        db.session.delete(error_log)
        db.session.commit()
        flash(f"Erreur #{error_id} supprimee.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec suppression erreur #{error_id}: {exc}", "danger")
    return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))


@bp.route("/maintenance/errors/purge", methods=["POST"])
def maintenance_errors_purge():
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    errors_page = page_from_args(request.form, key="errors_page", default=1)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days, errors_page=errors_page)
    try:
        since = datetime.utcnow() - timedelta(days=ERROR_LOG_RETENTION_DAYS_DEFAULT)
        purged = (
            ErrorLog.query
            .filter(ErrorLog.status_code == 500, ErrorLog.created_at >= since)
            .delete(synchronize_session=False)
        )
        db.session.commit()
        flash(f"Erreurs 500 ({ERROR_LOG_RETENTION_DAYS_DEFAULT} jours) supprimees: {int(purged or 0)}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec purge erreurs 500 ({ERROR_LOG_RETENTION_DAYS_DEFAULT} jours): {exc}", "danger")
    return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))


@bp.route("/maintenance/mode/enable", methods=["POST"])
def maintenance_mode_enable():
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days)
    message = (request.form.get("message") or "").strip()
    try:
        state = enable_maintenance_mode(message=message or None)
        flash("Mode maintenance active.", "warning")
        log_access(
            "maintenance_mode_enable",
            "platform_settings",
            0,
            success=True,
            changes={"active": bool(state.get("active")), "manual_enabled": bool(state.get("manual_enabled"))},
        )
        if _is_ajax_request():
            return jsonify({"success": True, "state": state})
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec activation maintenance: {exc}", "danger")
        if _is_ajax_request():
            return jsonify({"success": False, "error": str(exc)}), 400
    return redirect(url_for("admin.maintenance", days=days))


@bp.route("/maintenance/mode/disable", methods=["POST"])
def maintenance_mode_disable():
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days)
    try:
        state = disable_maintenance_mode()
        flash("Mode maintenance desactive.", "success")
        log_access(
            "maintenance_mode_disable",
            "platform_settings",
            0,
            success=True,
            changes={"active": bool(state.get("active")), "manual_enabled": bool(state.get("manual_enabled"))},
        )
        if _is_ajax_request():
            return jsonify({"success": True, "state": state})
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec desactivation maintenance: {exc}", "danger")
        if _is_ajax_request():
            return jsonify({"success": False, "error": str(exc)}), 400
    return redirect(url_for("admin.maintenance", days=days))


@bp.route("/maintenance/mode/schedule", methods=["POST"])
def maintenance_mode_schedule():
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days)
    start_raw = (request.form.get("starts_at") or "").strip()
    end_raw = (request.form.get("ends_at") or "").strip()
    message = (request.form.get("message") or "").strip()

    try:
        starts_at = parse_maintenance_datetime(start_raw)
        ends_at = parse_maintenance_datetime(end_raw)
        if starts_at is None or ends_at is None:
            raise ValueError("Debut et fin sont obligatoires.")
        state = schedule_maintenance_mode(starts_at=starts_at, ends_at=ends_at, message=message or None)
        flash("Maintenance programmee.", "info")
        log_access(
            "maintenance_mode_schedule",
            "platform_settings",
            0,
            success=True,
            changes={
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "active": bool(state.get("active")),
            },
        )
        if _is_ajax_request():
            return jsonify({"success": True, "state": state})
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec programmation maintenance: {exc}", "danger")
        if _is_ajax_request():
            return jsonify({"success": False, "error": str(exc)}), 400

    return redirect(url_for("admin.maintenance", days=days))


@bp.route("/maintenance/run/<string:mode>", methods=["POST"])
def run_maintenance(mode: str):
    mode_value = (mode or "").strip().lower()
    if mode_value not in {"quick", "full"}:
        flash("Mode de nettoyage invalide.", "warning")
        return redirect(url_for("admin.maintenance"))

    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days)
    cli_hint = f"flask cleanup --mode {mode_value} --days {days}"
    message = f"Nettoyage deplace hors requete HTTP. Lancez: {cli_hint}"
    log_access(
        "maintenance_run_blocked_http",
        "system",
        0,
        success=False,
        changes={"mode": mode_value, "days": days, "cli": cli_hint},
    )
    if _is_ajax_request():
        return jsonify({"success": False, "message": message, "cli": cli_hint}), 409

    flash(message, "info")
    return redirect(url_for("admin.maintenance", days=days))


@bp.route("/maintenance/reset-data", methods=["POST"])
def maintenance_reset_data():
    password = (request.form.get("password") or "").strip()
    confirm_text = (request.form.get("confirm_text") or "").strip().upper()
    backup_dir = (request.form.get("backup_dir") or "").strip()
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    errors_page = page_from_args(request.form, key="errors_page", default=1)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days, errors_page=errors_page)

    if confirm_text != "RESET":
        flash("Confirmation invalide. Tapez RESET pour continuer.", "warning")
        return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))

    if not password or not current_user.check_password(password):
        flash("Mot de passe admin invalide.", "danger")
        return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))

    # Capture des infos admin AVANT le reset
    admin_id = getattr(current_user, "id", None)
    admin_username = getattr(current_user, "username", None)

    reset_result = None
    try:
        backup_result = create_pre_reset_backup(
            backup_dir=backup_dir or None,
            requested_by_admin_id=admin_id,
            requested_by_admin_username=admin_username,
        )

        reset_result = reset_database_keep_admins()
        reset_result["backup"] = backup_result

        log_access(
            "maintenance_reset_database",
            "system",
            0,
            success=True,
            changes={
                "admins_kept": reset_result.get("admins_kept", 0),
                "backup_file": backup_result.get("backup_file"),
                "backup_dir": backup_result.get("backup_dir"),
            },
        )

        # Important: déconnecter l'utilisateur car DB/session a changé
        logout_user()

        flash(
            f"Backup cree: {backup_result.get('backup_file')} | Base reinitialisee (admins conserves).",
            "success",
        )

    except Exception as exc:
        db.session.rollback()

        # Si un reset partiel a eu lieu, mieux vaut déconnecter aussi
        try:
            logout_user()
        except Exception:
            pass

        flash(f"Echec backup/reset: {exc}", "danger")

    # Si AJAX: JSON
    if _is_ajax_request():
        return jsonify(
            {
                "success": bool(reset_result),
                "reset_result": reset_result,
            }
        )

    # Toujours redirect après un reset (jamais render_template dans la même requête)
    return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))
