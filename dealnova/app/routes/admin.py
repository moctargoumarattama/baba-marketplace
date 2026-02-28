from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user, logout_user
from datetime import date, datetime, timedelta
from urllib.parse import quote

from ..extensions import db
from ..models.order import Order, OrderItem
from ..models.order_period import OrderPeriod
from ..models.financial import FinancialPeriod, FinancialEntry
from ..models.maintenance import ErrorLog, MaintenanceRun
from ..models.product import Product
from ..models.shop import Shop
from ..models.user import User
from ..models.vendor_fulfillment import VendorFulfillment
from ..models.vendor_payout import VendorPayout
from ..models.vendor_receipt import VendorReceipt
from ..services.audit import log_access
from sqlalchemy.orm import selectinload
from sqlalchemy import or_

from ..models.platform_settings import PlatformSettings
from ..services.maintenance import (
    DB_SIZE_MB_DANGER,
    DB_SIZE_MB_WARNING,
    EXPIRED_LOCATIONS_GT_DAYS_DANGER,
    EXPIRED_LOCATIONS_GT_DAYS_WARNING,
    ORPHAN_MEDIA_COUNT_DANGER,
    ORPHAN_MEDIA_COUNT_WARNING,
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
)
from ..services.financial_periods import (
    ENTRY_TYPE_DELIVERY_FEE,
    ENTRY_TYPE_RENTAL_COMMISSION,
    ENTRY_TYPE_SUBSCRIPTION,
    FINANCIAL_PERIOD_CLOSED,
    FINANCIAL_PERIOD_DELETE_RETENTION_DAYS,
    FINANCIAL_PERIOD_OPEN,
    close_financial_period,
    compute_period_totals,
    create_financial_period,
    financial_period_delete_guard,
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

FINAL_DELIVERY_ORDER_STATUSES = {"delivered", "cancelled", "archived"}
COURIER_ASSIGNMENT_FILTERS = {"", "unassigned", "assigned", "delivered"}
COURIER_DELIVERY_IN_PROGRESS = {"new", "assigned", "picked_up", "delivering"}
COURIER_DELIVERY_COMPLETED = {"delivered", "canceled"}
DELIVERY_SOURCE_FILTERS = {"", DELIVERY_SOURCE_MARKETPLACE, DELIVERY_SOURCE_SPECIAL}

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


def _open_order_period() -> OrderPeriod | None:
    return (
        OrderPeriod.query
        .filter(OrderPeriod.status == OPEN_STATUS)
        .order_by(OrderPeriod.opened_at.desc(), OrderPeriod.id.desc())
        .first()
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


def _apply_delivery_filters(
    base_query,
    *,
    status_filter: str = "",
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
    if status_filter:
        query = query.filter(Order.status == status_filter)
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

    health_badges = _maintenance_badges(health)

    errors_block = {
        "available": True,
        "total_500_last_24h": "N/A",
        "items": [],
        "page": max(1, int(errors_page or 1)),
        "per_page": 20,
        "pagination": None,
        "note": "",
    }
    try:
        since = datetime.utcnow() - timedelta(hours=24)
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


# ======================
# ADMIN ONLY
# ======================
@bp.before_request
@login_required
def restrict_admin():
    role = (getattr(current_user, "role", "") or "").lower()
    if role == "admin":
        return None

    if role == "courier":
        return render_template("errors/403.html"), 403

    flash("Accès réservé aux administrateurs", "danger")
    return redirect(url_for("shop.home"))


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
    scoped_base = _apply_courier_assignment_filter(period_base, delivery_scope)
    if courier_id_filter:
        scoped_base = scoped_base.filter(Order.courier_id == courier_id_filter)

    pending_query = (
        scoped_base.filter(Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS)))
        .options(
            selectinload(Order.courier),
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
        )
        .order_by(Order.created_at.desc())
    )
    pending = enrich_orders(pending_query.limit(25).all())

    delivered_recent_query = (
        scoped_base.filter(Order.delivery_status == "delivered")
        .filter(Order.delivered_at.is_(None) | (Order.delivered_at >= (now - timedelta(hours=72))))
    )
    total_baba_fee = (
        delivered_recent_query.with_entities(
            db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)
        ).scalar() or 0
    ) / 100
    pending_count = scoped_base.filter(Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS))).count()
    delivered_recent_count = delivered_recent_query.count()

    status_filter = request.args.get("status", "")
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    product_filter = request.args.get("product", "")
    shop_filter = request.args.get("shop", "")
    city_filter = request.args.get("city", "")
    client_filter = request.args.get("client", "")
    phone_filter = request.args.get("phone", "")
    page = page_from_args(request.args)

    history_query = _apply_delivery_filters(
        scoped_base,
        status_filter=status_filter,
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
        response.headers["Content-Disposition"] = "attachment; filename=deliveries_history.csv"
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
        status_filter=status_filter,
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
        order.courier.courier_is_available = True
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
        order.courier.courier_is_available = True
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
    order.courier_id = courier.id if courier else None

    if courier:
        now = datetime.utcnow()
        if order.delivery_status in {"new", ""}:
            order.delivery_status = "assigned"
        order.assigned_at = now
        order.assigned_by_user_id = current_user.id if current_user.is_authenticated else None
        # Avoid double assignment: once assigned by admin, courier becomes unavailable.
        courier.courier_is_available = False
        courier.courier_last_seen_at = now
    else:
        if order.delivery_status in {"assigned", "picked_up", "delivering"}:
            order.delivery_status = "new"
            order.picked_up_at = None
        order.assigned_by_user_id = None

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
    delivery_scope = _normalize_courier_assignment_filter(request.args.get("delivery_scope"))
    courier_id_filter = request.args.get("courier_id", type=int)

    period_base = _orders_query_for_period(
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
    )
    if source_filter:
        period_base = period_base.filter(Order.delivery_source == source_filter)
    scoped_base = _apply_courier_assignment_filter(period_base, delivery_scope)
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
    pending_count = scoped_base.filter(Order.status == "pending").count()
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
        delivery_scope=delivery_scope,
        courier_id_filter=courier_id_filter,
        couriers=couriers,
        courier_filters=courier_filters,
        read_only=read_only,
        notify_url=url_for(
            "admin.orders_notifications",
            period_id=selected_period_id,
            include_legacy=1 if include_legacy else None,
            source=source_filter or None,
            delivery_scope=delivery_scope or None,
            courier_id=courier_id_filter or None,
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
    delivery_scope = _normalize_courier_assignment_filter(request.args.get("delivery_scope"))
    courier_id_filter = request.args.get("courier_id", type=int)
    scoped_base = _apply_courier_assignment_filter(period_base, delivery_scope)
    if courier_id_filter:
        scoped_base = scoped_base.filter(Order.courier_id == courier_id_filter)
    latest_order = scoped_base.order_by(Order.created_at.desc()).first()
    latest_order_id = latest_order.id if latest_order else 0
    pending_count = scoped_base.filter(Order.status == "pending").count()
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
    delivery_scope = _normalize_courier_assignment_filter(request.args.get("delivery_scope"))
    courier_id_filter = request.args.get("courier_id", type=int)

    period_base = _orders_query_for_period(
        selected_period_id=selected_period_id,
        include_legacy=include_legacy,
    )
    if source_filter:
        period_base = period_base.filter(Order.delivery_source == source_filter)
    scoped_base = _apply_courier_assignment_filter(period_base, delivery_scope)
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
    pending_count = scoped_base.filter(Order.status == "pending").count()
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
            delivery_scope=delivery_scope or None,
            courier_id=courier_id_filter or None,
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
            "detail_url": url_for("admin.order_detail", oid=o.id),
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
        delivery_scope=delivery_scope,
        courier_id_filter=courier_id_filter,
        orders=[format_order(o) for o in orders]
    )


@bp.route("/orders/archives")
def order_archives():
    page = page_from_args(request.args)
    period_id = request.args.get("period_id", type=int)

    query = _archived_orders_query().options(
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.period),
    )
    if period_id:
        query = query.filter(Order.period_id == period_id)

    pagination = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    orders = pagination.items

    closed_periods = (
        OrderPeriod.query
        .filter(OrderPeriod.status == CLOSED_STATUS)
        .order_by(OrderPeriod.closed_at.desc(), OrderPeriod.id.desc())
        .all()
    )
    now = datetime.utcnow()
    delete_guards = {}
    for order in orders:
        allowed, message, available_at = order_delete_guard(order, now=now)
        delete_guards[order.id] = {
            "allowed": allowed,
            "message": message,
            "available_at": available_at,
        }

    return render_template(
        "admin/order_archives.html",
        orders=orders,
        pagination=pagination,
        period_id=period_id,
        closed_periods=closed_periods,
        delete_guards=delete_guards,
        retention_days=ORDER_DELETE_RETENTION_DAYS,
    )


@bp.route("/order-periods")
def order_periods():
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

    return render_template(
        "admin/order_periods.html",
        periods=periods,
        open_period=open_period,
        period_counts=period_counts,
        retention_days=ORDER_DELETE_RETENTION_DAYS,
    )


@bp.route("/order-periods/create", methods=["POST"])
def order_period_create():
    name = (request.form.get("name") or "").strip()
    try:
        period = create_order_period(
            name=name or None,
            created_by=current_user.id if current_user.is_authenticated else None,
        )
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
    return redirect(url_for("admin.order_periods"))


@bp.route("/order-periods/<int:period_id>/close", methods=["POST"])
def order_period_close(period_id: int):
    period = db.session.get(OrderPeriod, period_id)
    if period is None:
        return render_template("errors/404.html"), 404
    if period.status == CLOSED_STATUS:
        flash("Cette periode est deja fermee.", "info")
        return redirect(url_for("admin.order_periods"))

    try:
        close_order_period(period)
        db.session.commit()
        log_access(
            "close_order_period",
            "order_period",
            period.id,
            success=True,
            changes={"closed_at": period.closed_at.isoformat() if period.closed_at else None},
        )
        flash(f"Periode fermee: {period.name}", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec fermeture periode: {exc}", "danger")
    return redirect(url_for("admin.order_periods"))


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

    periods = (
        FinancialPeriod.query
        .filter(FinancialPeriod.deleted_at.is_(None))
        .order_by(
            db.case((FinancialPeriod.status == FINANCIAL_PERIOD_OPEN, 0), else_=1),
            FinancialPeriod.start_date.desc(),
            FinancialPeriod.id.desc(),
        )
        .all()
    )

    selected_period = None
    if requested_period_id is not None:
        selected_period = next((period for period in periods if period.id == requested_period_id), None)

    if selected_period is None and periods:
        selected_period = next((period for period in periods if period.status == FINANCIAL_PERIOD_OPEN), periods[0])

    selected_period_id = selected_period.id if selected_period else None

    period_ids = [period.id for period in periods]
    period_stats = {
        period_id: {
            "delivery_total_cents": 0,
            "subscription_total_cents": 0,
            "rental_total_cents": 0,
            "total_cents": 0,
            "entry_count": 0,
        }
        for period_id in period_ids
    }
    if period_ids:
        rows = (
            db.session.query(
                FinancialEntry.period_id,
                FinancialEntry.entry_type,
                db.func.coalesce(db.func.sum(FinancialEntry.amount_cents), 0).label("amount"),
                db.func.count(FinancialEntry.id).label("count"),
            )
            .filter(
                FinancialEntry.deleted_at.is_(None),
                FinancialEntry.period_id.in_(period_ids),
            )
            .group_by(FinancialEntry.period_id, FinancialEntry.entry_type)
            .all()
        )
        for row in rows:
            stats = period_stats.get(int(row.period_id))
            if not stats:
                continue
            amount = int(row.amount or 0)
            count = int(row.count or 0)
            if row.entry_type == ENTRY_TYPE_DELIVERY_FEE:
                stats["delivery_total_cents"] = amount
            elif row.entry_type == ENTRY_TYPE_SUBSCRIPTION:
                stats["subscription_total_cents"] = amount
            elif row.entry_type == ENTRY_TYPE_RENTAL_COMMISSION:
                stats["rental_total_cents"] = amount
            stats["entry_count"] += count

        for stats in period_stats.values():
            stats["total_cents"] = int(
                stats["delivery_total_cents"]
                + stats["subscription_total_cents"]
                + stats["rental_total_cents"]
            )

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
        selected_totals = compute_period_totals(selected_period.id)

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
    if selected_period_id is not None:
        entries_query = entries_query.filter(FinancialEntry.period_id == selected_period_id)
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
    delete_message = ""
    delete_available_at = None
    if selected_period is not None:
        delete_allowed, delete_message, delete_available_at = financial_period_delete_guard(selected_period)

    entry_type_labels = {
        ENTRY_TYPE_DELIVERY_FEE: "Livraison (Part Baba)",
        ENTRY_TYPE_SUBSCRIPTION: "Abonnement",
        ENTRY_TYPE_RENTAL_COMMISSION: "Location (commission)",
    }

    return render_template(
        "admin/finance.html",
        periods=periods,
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
        retention_days=FINANCIAL_PERIOD_DELETE_RETENTION_DAYS,
    )


@bp.route("/finance/periods/open", methods=["POST"])
def finance_period_open():
    name = (request.form.get("name") or "").strip()
    start_date = _parse_iso_date(request.form.get("start_date"))
    end_date = _parse_iso_date(request.form.get("end_date"))
    if start_date is None or end_date is None:
        flash("Dates invalides. Format attendu: YYYY-MM-DD.", "warning")
        return redirect(url_for("admin.finance"))

    try:
        period = create_financial_period(name=name or None, start_date=start_date, end_date=end_date)
        db.session.commit()
        log_access(
            "financial_period_open",
            "financial_period",
            period.id,
            success=True,
            changes={
                "name": period.name,
                "start_date": period.start_date.isoformat(),
                "end_date": period.end_date.isoformat(),
            },
        )
        flash(f"Periode financiere ouverte: {period.name}", "success")
        return redirect(url_for("admin.finance", period_id=period.id))
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec creation periode financiere: {exc}", "danger")
    return redirect(url_for("admin.finance"))


@bp.route("/finance/periods/<int:period_id>/close", methods=["POST"])
def finance_period_close(period_id: int):
    period = db.session.get(FinancialPeriod, period_id)
    if period is None:
        return render_template("errors/404.html"), 404
    if period.deleted_at is not None:
        flash("Cette periode est supprimee.", "warning")
        return redirect(url_for("admin.finance"))
    if period.status == FINANCIAL_PERIOD_CLOSED:
        flash("Cette periode financiere est deja fermee.", "info")
        return redirect(url_for("admin.finance", period_id=period.id))

    try:
        close_financial_period(period)
        db.session.commit()
        log_access(
            "financial_period_close",
            "financial_period",
            period.id,
            success=True,
            changes={
                "closed_at": period.closed_at.isoformat() if period.closed_at else None,
                "delivery_total_cents": period.delivery_total_cents,
                "subscription_total_cents": period.subscription_total_cents,
                "rental_total_cents": period.rental_total_cents,
                "total_cents": period.total_cents,
            },
        )
        flash(f"Periode fermee: {period.name}", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec fermeture periode financiere: {exc}", "danger")
    return redirect(url_for("admin.finance", period_id=period.id))


@bp.route("/finance/periods/<int:period_id>/delete", methods=["POST"])
def finance_period_delete(period_id: int):
    period = db.session.get(FinancialPeriod, period_id)
    if period is None:
        return render_template("errors/404.html"), 404
    if period.deleted_at is not None:
        flash("Cette periode est deja supprimee.", "warning")
        return redirect(url_for("admin.finance"))

    delete_confirm = (request.form.get("confirm_delete") or "").strip()
    admin_password = request.form.get("admin_password") or ""
    if delete_confirm != "DELETE":
        flash("Confirmation invalide. Tapez DELETE.", "warning")
        return redirect(url_for("admin.finance", period_id=period.id))
    if not current_user.check_password(admin_password):
        flash("Mot de passe admin invalide.", "danger")
        return redirect(url_for("admin.finance", period_id=period.id))

    allowed, message, _available_at = financial_period_delete_guard(period)
    if not allowed:
        flash(message or "Suppression refusee.", "warning")
        return redirect(url_for("admin.finance", period_id=period.id))

    try:
        removed_entries = (
            FinancialEntry.query
            .filter(FinancialEntry.period_id == period.id)
            .delete(synchronize_session=False)
        )
        db.session.delete(period)
        db.session.commit()
        log_access(
            "financial_period_delete",
            "financial_period",
            period_id,
            success=True,
            changes={"removed_entries": int(removed_entries or 0)},
        )
        flash(
            f"Periode #{period_id} supprimee avec {int(removed_entries or 0)} entree(s).",
            "success",
        )
        return redirect(url_for("admin.finance"))
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec suppression periode financiere: {exc}", "danger")
        return redirect(url_for("admin.finance", period_id=period.id))


@bp.route("/orders/<int:oid>/delete", methods=["POST"])
def delete_archived_order(oid: int):
    next_url = (request.args.get("next") or request.form.get("next") or "").strip()

    def _redirect_after_delete(default_endpoint: str = "admin.order_archives"):
        if next_url.startswith("/"):
            return redirect(next_url)
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

    status_filter = request.args.get("status", "")
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

    pending_query = (
        scoped_base.filter(Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS)))
        .options(
            selectinload(Order.courier),
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop),
        )
        .order_by(Order.created_at.desc())
    )
    pending_orders = pending_query.limit(25).all()

    delivered_recent_query = (
        scoped_base.filter(Order.delivery_status == "delivered")
        .filter(Order.delivered_at.is_(None) | (Order.delivered_at >= (now - timedelta(hours=72))))
    )
    delivered_recent_count = delivered_recent_query.count()
    total_baba_fee = (
        delivered_recent_query.with_entities(
            db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)
        ).scalar() or 0
    ) / 100

    history_query = _apply_delivery_filters(
        scoped_base,
        status_filter=status_filter,
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
            "status": status_filter or None,
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
            "detail_url": url_for("admin.order_detail", oid=order.id),
            "deliver_url": url_for("admin.mark_delivered", oid=order.id, next=next_url),
            "cancel_url": url_for("admin.cancel_order", oid=order.id, next=next_url),
            "assign_url": url_for("admin.assign_courier", oid=order.id, next=next_url),
            "call_url": f"tel:{order.phone}"
        }

    return jsonify(
        pending_count=scoped_base.filter(Order.delivery_status.in_(tuple(COURIER_DELIVERY_IN_PROGRESS))).count(),
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

    base_archived = _archived_orders_query()
    if period_id:
        base_archived = base_archived.filter(Order.period_id == period_id)
    if source_filter:
        base_archived = base_archived.filter(Order.delivery_source == source_filter)

    history_query = _apply_delivery_filters(
        base_archived,
        status_filter=status_filter,
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


# ======================
# MAINTENANCE SYSTEME
# ======================
@bp.route("/maintenance", methods=["GET"])
def maintenance():
    days = _parse_days(request.args.get("days"), default=6, minimum=1, maximum=365)
    errors_page = page_from_args(request.args, key="errors_page", default=1)
    context = _maintenance_view_context(days=days, errors_page=errors_page)
    return render_template("admin/maintenance.html", **context)


@bp.route("/maintenance/errors/<int:error_id>/delete", methods=["POST"])
def maintenance_error_delete(error_id: int):
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
    errors_page = page_from_args(request.form, key="errors_page", default=1)
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
    try:
        since = datetime.utcnow() - timedelta(hours=24)
        purged = (
            ErrorLog.query
            .filter(ErrorLog.status_code == 500, ErrorLog.created_at >= since)
            .delete(synchronize_session=False)
        )
        db.session.commit()
        flash(f"Erreurs 500 (24h) supprimees: {int(purged or 0)}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Echec purge erreurs 500 (24h): {exc}", "danger")
    return redirect(url_for("admin.maintenance", days=days, errors_page=errors_page))


@bp.route("/maintenance/mode/enable", methods=["POST"])
def maintenance_mode_enable():
    days = _parse_days(request.form.get("days"), default=6, minimum=1, maximum=365)
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