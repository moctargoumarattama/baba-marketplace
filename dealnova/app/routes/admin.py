import json
import os
from pathlib import Path
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, session
from flask_login import login_required, current_user, logout_user
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models.order import Order
from ..models.financial import FinancialEntry
from ..models.maintenance import ErrorLog, MaintenanceRun
from ..models.product import Product
from ..models.promo import Promo
from ..models.featured_item import FeaturedItem
from ..models.shop import Shop
from ..models.user import User
from ..models.vendor_fulfillment import VendorFulfillment
from ..models.vendor_payout import VendorPayout
from ..models.vendor_receipt import VendorReceipt
from ..models.rental import RentalListing
from ..models.product_contact_lead import ProductContactLead
from ..models.subscription_payment import SubscriptionPayment
from ..services.audit import log_access
from sqlalchemy.orm import selectinload
from sqlalchemy import case, func, or_
from sqlalchemy.exc import SQLAlchemyError
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
    create_database_backup,
    import_database_backup,
    list_database_backups,
    create_pre_reset_backup,
    restore_database_backup,
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
from ..services.date_filters import resolve_date_filter
from ..services.finance_entries import (
    ENTRY_TYPE_DELIVERY_FEE,
    ENTRY_TYPE_RENTAL_COMMISSION,
    ENTRY_TYPE_SUBSCRIPTION,
    record_delivery_fee_entry,
)
from ..services.delivery_context import (
    DELIVERY_SOURCE_SPECIAL,
    enrich_order_delivery_context,
    enrich_orders_delivery_context,
    normalize_delivery_source,
)
from ..services.traffic_stats import get_live_traffic_metrics


bp = Blueprint("admin", __name__, url_prefix="/admin")
MAINTENANCE_PANEL_SESSION_KEY = "maintenance_panel_unlock_until"
MAINTENANCE_PANEL_DEFAULT_UNLOCK_MINUTES = 90

FINAL_DELIVERY_ORDER_STATUSES = {"delivered", "cancelled", "archived"}
ACTIVE_DELIVERY_STATUSES = {"new"}
ORDER_STATUS_FILTERS = {"", "pending", "delivered", "cancelled"}
DELIVERY_STATUS_FILTERS = {"", "new", "delivered", "canceled"}
FEATURED_SEARCH_LIMIT = 18
FEATURED_HISTORY_PER_PAGE = 30
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


def _archived_orders_query():
    return Order.query.filter(
        Order.delivery_source == DELIVERY_SOURCE_SPECIAL,
        or_(
            Order.status.in_(tuple(FINAL_DELIVERY_ORDER_STATUSES)),
            Order.delivery_status.in_(("delivered", "canceled")),
        ),
    )


def _delivery_delete_guard(order) -> tuple[bool, str, datetime | None]:
    if order is None:
        return False, "Livraison introuvable.", None
    if not _is_express_delivery_order(order):
        return False, "Suppression reservee aux livraisons express.", None
    if (order.status or "").lower() not in FINAL_DELIVERY_ORDER_STATUSES:
        return False, f"Suppression refusee: livraison non finalisee (statut {order.status}).", None
    return True, "", None


def _apply_delivery_filters(
    base_query,
    *,
    order_status_filter: str = "",
    delivery_status_filter: str = "",
    source_filter: str = "",
    city_filter: str = "",
    client_filter: str = "",
    phone_filter: str = "",
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

    return query


def _normalize_order_status_filter(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in ORDER_STATUS_FILTERS else ""


def _normalize_delivery_status_filter(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in DELIVERY_STATUS_FILTERS else ""


def _is_express_delivery_order(order: Order) -> bool:
    return normalize_delivery_source(getattr(order, "delivery_source", None)) == DELIVERY_SOURCE_SPECIAL


def _reject_product_delivery_action(message: str = "Les produits physiques sont geres directement entre client et boutique."):
    if _is_ajax_request():
        return jsonify(success=False, message=message), 410
    flash(message, "warning")
    return redirect(url_for("admin.product_contacts"))


def _operational_deliveries_query(base_query, *, now: datetime | None = None, window_hours: int = 24):
    current_time = now or datetime.utcnow()
    cutoff = current_time - timedelta(hours=window_hours)
    return base_query.filter(
        or_(
            Order.delivery_status.in_(tuple(ACTIVE_DELIVERY_STATUSES)),
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


def _maintenance_health_freshness(last_run, days: int) -> dict:
    command = f"flask cleanup --mode quick --days {days}"
    if not last_run:
        return {
            "calculated_at_label": "Non disponible",
            "status_label": "Ancien",
            "status_class": "status-warn",
            "age_label": "Aucun rapport console enregistre",
            "command": command,
        }

    calculated_at = last_run.finished_at or last_run.started_at
    if not calculated_at:
        return {
            "calculated_at_label": "Non disponible",
            "status_label": "Ancien",
            "status_class": "status-warn",
            "age_label": "Date du rapport absente",
            "command": command,
        }

    age = datetime.utcnow() - calculated_at
    total_seconds = max(0, int(age.total_seconds()))
    is_fresh = total_seconds < 86400
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours:
        age_label = f"Il y a {hours}h {minutes:02d}min"
    else:
        age_label = f"Il y a {minutes}min"

    return {
        "calculated_at_label": calculated_at.strftime("%d/%m/%Y %H:%M:%S"),
        "status_label": "Frais" if is_fresh else "Ancien",
        "status_class": "status-ok" if is_fresh else "status-warn",
        "age_label": age_label,
        "command": command,
    }


def _maintenance_backup_context() -> dict:
    retention_days = int(current_app.config.get("DB_BACKUP_RETENTION_DAYS", 30) or 30)
    backup_dir = str(current_app.config.get("MAINTENANCE_BACKUP_DIR") or "").strip()
    display_dir = backup_dir or str((Path(current_app.root_path).resolve().parent / "backups").resolve())
    project_dir = str((Path(current_app.root_path).resolve().parent).resolve())
    venv_name = str(current_app.config.get("PYTHONANYWHERE_VENV_NAME") or "babaenv").strip() or "babaenv"
    command = (
        f"cd {project_dir} && workon {venv_name} && "
        f"flask --app app:create_app db-backup --backup-dir {display_dir} --retention-days {retention_days}"
    )
    restore_command = f"flask --app app:create_app db-restore {display_dir}/nom_du_backup.sql.gz --yes"
    panel = {
        "available": True,
        "backup_dir": display_dir,
        "retention_days": retention_days,
        "command": command,
        "restore_command": restore_command,
        "backups": [],
        "latest": None,
        "status_label": "Aucune sauvegarde",
        "status_class": "status-warn",
        "note": "",
    }

    try:
        backups = list_database_backups(backup_dir=backup_dir or None)
        panel["backups"] = backups
        latest = backups[0] if backups else None
        panel["latest"] = latest
        if latest:
            modified_raw = latest.get("modified_at_utc") or ""
            modified_dt = None
            try:
                modified_dt = datetime.fromisoformat(modified_raw.replace("Z", ""))
            except ValueError:
                modified_dt = None
            if modified_dt and (datetime.utcnow() - modified_dt).total_seconds() < 86400:
                panel["status_label"] = "Sauvegarde recente"
                panel["status_class"] = "status-ok"
            else:
                panel["status_label"] = "Sauvegarde ancienne"
                panel["status_class"] = "status-warn"
    except Exception as exc:
        panel["available"] = False
        panel["status_label"] = "Erreur sauvegardes"
        panel["status_class"] = "status-danger"
        panel["note"] = str(exc)

    return panel


def _maintenance_status(value, warning: float, danger: float) -> dict:
    numeric = _to_float_or_none(value)
    if numeric is None:
        return {"level": "na", "label": "N/A", "class_name": "status-na"}
    if numeric > danger:
        return {"level": "danger", "label": "Danger", "class_name": "status-danger"}
    if numeric > warning:
        return {"level": "warning", "label": "âš ï¸ A surveiller", "class_name": "status-warn"}
    return {"level": "ok", "label": "OK", "class_name": "status-ok"}


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
        "health_freshness": _maintenance_health_freshness(last_run, days),
        "backup_panel": _maintenance_backup_context(),
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
    if int(context.get("history_page") or 1) > 1:
        params["history_page"] = int(context.get("history_page") or 1)
    if context.get("status_filter") and context["status_filter"] != "all":
        params["status"] = context["status_filter"]
    if context.get("shop_q"):
        params["shop_q"] = context["shop_q"]
    if context.get("product_q"):
        params["product_q"] = context["product_q"]
    if context.get("location_q"):
        params["location_q"] = context["location_q"]
    return url_for("admin.featured_items", **params)


def _featured_target_type_order():
    return case(
        (FeaturedItem.target_type == FeaturedItem.TARGET_SHOP, 0),
        (FeaturedItem.target_type == FeaturedItem.TARGET_PRODUCT, 1),
        (FeaturedItem.target_type == FeaturedItem.TARGET_LOCATION, 2),
        else_=3,
    )


def _featured_target_rank_subquery():
    return (
        db.session.query(
            FeaturedItem.id.label("item_id"),
            func.row_number()
            .over(
                partition_by=(
                    FeaturedItem.target_type,
                    FeaturedItem.shop_id,
                    FeaturedItem.product_id,
                    FeaturedItem.location_id,
                ),
                order_by=(
                    FeaturedItem.is_active.desc(),
                    _featured_target_type_order(),
                    FeaturedItem.ends_at.desc(),
                    FeaturedItem.created_at.desc(),
                    FeaturedItem.id.desc(),
                ),
            )
            .label("target_rank"),
        )
        .subquery()
    )


def _featured_items_query_options():
    return (
        selectinload(FeaturedItem.shop).selectinload(Shop.vendor),
        selectinload(FeaturedItem.product).selectinload(Product.shop),
        selectinload(FeaturedItem.location).selectinload(RentalListing.shop),
        selectinload(FeaturedItem.vendor),
        selectinload(FeaturedItem.created_by_admin),
    )


def _build_featured_items_context(source=None) -> dict:
    source = source or request.args
    featured_view = _normalize_featured_view(source.get("view"))
    status_filter = _normalize_featured_status(source.get("status"))
    history_page = page_from_args(source, key="history_page", default=1)
    now = datetime.utcnow()
    ranked_targets = _featured_target_rank_subquery()
    active_targets_query = (
        FeaturedItem.query
        .join(ranked_targets, FeaturedItem.id == ranked_targets.c.item_id)
        .options(*_featured_items_query_options())
        .filter(ranked_targets.c.target_rank == 1)
        .filter(
            FeaturedItem.is_active == True,
            FeaturedItem.starts_at <= now,
            FeaturedItem.ends_at >= now,
        )
        .order_by(
            _featured_target_type_order(),
            FeaturedItem.ends_at.desc(),
            FeaturedItem.created_at.desc(),
            FeaturedItem.id.desc(),
        )
    )
    latest_rows = active_targets_query.all()
    for item in latest_rows:
        item.ui_status = "active"

    history_query = (
        FeaturedItem.query
        .join(ranked_targets, FeaturedItem.id == ranked_targets.c.item_id)
        .options(*_featured_items_query_options())
        .filter(
            or_(
                ranked_targets.c.target_rank > 1,
                FeaturedItem.is_active == False,
                FeaturedItem.starts_at > now,
                FeaturedItem.ends_at < now,
            )
        )
        .order_by(FeaturedItem.created_at.desc(), FeaturedItem.id.desc())
    )
    history_pagination = history_query.paginate(
        page=history_page,
        per_page=FEATURED_HISTORY_PER_PAGE,
        error_out=False,
    )
    history_items = history_pagination.items
    for item in history_items:
        item.ui_status = "history"
        item.can_delete_after = item.created_at + timedelta(days=30)
        item.can_delete_now = item.can_delete_after <= now

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
        "history_count": history_pagination.total,
        "history_pagination": history_pagination,
        "history_page": history_pagination.page,
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

        flash("Accès réservé aux administrateurs", "danger")
    return redirect(url_for("shop.home"))


@bp.before_request
def restrict_sensitive_pages_for_manager():
    if _is_manager_user() and request.endpoint in MANAGER_BLOCKED_ADMIN_ENDPOINTS:
        return _sensitive_admin_forbidden_response()


# ======================
# CONTACTS PRODUITS
# ======================
@bp.route("/promotions")
def promo_reviews():
    page = page_from_args(request.args)
    status = (request.args.get("status") or Promo.STATUS_PENDING).strip().lower()
    if status not in {Promo.STATUS_PENDING, Promo.STATUS_APPROVED, Promo.STATUS_REJECTED, "all"}:
        status = Promo.STATUS_PENDING

    query = (
        Promo.query
        .join(Product, Product.id == Promo.product_id)
        .outerjoin(Shop, Shop.id == Product.shop_id)
        .options(selectinload(Promo.product).selectinload(Product.shop))
    )
    if status != "all":
        query = query.filter(Promo.status == status)

    pagination = (
        query
        .order_by(
            case((Promo.status == Promo.STATUS_PENDING, 0), else_=1),
            Promo.created_at.desc(),
            Promo.id.desc(),
        )
        .paginate(page=page, per_page=40, error_out=False)
    )
    trusted_shop_ids = {
        shop_id for (shop_id,) in Shop.query.with_entities(Shop.id).filter(Shop.promo_trusted == True).all()
    }
    status_counts = {
        row.status: int(row.total or 0)
        for row in (
            db.session.query(Promo.status, func.count(Promo.id).label("total"))
            .group_by(Promo.status)
            .all()
        )
    }
    return render_template(
        "admin/promo_reviews.html",
        promos=pagination.items,
        pagination=pagination,
        status=status,
        trusted_shop_ids=trusted_shop_ids,
        status_counts=status_counts,
    )


@bp.route("/promotions/<int:promo_id>/approve", methods=["POST"])
def promo_approve(promo_id):
    promo = Promo.query.get_or_404(promo_id)
    trust_shop = request.form.get("trust_shop") == "1"
    promo.status = Promo.STATUS_APPROVED
    promo.review_note = (request.form.get("review_note") or "").strip()[:500] or None
    promo.reviewed_by_id = current_user.id
    promo.reviewed_at = datetime.utcnow()
    if trust_shop and promo.product and promo.product.shop:
        promo.product.shop.promo_trusted = True
    db.session.commit()
    bump_catalog_version()
    flash("Promotion approuvée.", "success")
    return redirect(url_for("admin.promo_reviews"))


@bp.route("/promotions/<int:promo_id>/reject", methods=["POST"])
def promo_reject(promo_id):
    promo = Promo.query.get_or_404(promo_id)
    promo.status = Promo.STATUS_REJECTED
    promo.review_note = (request.form.get("review_note") or "").strip()[:500] or "Refusée par l'admin."
    promo.reviewed_by_id = current_user.id
    promo.reviewed_at = datetime.utcnow()
    db.session.commit()
    bump_catalog_version()
    flash("Promotion refusée.", "info")
    return redirect(url_for("admin.promo_reviews"))


@bp.route("/shops/<int:shop_id>/promo-trusted", methods=["POST"])
def shop_promo_trusted_toggle(shop_id):
    shop = Shop.query.get_or_404(shop_id)
    shop.promo_trusted = not bool(shop.promo_trusted)
    db.session.commit()
    flash(
        "Publication automatique des promos activée." if shop.promo_trusted else "Validation admin des promos réactivée.",
        "success",
    )
    return redirect(request.referrer or url_for("admin_users.shop_detail", shop_id=shop.id))


@bp.route("/product-contacts")
def product_contacts():
    page = page_from_args(request.args)
    search = (request.args.get("q") or "").strip()
    phone_filter = (request.args.get("phone") or "").strip()
    shop_id_filter = request.args.get("shop_id", type=int)
    date_filter = resolve_date_filter(request.args, default="month")

    query = (
        ProductContactLead.query
        .outerjoin(Shop, ProductContactLead.shop_id == Shop.id)
        .options(selectinload(ProductContactLead.shop))
        .filter(ProductContactLead.source == "product_whatsapp")
    )

    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            ProductContactLead.client_name.ilike(like),
            ProductContactLead.client_phone.ilike(like),
            ProductContactLead.product_summary_json.ilike(like),
            Shop.name.ilike(like),
        ))
    if phone_filter:
        query = query.filter(ProductContactLead.client_phone.ilike(f"%{phone_filter}%"))
    if shop_id_filter:
        query = query.filter(ProductContactLead.shop_id == shop_id_filter)
    query = query.filter(
        ProductContactLead.created_at >= date_filter.start_at,
        ProductContactLead.created_at < date_filter.end_at,
    )

    pagination = query.order_by(ProductContactLead.created_at.desc()).paginate(
        page=page,
        per_page=50,
        error_out=False,
    )

    for lead in pagination.items:
        try:
            summary = json.loads(lead.product_summary_json or "[]")
        except (TypeError, ValueError):
            summary = []
        lead._product_summary = summary if isinstance(summary, list) else []

    shops = Shop.query.order_by(Shop.name.asc()).all()

    return render_template("admin/product_contacts.html",
        leads=pagination.items,
        pagination=pagination,
        shops=shops,
        search=search,
        phone_filter=phone_filter,
        shop_id_filter=shop_id_filter,
        range_filter=date_filter.range_filter,
        date_range_label=date_filter.label,
        date_from=date_filter.date_from,
        date_to=date_filter.date_to,
        total_contacts=pagination.total,
    )


# ======================
# LIVRAISONS
# ======================
@bp.route("/deliveries")
def deliveries():
    now = datetime.utcnow()
    date_filter = resolve_date_filter(request.args, default="month")
    read_only = False
    base_query = Order.query
    source_filter = DELIVERY_SOURCE_SPECIAL
    base_query = base_query.filter(Order.delivery_source == DELIVERY_SOURCE_SPECIAL)
    order_status_filter = _normalize_order_status_filter(request.args.get("order_status") or request.args.get("status"))
    delivery_status_filter = _normalize_delivery_status_filter(request.args.get("delivery_status"))
    scoped_base = base_query
    if order_status_filter:
        scoped_base = scoped_base.filter(Order.status == order_status_filter)
    if delivery_status_filter:
        scoped_base = scoped_base.filter(Order.delivery_status == delivery_status_filter)
    operational_base = _operational_deliveries_query(scoped_base, now=now, window_hours=24)

    pending_query = (
        operational_base.filter(Order.delivery_status.in_(tuple(ACTIVE_DELIVERY_STATUSES)))
        .order_by(Order.created_at.desc())
    )
    pending = pending_query.limit(25).all()

    delivered_recent_query = (
        operational_base.filter(Order.delivery_status == "delivered")
        .filter(Order.delivered_at.is_(None) | (Order.delivered_at >= (now - timedelta(hours=24))))
    )
    total_baba_fee = (
        delivered_recent_query.with_entities(
            db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)
        ).scalar() or 0
    ) / 100
    pending_count = operational_base.filter(Order.delivery_status.in_(tuple(ACTIVE_DELIVERY_STATUSES))).count()
    delivered_recent_count = delivered_recent_query.count()
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
    )
    history_query = history_query.filter(
        Order.created_at >= date_filter.start_at,
        Order.created_at < date_filter.end_at,
    )

    pagination = history_query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=30, error_out=False
    )
    history_orders = pagination.items
    enrich_orders_delivery_context(pending)
    enrich_orders_delivery_context(history_orders)

    if request.args.get("export") == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "Date", "Statut", "Source", "Client", "Telephone", "Ville",
            "Objet", "Depart", "Arrivee", "DeliveryStatus", "Total(MAD)",
            "Livraison(MAD)", "RevenuLivraisonBaba(MAD)", "RemiseBaba"
        ])

        for order in history_orders:
            writer.writerow([
                order.id,
                order.created_at.strftime("%d/%m/%Y %H:%M") if order.created_at else "",
                order.status,
                order.delivery_source or DELIVERY_SOURCE_SPECIAL,
                order.full_name,
                order.phone,
                order.delivery_city or order.city,
                order.special_item or "",
                order.special_pickup_address or "",
                order.special_dropoff_address or order.delivery_address or "",
                order.delivery_status,
                f"{(order.total or 0) / 100:.2f}",
                f"{(order.delivery_price_cents or order.shipping or 0) / 100:.2f}",
                f"{(order.delivery_platform_fee_cents or 0) / 100:.2f}",
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
        pending_count=pending_count,
        delivered_recent_count=delivered_recent_count,
        pagination=pagination,
        history_orders=history_orders,
        source_filter=source_filter,
        order_status_filter=order_status_filter,
        delivery_status_filter=delivery_status_filter,
        range_filter=date_filter.range_filter,
        date_range_label=date_filter.label,
        date_from=date_filter.date_from,
        date_to=date_filter.date_to,
        city_filter=city_filter,
        client_filter=client_filter,
        phone_filter=phone_filter,
        cities=Order.CITIES,
        read_only=read_only,
    )


@bp.route("/deliver/<int:oid>", methods=["POST"])
def mark_delivered(oid):
    order = Order.query.get_or_404(oid)
    if not _is_express_delivery_order(order):
        return _reject_product_delivery_action("Baba ne marque plus les produits physiques comme livres.")
    order.status = "delivered"
    order.delivery_status = "delivered"
    order.delivered_at = datetime.utcnow()
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
            f"Livraison express #{oid} livree - revenu livraison Baba: "
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
    if not _is_express_delivery_order(order):
        return _reject_product_delivery_action("Baba ne modifie plus les demandes produits WhatsApp.")
    order.status = "cancelled"
    order.delivery_status = "canceled"
    order.delivered_at = None
    order.baba_fee_settled_at = None
    order.baba_fee_settled_by_user_id = None
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


    flash(f"Livraison express #{oid} annulee", "warning")
    next_url = request.args.get("next")
    if next_url and next_url.endswith("?"):
        next_url = next_url[:-1]
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("admin.deliveries"))


# ======================
# Redirections legacy produit / archives livraison express
# ======================
@bp.route("/orders")
def all_orders():
    flash("Les produits physiques sont maintenant consultables dans Contacts produits.", "info")
    return redirect(url_for("admin.product_contacts"))


@bp.route("/orders/archives")
def order_archives():
    redirect_params = {}
    range_filter = (request.args.get("range") or "").strip()
    if range_filter:
        redirect_params["range"] = range_filter

    date_from = (request.args.get("date_from") or request.args.get("from") or "").strip()
    if date_from:
        redirect_params["date_from"] = date_from

    date_to = (request.args.get("date_to") or request.args.get("to") or "").strip()
    if date_to:
        redirect_params["date_to"] = date_to

    page = page_from_args(request.args, key="archives_page", default=1)
    if page > 1:
        redirect_params["page"] = page

    return redirect(url_for("admin.deliveries_archives", **redirect_params))


@bp.route("/finance")
def finance():
    page = page_from_args(request.args)
    date_filter = resolve_date_filter(request.args, default="month")
    entry_type = (request.args.get("entry_type") or "").strip().lower()
    if entry_type not in {ENTRY_TYPE_DELIVERY_FEE, ENTRY_TYPE_SUBSCRIPTION, ENTRY_TYPE_RENTAL_COMMISSION}:
        entry_type = ""

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
    rows = (
        db.session.query(
            FinancialEntry.entry_type,
            db.func.count(FinancialEntry.id).label("cnt"),
            db.func.coalesce(db.func.sum(FinancialEntry.amount_cents), 0).label("total"),
        )
        .filter(
            FinancialEntry.deleted_at.is_(None),
            FinancialEntry.created_at >= date_filter.start_at,
            FinancialEntry.created_at < date_filter.end_at,
        )
        .group_by(FinancialEntry.entry_type)
        .all()
    )
    for row in rows:
        count = int(row.cnt or 0)
        total = int(row.total or 0)
        selected_totals["entry_count"] += count
        if row.entry_type == ENTRY_TYPE_DELIVERY_FEE:
            selected_totals["delivery_total_cents"] = total
            selected_totals["delivery_count"] = count
        elif row.entry_type == ENTRY_TYPE_SUBSCRIPTION:
            selected_totals["subscription_total_cents"] = total
            selected_totals["subscription_count"] = count
        elif row.entry_type == ENTRY_TYPE_RENTAL_COMMISSION:
            selected_totals["rental_total_cents"] = total
            selected_totals["rental_count"] = count
    selected_totals["total_cents"] = (
        selected_totals["delivery_total_cents"]
        + selected_totals["subscription_total_cents"]
        + selected_totals["rental_total_cents"]
    )

    entries_query = (
        FinancialEntry.query
        .options(
            selectinload(FinancialEntry.order),
            selectinload(FinancialEntry.rental_archive),
            selectinload(FinancialEntry.subscription_payment),
            selectinload(FinancialEntry.subscription_payment).selectinload(SubscriptionPayment.user),
            selectinload(FinancialEntry.subscription_payment).selectinload(SubscriptionPayment.created_by),
        )
        .filter(FinancialEntry.deleted_at.is_(None))
    )
    entries_query = entries_query.filter(
        FinancialEntry.created_at >= date_filter.start_at,
        FinancialEntry.created_at < date_filter.end_at,
    )

    if entry_type:
        entries_query = entries_query.filter(FinancialEntry.entry_type == entry_type)
    entries_pagination = entries_query.order_by(
        FinancialEntry.created_at.desc(),
        FinancialEntry.id.desc(),
    ).paginate(page=page, per_page=50, error_out=False)

    entry_type_labels = {
        ENTRY_TYPE_DELIVERY_FEE: "Livraison express",
        ENTRY_TYPE_SUBSCRIPTION: "Abonnement vendeur",
        ENTRY_TYPE_RENTAL_COMMISSION: "Commission location",
    }

    return render_template(
        "admin/finance.html",
        selected_totals=selected_totals,
        entries=entries_pagination.items,
        entries_pagination=entries_pagination,
        entry_type=entry_type,
        range_filter=date_filter.range_filter,
        date_range_label=date_filter.label,
        date_from=date_filter.date_from,
        date_to=date_filter.date_to,
        entry_type_labels=entry_type_labels,
    )

@bp.route("/orders/<int:oid>/delete", methods=["POST"])
def delete_archived_order(oid: int):
    next_url = (request.args.get("next") or request.form.get("next") or "").strip()

    def _redirect_after_delete(default_endpoint: str = "admin.deliveries_archives"):
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for(default_endpoint))

    order = (
        Order.query
        .filter(Order.id == oid)
        .first()
    )
    if order is None:
        return render_template("errors/404.html"), 404
    allowed, message, _available_at = _delivery_delete_guard(order)
    if not allowed:
        flash(message or "Suppression refusee.", "warning")
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
            changes={"status": order.status},
        )
        flash(f"Livraison express #{oid} supprimee definitivement.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec suppression livraison express #{oid}: {exc}", "danger")

    return _redirect_after_delete()


@bp.route("/deliveries/live")
def deliveries_live():
    now = datetime.utcnow()
    date_filter = resolve_date_filter(request.args, default="month")
    read_only = False
    source_filter = DELIVERY_SOURCE_SPECIAL
    order_status_filter = _normalize_order_status_filter(request.args.get("order_status") or request.args.get("status"))
    delivery_status_filter = _normalize_delivery_status_filter(request.args.get("delivery_status"))
    city_filter = request.args.get("city", "")
    client_filter = request.args.get("client", "")
    phone_filter = request.args.get("phone", "")
    page = page_from_args(request.args)

    base_query = Order.query
    base_query = base_query.filter(Order.delivery_source == DELIVERY_SOURCE_SPECIAL)
    scoped_base = base_query
    if order_status_filter:
        scoped_base = scoped_base.filter(Order.status == order_status_filter)
    if delivery_status_filter:
        scoped_base = scoped_base.filter(Order.delivery_status == delivery_status_filter)
    operational_base = _operational_deliveries_query(scoped_base, now=now, window_hours=24)

    pending_query = (
        operational_base.filter(Order.delivery_status.in_(tuple(ACTIVE_DELIVERY_STATUSES)))
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
    )
    history_query = history_query.filter(
        Order.created_at >= date_filter.start_at,
        Order.created_at < date_filter.end_at,
    )

    pagination = history_query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=30, error_out=False
    )

    def to_json(order):
        can_mutate = (not read_only) and (order.delivery_status in ACTIVE_DELIVERY_STATUSES)
        next_params = {
            "order_status": order_status_filter or None,
            "delivery_status": delivery_status_filter or None,
            "range": date_filter.range_filter,
            "date_from": date_filter.date_from or None,
            "date_to": date_filter.date_to or None,
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
            "delivery_source": order.delivery_source or DELIVERY_SOURCE_SPECIAL,
            "total": round((order.total or 0) / 100, 2),
            "delivery_price": round((order.delivery_price_cents or order.shipping or 0) / 100, 2),
            "delivery_platform_fee": round((order.delivery_platform_fee_cents or 0) / 100, 2),
            "baba_fee_settled": bool(order.baba_fee_settled_at),
            "status": order.status,
            "delivery_status": order.delivery_status,
            "can_mutate": can_mutate,
            "created_at": order.created_at.strftime("%d/%m/%Y %H:%M") if order.created_at else "",
            "special_item": order.special_item or "",
            "pickup_address": order.special_pickup_address or "",
            "dropoff_address": order.special_dropoff_address or order.delivery_address or "",
            "detail_url": url_for("admin.order_detail", oid=order.id, next=next_url),
            "deliver_url": url_for("admin.mark_delivered", oid=order.id, next=next_url),
            "cancel_url": url_for("admin.cancel_order", oid=order.id, next=next_url),
            "call_url": f"tel:{order.phone}"
        }

    return jsonify(
        pending_count=operational_base.filter(Order.delivery_status.in_(tuple(ACTIVE_DELIVERY_STATUSES))).count(),
        delivered_recent_count=delivered_recent_count,
        total_baba_fee=round(total_baba_fee, 2),
        read_only=read_only,
        range_filter=date_filter.range_filter,
        date_range_label=date_filter.label,
        source_filter=source_filter,
        order_status_filter=order_status_filter,
        delivery_status_filter=delivery_status_filter,
        history_total=pagination.total,
        page=pagination.page,
        pages=pagination.pages,
        pending_orders=[to_json(o) for o in pending_orders],
        history_orders=[to_json(o) for o in pagination.items]
    )


@bp.route("/deliveries/archives")
def deliveries_archives():
    status_filter = request.args.get("status", "")
    source_filter = DELIVERY_SOURCE_SPECIAL
    date_filter = resolve_date_filter(request.args, default="month")
    city_filter = request.args.get("city", "")
    client_filter = request.args.get("client", "")
    phone_filter = request.args.get("phone", "")
    page = page_from_args(request.args)

    try:
        base_archived = _archived_orders_query()

        history_query = _apply_delivery_filters(
            base_archived,
            order_status_filter=status_filter,
            source_filter=source_filter,
            city_filter=city_filter,
            client_filter=client_filter,
            phone_filter=phone_filter,
        ).filter(
            Order.created_at >= date_filter.start_at,
            Order.created_at < date_filter.end_at,
        )

        pagination = history_query.order_by(Order.created_at.desc()).paginate(
            page=page, per_page=30, error_out=False
        )
        history_orders = pagination.items
        enrich_orders_delivery_context(history_orders)

        delete_guards = {}
        for order in history_orders:
            allowed, message, available_at = _delivery_delete_guard(order)
            delete_guards[order.id] = {
                "allowed": allowed,
                "message": message,
                "available_at": available_at,
            }

    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "deliveries_archives.db_error - source=%s page=%s",
            source_filter, page,
        )
        flash("Erreur lors du chargement des archives. Merci de réessayer.", "danger")
        return redirect(url_for("admin.deliveries"))

    except Exception:
        current_app.logger.exception(
            "deliveries_archives.unexpected_error - source=%s page=%s",
            source_filter, page,
        )
        flash("Une erreur inattendue s'est produite.", "danger")
        return redirect(url_for("admin.deliveries"))

    return render_template(
        "admin/deliveries_archives.html",
        pagination=pagination,
        history_orders=history_orders,
        source_filter=source_filter,
        status_filter=status_filter,
        range_filter=date_filter.range_filter,
        date_range_label=date_filter.label,
        date_from=date_filter.date_from,
        date_to=date_filter.date_to,
        city_filter=city_filter,
        client_filter=client_filter,
        phone_filter=phone_filter,
        cities=Order.CITIES,
        delete_guards=delete_guards,
    )


@bp.route("/order/<int:oid>")
def order_detail(oid):
    order = Order.query.get_or_404(oid)
    if not _is_express_delivery_order(order):
        flash("Les anciennes commandes produits sont remplacees par Contacts produits.", "info")
        return redirect(url_for("admin.product_contacts"))
    enrich_order_delivery_context(order)
    log_access("view_order", "order", order.id, success=True)
    return render_template("admin/order_detail.html", order=order)


# ======================
# Tarifs et finance
# ======================



# ======================
# PARAMETRES PLATEFORME
# ======================
@bp.route("/pricing", methods=["GET", "POST"])
def pricing_settings():
    if request.method == "GET" and (request.args.get("section") or "").strip().lower() == "archives":
        redirect_params = {}
        range_filter = (request.args.get("range") or "").strip()
        if range_filter:
            redirect_params["range"] = range_filter

        date_from = (request.args.get("date_from") or request.args.get("from") or "").strip()
        if date_from:
            redirect_params["date_from"] = date_from

        date_to = (request.args.get("date_to") or request.args.get("to") or "").strip()
        if date_to:
            redirect_params["date_to"] = date_to

        page = page_from_args(request.args, key="archives_page", default=1)
        if page > 1:
            redirect_params["page"] = page

        return redirect(url_for("admin.deliveries_archives", **redirect_params))

    settings = PlatformSettings.get()

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
            return render_template("admin/pricing.html", settings=settings)

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

    return render_template("admin/pricing.html", settings=settings)


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
from ..models.maintenance import MaintenanceRun

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
            "health_freshness": _maintenance_health_freshness(None, days),
            "backup_panel": _maintenance_backup_context(),
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


@bp.route("/maintenance/backups/create", methods=["POST"])
def maintenance_backup_create():
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days)

    backup_dir = (request.form.get("backup_dir") or "").strip()
    retention_raw = (request.form.get("retention_days") or "").strip()
    retention_days = int(retention_raw) if retention_raw.isdigit() else None
    try:
        result = create_database_backup(backup_dir=backup_dir or None, retention_days=retention_days)
        flash(f"Sauvegarde creee: {result.get('backup_file')}", "success")
        log_access(
            "maintenance_db_backup_create",
            "system",
            0,
            success=True,
            changes={"backup_file": result.get("backup_file"), "backup_dir": result.get("backup_dir")},
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec sauvegarde base de donnees: {exc}", "danger")
    return redirect(url_for("admin.maintenance", days=days) + "#maintenance-backups")


@bp.route("/maintenance/backups/import", methods=["POST"])
def maintenance_backup_import():
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days)

    backup_dir = (request.form.get("backup_dir") or "").strip()
    upload = request.files.get("backup_file")
    if not upload or not upload.filename:
        flash("Choisis un fichier .sql.gz a importer.", "warning")
        return redirect(url_for("admin.maintenance", days=days) + "#maintenance-backups")

    try:
        result = import_database_backup(
            source_stream=upload,
            filename=upload.filename,
            backup_dir=backup_dir or None,
        )
        flash(f"Sauvegarde importee: {result.get('backup_file')}", "success")
        log_access(
            "maintenance_db_backup_import",
            "system",
            0,
            success=True,
            changes={"backup_file": result.get("backup_file"), "original_filename": result.get("original_filename")},
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec import sauvegarde: {exc}", "danger")
    return redirect(url_for("admin.maintenance", days=days) + "#maintenance-backups")


@bp.route("/maintenance/backups/restore", methods=["POST"])
def maintenance_backup_restore():
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    if not _maintenance_panel_is_unlocked():
        return _maintenance_protected_redirect(days=days)

    password = (request.form.get("password") or "").strip()
    confirm_text = (request.form.get("confirm_text") or "").strip().upper()
    backup_file = (request.form.get("backup_file") or "").strip()

    if confirm_text != "RESTAURER":
        flash("Confirmation invalide. Tape RESTAURER pour continuer.", "warning")
        return redirect(url_for("admin.maintenance", days=days) + "#maintenance-backups")

    if not password or not current_user.check_password(password):
        flash("Mot de passe admin invalide.", "danger")
        return redirect(url_for("admin.maintenance", days=days) + "#maintenance-backups")

    if not backup_file:
        flash("Sauvegarde a restaurer introuvable.", "warning")
        return redirect(url_for("admin.maintenance", days=days) + "#maintenance-backups")

    try:
        result = restore_database_backup(backup_file, yes=True)
        flash(f"Base restauree depuis: {result.get('restored_file')}", "success")
        log_access(
            "maintenance_db_backup_restore",
            "system",
            0,
            success=True,
            changes={"restored_file": result.get("restored_file"), "database": result.get("database")},
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec restauration base de donnees: {exc}", "danger")

    return redirect(url_for("admin.maintenance", days=days) + "#maintenance-backups")


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
