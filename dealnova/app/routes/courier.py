from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models.order import Order, OrderItem
from ..models.product import Product
from ..models.user import User
from ..services.delivery_context import enrich_orders_delivery_context
from ..services.financial_periods import record_delivery_fee_entry
from ..services.pagination import page_from_args


bp = Blueprint("courier", __name__, url_prefix="/courier")

IN_PROGRESS_STATUSES = {"new", "assigned", "picked_up", "delivering"}
COMPLETED_STATUSES = {"delivered", "canceled"}
ALLOWED_ACTION_STATUSES = {"picked_up", "delivering", "delivered"}


def _is_ajax_request() -> bool:
    return (
        request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )


def _get_courier_user() -> User | None:
    courier_id = getattr(current_user, "id", None)
    if not courier_id:
        return None
    return db.session.get(User, courier_id)


def _courier_account_is_active(courier: User | None) -> bool:
    if courier is None:
        return False
    return bool(courier.is_active and courier.courier_is_active)


def _today_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.utcnow()
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def _courier_baba_due_stats(courier_id: int) -> dict[str, int]:
    start, end = _today_bounds()
    base = (
        Order.query
        .filter(
            Order.courier_id == courier_id,
            Order.delivery_status == "delivered",
            Order.delivered_at.isnot(None),
            Order.delivered_at >= start,
            Order.delivered_at < end,
        )
    )

    due_q = base.filter(Order.baba_fee_settled_at.is_(None))
    settled_q = base.filter(Order.baba_fee_settled_at.isnot(None))

    due_cents = (
        due_q.with_entities(db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)).scalar() or 0
    )
    due_count = due_q.count()
    settled_cents = (
        settled_q.with_entities(db.func.coalesce(db.func.sum(Order.delivery_platform_fee_cents), 0)).scalar() or 0
    )
    settled_count = settled_q.count()
    return {
        "due_cents": int(due_cents or 0),
        "due_count": int(due_count or 0),
        "settled_cents": int(settled_cents or 0),
        "settled_count": int(settled_count or 0),
    }


@bp.before_request
@login_required
def restrict_courier():
    if (getattr(current_user, "role", "") or "").lower() != "courier":
        flash("Acces reserve aux livreurs.", "warning")
        return redirect(url_for("shop.home"))


@bp.route("/")
def panel_home():
    return redirect(url_for("courier.panel_deliveries"))


def _render_courier_deliveries(default_tab: str = "in_progress"):
    tab = (request.args.get("tab") or default_tab).strip().lower()
    if tab not in {"in_progress", "completed"}:
        tab = "in_progress"
    page = page_from_args(request.args)

    courier = _get_courier_user()
    courier_account_active = _courier_account_is_active(courier)
    courier_is_available = bool(courier.courier_is_available) if courier else False

    base_query = (
        Order.query
        .filter(Order.courier_id == current_user.id)
        .options(selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.shop))
        .order_by(Order.created_at.desc())
    )

    in_progress_count = base_query.filter(Order.delivery_status.in_(tuple(IN_PROGRESS_STATUSES))).count()
    completed_count = base_query.filter(Order.delivery_status.in_(tuple(COMPLETED_STATUSES))).count()

    scoped_query = (
        base_query.filter(Order.delivery_status.in_(tuple(COMPLETED_STATUSES)))
        if tab == "completed"
        else base_query.filter(Order.delivery_status.in_(tuple(IN_PROGRESS_STATUSES)))
    )
    pagination = scoped_query.paginate(page=page, per_page=30, error_out=False)
    orders = enrich_orders_delivery_context(pagination.items)

    return render_template(
        "courier/deliveries.html",
        orders=orders,
        pagination=pagination,
        tab=tab,
        in_progress_count=in_progress_count,
        completed_count=completed_count,
        courier_account_active=courier_account_active,
        courier_is_available=courier_is_available,
        courier_last_seen_at=(courier.courier_last_seen_at if courier else None),
        baba_today=_courier_baba_due_stats(current_user.id),
        notify_url="",
        password_change_window_active=(courier.password_change_window_active() if courier else False),
        password_change_allowed_until=(courier.password_change_allowed_until if courier else None),
    )


@bp.route("/orders")
def panel_orders():
    return _render_courier_deliveries(default_tab="in_progress")


@bp.route("/deliveries")
def panel_deliveries():
    return _render_courier_deliveries(default_tab="in_progress")


@bp.route("/password/change", methods=["POST"])
def change_password():
    courier = _get_courier_user()
    if courier is None:
        return redirect(url_for("courier.panel_deliveries"))

    if not courier.password_change_window_active():
        flash("Demandez a l'admin d'activer la fenetre de changement (20 min).", "warning")
        return redirect(url_for("courier.panel_deliveries"))

    current_password = (request.form.get("current_password") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()
    confirm_password = (request.form.get("confirm_password") or "").strip()

    if not current_password or not new_password or not confirm_password:
        flash("Tous les champs mot de passe sont obligatoires.", "warning")
        return redirect(url_for("courier.panel_deliveries"))
    if not courier.check_password(current_password):
        flash("Mot de passe actuel incorrect.", "danger")
        return redirect(url_for("courier.panel_deliveries"))
    if len(new_password) < 8:
        flash("Nouveau mot de passe trop court (min 8 caracteres).", "warning")
        return redirect(url_for("courier.panel_deliveries"))
    if new_password != confirm_password:
        flash("Confirmation mot de passe non correspondante.", "warning")
        return redirect(url_for("courier.panel_deliveries"))

    courier.set_password(new_password)
    courier.password_change_allowed_until = None
    courier.courier_last_seen_at = datetime.utcnow()
    db.session.commit()
    flash("Mot de passe mis a jour avec succes.", "success")
    return redirect(url_for("courier.panel_deliveries"))


@bp.route("/availability", methods=["POST"])
def toggle_availability():
    courier = _get_courier_user()
    next_url = (request.form.get("next") or request.args.get("next") or "").strip()

    def _redirect_default():
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("courier.panel_deliveries"))

    if not _courier_account_is_active(courier):
        message = "Compte inactif, contactez l'admin."
        if _is_ajax_request():
            return jsonify(success=False, message=message), 403
        flash(message, "warning")
        return _redirect_default()

    value = (request.form.get("available") or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        courier.courier_is_available = True
    elif value in {"0", "false", "no", "off"}:
        courier.courier_is_available = False
    else:
        courier.courier_is_available = not bool(courier.courier_is_available)

    courier.courier_last_seen_at = datetime.utcnow()
    db.session.commit()

    label = "Disponible" if courier.courier_is_available else "Indisponible"
    if _is_ajax_request():
        return jsonify(
            success=True,
            courier_id=courier.id,
            courier_is_available=bool(courier.courier_is_available),
            message=f"Statut mis a jour: {label}.",
        )
    flash(f"Statut mis a jour: {label}.", "success")
    return _redirect_default()


@bp.route("/deliveries/<int:oid>/status", methods=["POST"])
def update_delivery_status(oid: int):
    target_status = (request.form.get("delivery_status") or "").strip().lower()
    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    courier = _get_courier_user()

    if target_status not in ALLOWED_ACTION_STATUSES:
        if _is_ajax_request():
            return jsonify(success=False, message="Statut invalide."), 400
        flash("Statut invalide.", "warning")
        return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))

    if not _courier_account_is_active(courier):
        message = "Compte inactif, contactez l'admin."
        if _is_ajax_request():
            return jsonify(success=False, message=message), 403
        flash(message, "warning")
        return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))

    order = db.session.get(Order, oid)
    if order is None:
        return render_template("errors/404.html"), 404
    if order.courier_id != current_user.id:
        return render_template("errors/403.html"), 403
    if order.delivery_status == "canceled":
        if _is_ajax_request():
            return jsonify(success=False, message="Livraison annulee."), 400
        flash("Livraison annulee.", "warning")
        return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))
    if order.delivery_status == "delivered" and target_status != "delivered":
        if _is_ajax_request():
            return jsonify(success=False, message="Livraison deja finalisee."), 400
        flash("Livraison deja finalisee.", "warning")
        return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))
    if order.delivery_status == "delivered" and target_status == "delivered":
        if _is_ajax_request():
            return jsonify(success=True, order_id=order.id, delivery_status=order.delivery_status, status=order.status)
        flash(f"Livraison #{order.id} deja livree.", "info")
        return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))

    now = datetime.utcnow()

    if target_status == "picked_up":
        order.delivery_status = "picked_up"
        order.picked_up_at = now
        if order.assigned_at is None:
            order.assigned_at = now
        if order.status == "pending":
            order.status = "shipped"
    elif target_status == "delivering":
        order.delivery_status = "delivering"
        if order.assigned_at is None:
            order.assigned_at = now
        if order.picked_up_at is None:
            order.picked_up_at = now
        if order.status == "pending":
            order.status = "shipped"
    elif target_status == "delivered":
        order.delivery_status = "delivered"
        if order.assigned_at is None:
            order.assigned_at = now
        if order.picked_up_at is None:
            order.picked_up_at = now
        order.delivered_at = now
        order.status = "delivered"
        record_delivery_fee_entry(order, note="order delivered by courier")
        # Simple flow: courier is marked available again once delivery is done.
        if courier is not None:
            courier.courier_is_available = True

    if courier is not None:
        courier.courier_last_seen_at = now
    db.session.commit()

    if _is_ajax_request():
        return jsonify(
            success=True,
            order_id=order.id,
            delivery_status=order.delivery_status,
            status=order.status,
        )

    labels = {
        "picked_up": "Recuperee",
        "delivering": "En route",
        "delivered": "Livree",
    }
    flash(f"Livraison #{order.id} mise a jour: {labels.get(target_status, target_status)}.", "success")
    return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))


@bp.route("/deliveries/<int:oid>/settle-baba", methods=["POST"])
def settle_baba_fee(oid: int):
    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    courier = _get_courier_user()
    if not _courier_account_is_active(courier):
        if _is_ajax_request():
            return jsonify(success=False, message="Compte inactif, contactez l'admin."), 403
        flash("Compte inactif, contactez l'admin.", "warning")
        return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))

    order = db.session.get(Order, oid)
    if order is None:
        return render_template("errors/404.html"), 404
    if order.courier_id != current_user.id:
        return render_template("errors/403.html"), 403
    if order.delivery_status != "delivered":
        if _is_ajax_request():
            return jsonify(success=False, message="Remise Baba possible uniquement sur une livraison livree."), 400
        flash("Remise Baba possible uniquement sur une livraison livree.", "warning")
        return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))
    if order.baba_fee_settled_at is not None:
        if _is_ajax_request():
            return jsonify(success=True, message="Deja marquee comme remise."), 200
        flash("Cette livraison est deja marquee comme remise.", "info")
        return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))

    now = datetime.utcnow()
    order.baba_fee_settled_at = now
    order.baba_fee_settled_by_user_id = current_user.id
    if courier is not None:
        courier.courier_last_seen_at = now
    db.session.commit()

    if _is_ajax_request():
        return jsonify(success=True, message="Remise Baba confirmee.", order_id=order.id), 200
    flash("Remise Baba confirmee.", "success")
    return redirect(next_url if next_url.startswith("/") else url_for("courier.panel_deliveries"))
