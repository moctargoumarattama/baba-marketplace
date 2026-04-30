# app/routes/admin_users.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from ..extensions import db
from ..models.user import User
from ..models.shop import (
    SHOP_TYPE_LABELS,
    SHOP_TYPE_ORDER,
    Shop,
    normalize_allowed_shop_types,
    normalize_shop_type,
)
from ..models.product import Product
from ..models.order import Order, OrderItem
from ..models.audit import AuditLog
from ..models.blocked import BlockedContact
from ..models.product_contact_lead import ProductContactLead
from ..models.platform_settings import PlatformSettings
from ..models.subscription_payment import SubscriptionPayment
from ..services.logging_service import logging_service
from ..services.cache import bump_catalog_version, cache
from ..services.audit import log_access
from ..services.date_filters import resolve_date_filter
from ..services.finance_entries import record_subscription_entry
from ..services.pagination import normalize_limit, page_from_args
from ..services.traffic_stats import get_live_traffic_metrics
from datetime import datetime, timedelta
from sqlalchemy.orm import selectinload, load_only
from sqlalchemy import or_, and_
from sqlalchemy.exc import SQLAlchemyError  # ✅ AJOUT
import secrets
import re
import string
from slugify import slugify

bp = Blueprint("admin_users", __name__, url_prefix="/admin")

_MEMORABLE_PASSWORD_WORDS = [
    "atlas", "cacao", "cafe", "citron", "dune", "epice", "figue", "fleur",
    "hiver", "kiwi", "lune", "mango", "miel", "moka", "nacre", "ninja",
    "olive", "panda", "perle", "pomme", "sable", "safran", "salon", "soleil",
    "tacos", "tango", "the", "tomate", "turbo", "vague", "vanille", "zeste",
    "azur", "basil", "beige", "bento", "boute", "carte", "cedre", "coton",
    "dakar", "delta", "dinar", "droid", "gala", "givre", "glace", "goutte",
    "honey", "jade", "karma", "lilas", "lotus", "lucky", "marron", "mystic",
    "nebula", "nova", "onze", "pique", "pixel", "pulse", "qamar", "rabat",
    "sakura", "satin", "smile", "sonic", "spray", "sucre", "tapis", "tempo",
]

ADMIN_ROLE = "admin"
MANAGER_ROLE = "manager"
STAFF_VISIBLE_TO_MANAGER_ROLES = ("vendor",)
ALLOWED_USER_ROLES = (ADMIN_ROLE, MANAGER_ROLE, "vendor")
MANAGER_BLOCKED_ENDPOINTS = {
    "admin_users.view_logs",
    "admin_users.audit_logs",
    "admin_users.fraud_monitor",
    "admin_users.fraud_block",
    "admin_users.fraud_unblock",
}
FRAUD_MAX_ROWS_DEFAULT = 80
FRAUD_MAX_ROWS_CAP = 200
ADMIN_METRICS_CACHE_TTL_SHORT = 20
ADMIN_METRICS_CACHE_TTL_MEDIUM = 30
PASSWORD_CHANGE_WINDOW_MINUTES = 20
RESERVED_ROOT_SHOP_SLUGS = {
    "admin",
    "admin-access",
    "api",
    "booking",
    "cart",
    "delivery",
    "health",
    "lang",
    "location",
    "locations",
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


# Dictionnaire pour les verrous (optionnel)
_cache_locks = {}

def _cache_get_or_build(key: str, timeout: int, builder, use_lock: bool = False):
    """Récupère du cache ou construit la valeur"""
    try:
        cached = cache.get(key)
        if cached is not None:
            return cached
    except Exception:
        pass

    if use_lock:
        # Version avec verrou (évite les doubles calculs)
        import threading
        lock = _cache_locks.setdefault(key, threading.Lock())
        with lock:
            # Vérifier une deuxième fois
            try:
                cached = cache.get(key)
                if cached is not None:
                    return cached
            except Exception:
                pass

            value = builder()
            try:
                cache.set(key, value, timeout=max(1, int(timeout)))
            except Exception:
                pass
            return value
    else:
        # Version simple
        value = builder()
        try:
            cache.set(key, value, timeout=max(1, int(timeout)))
        except Exception:
            pass
        return value


def _normalize_user_role(raw_role):
    role = (raw_role or "").strip().lower()
    return role if role in ALLOWED_USER_ROLES else ""


def _current_admin_role() -> str:
    return (getattr(current_user, "role", "") or "").strip().lower()


def _is_full_admin() -> bool:
    return _current_admin_role() == ADMIN_ROLE


def _is_manager() -> bool:
    return _current_admin_role() == MANAGER_ROLE


def _visible_user_roles_for_current_user() -> tuple[str, ...]:
    if _is_manager():
        return STAFF_VISIBLE_TO_MANAGER_ROLES
    return ALLOWED_USER_ROLES


def _manageable_user_roles_for_current_user() -> tuple[str, ...]:
    if _is_manager():
        return STAFF_VISIBLE_TO_MANAGER_ROLES
    return ALLOWED_USER_ROLES


def _users_query_visible_to_current_user():
    return User.query.filter(User.role.in_(_visible_user_roles_for_current_user()))


def _manager_hidden_user(user: User | None) -> bool:
    if user is None:
        return False
    role = (user.role or "").lower()
    if role not in ALLOWED_USER_ROLES:
        return True
    return bool(_is_manager() and role not in STAFF_VISIBLE_TO_MANAGER_ROLES)


def _hidden_user_response():
    if _is_ajax_request():
        return jsonify(success=False, message="Utilisateur introuvable."), 404
    return render_template("errors/404.html"), 404


def _forbidden_sensitive_admin_response():
    message = "Accès réservé aux administrateurs principaux."
    if _is_ajax_request():
        return jsonify(success=False, message=message), 403
    flash(message, "danger")
    return redirect(url_for("admin_users.admin_dashboard"))


def _shop_types_from_form():
    primary_type = normalize_shop_type(request.form.get("primary_type")) or "products"
    allowed_raw = request.form.getlist("allowed_types")
    if request.form.get("allow_all_types") == "1":
        allowed_raw = list(SHOP_TYPE_ORDER)
    allowed_types = normalize_allowed_shop_types(allowed_raw, primary_type=primary_type)
    return primary_type, allowed_types


def _sanitize_shop_slug(raw_value: str | None, fallback_name: str | None = None) -> str:
    candidate = slugify((raw_value or "").strip())
    if not candidate and fallback_name:
        candidate = slugify((fallback_name or "").strip())
    return candidate


def _build_unique_shop_slug(name: str, *, exclude_shop_id: int | None = None) -> str:
    base_slug = _sanitize_shop_slug(None, fallback_name=name) or "boutique"
    slug = base_slug
    counter = 1

    while True:
        query = Shop.query.filter_by(slug=slug)
        if exclude_shop_id is not None:
            query = query.filter(Shop.id != exclude_shop_id)
        if not query.first():
            return slug

        slug = f"{base_slug}-{counter}"
        counter += 1
        if counter > 999:
            slug = f"{base_slug}-{int(datetime.utcnow().timestamp())}"


def _create_shop_for_vendor(
    vendor: User,
    *,
    name: str,
    description: str = "",
    contact_email: str = "",
    contact_phone: str = "",
    address: str = "",
    primary_type: str = "products",
    allowed_types: list[str] | None = None,
) -> Shop:
    normalized_primary = normalize_shop_type(primary_type) or "products"
    normalized_allowed = normalize_allowed_shop_types(allowed_types, primary_type=normalized_primary)

    shop = Shop(
        vendor_id=vendor.id,
        name=name.strip(),
        slug=_build_unique_shop_slug(name),
        description=(description or "").strip() or None,
        contact_email=(contact_email or "").strip() or vendor.email or None,
        contact_phone=(contact_phone or "").strip() or vendor.phone or None,
        address=(address or "").strip() or vendor.address or None,
        primary_type=normalized_primary,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    shop.set_allowed_types(normalized_allowed)

    db.session.add(shop)
    db.session.flush()

    Product.query.filter_by(vendor_id=vendor.id).update(
        {"shop_id": shop.id},
        synchronize_session=False,
    )
    return shop


def _generate_memorable_password() -> str:
    word1 = secrets.choice(_MEMORABLE_PASSWORD_WORDS)
    word2 = secrets.choice(_MEMORABLE_PASSWORD_WORDS)
    while word2 == word1:
        word2 = secrets.choice(_MEMORABLE_PASSWORD_WORDS)
    digits = f"{secrets.randbelow(10000):04d}"
    return f"{word1}-{word2}-{digits}"


def _is_ajax_request() -> bool:
    return (
        request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )


def _bool_arg(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


# ==================== MIDDLEWARE ADMIN ====================
@bp.before_request
@login_required
def restrict_to_admin():
    """Vérifie que l'utilisateur est admin"""
    role = _current_admin_role()

    if role in {ADMIN_ROLE, MANAGER_ROLE}:
        return None

    flash("Accès réservé aux administrateurs", "danger")
    return redirect(url_for("shop.home"))


@bp.before_request
def restrict_sensitive_pages_for_manager():
    if _is_manager() and request.endpoint in MANAGER_BLOCKED_ENDPOINTS:
        return _forbidden_sensitive_admin_response()


def _dashboard_activity_snapshot(days: int = 7, date_filter=None) -> dict:
    since = date_filter.start_at if date_filter else datetime.utcnow() - timedelta(days=days)
    until = date_filter.end_at if date_filter else None

    settings = PlatformSettings.get()
    try:
        low_stock_threshold = int(settings.low_stock_threshold or 5)
    except (TypeError, ValueError):
        low_stock_threshold = 5
    if low_stock_threshold < 0:
        low_stock_threshold = 0

    range_cache_part = (
        f"{date_filter.range_filter}:{date_filter.start_at.isoformat()}:{date_filter.end_at.isoformat()}"
        if date_filter
        else f"days:{days}"
    )
    metrics_cache_key = f"admin:dashboard:contacts:v2:{range_cache_part}:{low_stock_threshold}"

    def _build_metrics():
        contacts_recent = ProductContactLead.query.filter(
            ProductContactLead.source == "product_whatsapp",
            ProductContactLead.created_at >= since,
        )
        if until is not None:
            contacts_recent = contacts_recent.filter(ProductContactLead.created_at < until)
        contact_phones_count = (
            db.session.query(ProductContactLead.client_phone)
            .filter(
                ProductContactLead.source == "product_whatsapp",
                ProductContactLead.created_at >= since,
                ProductContactLead.client_phone.isnot(None),
                ProductContactLead.client_phone != "",
            )
        )
        if until is not None:
            contact_phones_count = contact_phones_count.filter(ProductContactLead.created_at < until)
        contact_phones_count = contact_phones_count.distinct().count()
        contacted_shops_count = (
            db.session.query(ProductContactLead.shop_id)
            .filter(
                ProductContactLead.source == "product_whatsapp",
                ProductContactLead.created_at >= since,
                ProductContactLead.shop_id.isnot(None),
            )
        )
        if until is not None:
            contacted_shops_count = contacted_shops_count.filter(ProductContactLead.created_at < until)
        contacted_shops_count = contacted_shops_count.distinct().count()
        contacts_estimated_total = (
            contacts_recent.with_entities(db.func.coalesce(db.func.sum(ProductContactLead.estimated_total), 0)).scalar()
            or 0
        )
        return {
            "contacts_recent_count": int(contacts_recent.count() or 0),
            "contact_phones_count": int(contact_phones_count or 0),
            "contacted_shops_count": int(contacted_shops_count or 0),
            "contacts_estimated_total_cents": int(contacts_estimated_total or 0),
            "unverified_count": int(Shop.query.filter(Shop.sql_is_incomplete_clause()).count() or 0),
            "vendors_without_shop_count": int(
                User.query.filter_by(role="vendor").filter(~User.id.in_(db.session.query(Shop.vendor_id))).count()
                or 0
            ),
            "low_stock_count": int(
                Product.query.filter(Product.is_active == True, Product.stock <= low_stock_threshold).count() or 0
            ),
        }

    metrics = _cache_get_or_build(metrics_cache_key, ADMIN_METRICS_CACHE_TTL_SHORT, _build_metrics)

    snapshot = dict(metrics)
    snapshot.update(
        {
            "activity_days": days,
            "low_stock_threshold": low_stock_threshold,
            "recent_product_contacts": (
                ProductContactLead.query
                .options(selectinload(ProductContactLead.shop))
                .filter(
                    ProductContactLead.source == "product_whatsapp",
                    ProductContactLead.created_at >= since,
                    *((ProductContactLead.created_at < until,) if until is not None else ()),
                )
                .order_by(ProductContactLead.created_at.desc())
                .limit(8)
                .all()
            ),
            "unverified_shops": (
                Shop.query
                .options(selectinload(Shop.vendor))
                .filter(Shop.sql_is_incomplete_clause())
                .order_by(Shop.created_at.desc())
                .limit(8)
                .all()
            ),
            "vendors_without_shop_list": (
                User.query.filter_by(role="vendor")
                .filter(~User.id.in_(db.session.query(Shop.vendor_id)))
                .order_by(User.created_at.desc())
                .limit(8)
                .all()
            ),
            "low_stock_products": (
                Product.query.filter(Product.is_active == True, Product.stock <= low_stock_threshold)
                .order_by(Product.stock.asc())
                .limit(8)
                .all()
            ),
        }
    )
    return snapshot

# ==================== DASHBOARD ADMIN ====================
@bp.route("/")
def admin_dashboard():
    """Dashboard admin principal"""
    date_filter = resolve_date_filter(request.args, default="month")

    # Statistiques (short cache to reduce repeated aggregate cost).
    cards = _cache_get_or_build(
        f"admin:dashboard:cards:v1:{_current_admin_role() or 'staff'}",
        ADMIN_METRICS_CACHE_TTL_SHORT,
        lambda: {
            "total_users": User.query.filter(User.role.in_(ALLOWED_USER_ROLES)).count(),
            "total_visible_users": _users_query_visible_to_current_user().count(),
            "total_vendors": User.query.filter_by(role="vendor").count(),
            "total_managers": User.query.filter_by(role=MANAGER_ROLE).count(),
            "total_shops": Shop.query.count(),
            "total_products": Product.query.count(),
            "vendors_without_shop": User.query.filter_by(role="vendor").filter(
                ~User.id.in_(db.session.query(Shop.vendor_id))
            ).count(),
        },
    )
    total_users = int(cards.get("total_visible_users" if _is_manager() else "total_users", 0) or 0)
    total_vendors = int(cards.get("total_vendors", 0) or 0)
    total_managers = int(cards.get("total_managers", 0) or 0)
    total_shops = int(cards.get("total_shops", 0) or 0)
    total_products = int(cards.get("total_products", 0) or 0)
    total_product_contacts = int(
        ProductContactLead.query
        .filter(
            ProductContactLead.source == "product_whatsapp",
            ProductContactLead.created_at >= date_filter.start_at,
            ProductContactLead.created_at < date_filter.end_at,
        )
        .count() or 0
    )
    vendors_without_shop = int(cards.get("vendors_without_shop", 0) or 0)

    # Utilisateurs récents
    recent_users = (
        _users_query_visible_to_current_user()
        .order_by(User.created_at.desc())
        .limit(10)
        .all()
    )

    # Boutiques récentes
    recent_shops = Shop.query.order_by(Shop.created_at.desc()).limit(10).all()
    activity_snapshot = _dashboard_activity_snapshot(date_filter=date_filter)
    live_traffic = get_live_traffic_metrics()

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_vendors=total_vendors,
        total_shops=total_shops,
        total_products=total_products,
        total_product_contacts=total_product_contacts,
        vendors_without_shop=vendors_without_shop,
        total_managers=total_managers,
        range_filter=date_filter.range_filter,
        date_range_label=date_filter.label,
        date_from=date_filter.date_from,
        date_to=date_filter.date_to,
        recent_users=recent_users,
        recent_shops=recent_shops,
        live_traffic=live_traffic,
        **activity_snapshot,
    )

@bp.route("/audience")
def audience_dashboard():
    if _current_admin_role() not in {ADMIN_ROLE, MANAGER_ROLE}:
        return render_template("errors/403.html"), 403
    live_traffic = get_live_traffic_metrics()
    return render_template("admin/audience.html", live_traffic=live_traffic)


@bp.route("/audience/live")
def audience_dashboard_live():
    if _current_admin_role() not in {ADMIN_ROLE, MANAGER_ROLE}:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return jsonify(
        ok=True,
        live_traffic=get_live_traffic_metrics(),
        generated_at=datetime.utcnow().isoformat() + "Z",
    )

# ==================== GESTION UTILISATEURS ====================
@bp.route("/users")
def manage_users():
    """Gérer tous les utilisateurs"""
    page = page_from_args(request.args)
    role_filter = _normalize_user_role(request.args.get('role', ''))
    search = request.args.get('search', '')

    visible_roles = _visible_user_roles_for_current_user()
    if role_filter and role_filter not in visible_roles:
        role_filter = ''

    query = _users_query_visible_to_current_user()

    # Filtres
    if role_filter:
        query = query.filter_by(role=role_filter)

    if search:
        query = query.filter(
            db.or_(
                User.username.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%'),
                User.full_name.ilike(f'%{search}%')
            )
        )

    # Pagination
    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )

    users = pagination.items
    # Statistiques par rôle
    roles_stats = {
        'vendor': User.query.filter_by(role='vendor').count(),
        'admin': User.query.filter_by(role=ADMIN_ROLE).count() if _is_full_admin() else 0,
        'manager': User.query.filter_by(role=MANAGER_ROLE).count() if _is_full_admin() else 0,
    }

    return render_template(
        "admin/users.html",
        users=users,
        pagination=pagination,
        role_filter=role_filter,
        search=search,
        roles_stats=roles_stats
    )

@bp.route("/user/<int:user_id>")
def user_detail(user_id):
    """Détail d'un utilisateur"""
    user = User.query.get_or_404(user_id)
    if _manager_hidden_user(user):
        return _hidden_user_response()

    # Boutique de l'utilisateur (si vendeur)
    shop = None
    if user.role == 'vendor':
        shop = Shop.query.filter_by(vendor_id=user.id).first()

    product_count = 0
    if user.role == 'vendor':
        product_count = Product.query.filter_by(vendor_id=user.id).count()

    return render_template(
        "admin/user_detail.html",
        user=user,
        shop=shop,
        product_count=product_count,
        password_change_window_active=user.password_change_window_active(),
        password_change_allowed_until=user.password_change_allowed_until,
        password_change_window_minutes=PASSWORD_CHANGE_WINDOW_MINUTES,
    )

@bp.route("/user/<int:user_id>/update", methods=["POST"])
def update_user(user_id):
    """Mettre à jour un utilisateur"""
    user = User.query.get_or_404(user_id)
    if _manager_hidden_user(user):
        return _hidden_user_response()

    before = {
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "address": user.address,
        "role": user.role,
    }

    # Mettre à jour les informations
    username = (request.form.get('username') or '').strip()
    if username:
        if not re.fullmatch(r"[a-zA-Z0-9_]{3,50}", username):
            flash("Nom d'utilisateur invalide. Utilisez 3 à 50 caractères.", "danger")
            return redirect(url_for('admin_users.user_detail', user_id=user.id))
        existing = User.query.filter(User.username == username, User.id != user.id).first()
        if existing:
            flash("Nom d'utilisateur déjà utilisé.", "danger")
            return redirect(url_for('admin_users.user_detail', user_id=user.id))
        user.username = username

    effective_role = user.role
    requested_role = None
    if request.form.get('role'):
        requested_role = _normalize_user_role(request.form.get('role'))
        allowed_roles = _manageable_user_roles_for_current_user()
        if not requested_role or requested_role not in allowed_roles:
            flash(f"Rôle invalide. Rôles autorisés : {', '.join(allowed_roles)}.", "danger")
            return redirect(url_for('admin_users.user_detail', user_id=user.id))
        effective_role = requested_role

    if effective_role != "vendor" and request.form.get('full_name'):
        user.full_name = request.form['full_name']

    if request.form.get('email'):
        email = request.form['email'].strip()
        existing_email = User.query.filter(User.email == email, User.id != user.id).first()
        if existing_email:
            flash("E-mail déjà utilisé.", "danger")
            return redirect(url_for('admin_users.user_detail', user_id=user.id))
        user.email = email

    if effective_role != "vendor" and request.form.get('phone'):
        user.phone = request.form['phone']

    if effective_role != "vendor" and request.form.get('address'):
        user.address = request.form['address']

    if effective_role == "vendor":
        user.full_name = None
        user.phone = None
        user.address = None

    if requested_role:
        user.role = requested_role
    db.session.commit()
    changed_fields = [k for k, v in before.items() if getattr(user, k) != v]
    if changed_fields:
        log_access(
            "update_user",
            "user",
            user.id,
            success=True,
            changes={"fields": changed_fields}
        )
    flash(f"Utilisateur {user.username} mis à jour", "success")
    return redirect(url_for('admin_users.user_detail', user_id=user.id))

@bp.route("/user/<int:user_id>/reset-password", methods=["POST"])
def reset_user_password(user_id):
    """Réinitialiser le mot de passe d'un utilisateur"""
    user = User.query.get_or_404(user_id)
    if _manager_hidden_user(user):
        return _hidden_user_response()

    # Générer un mot de passe temporaire (plus facile à retenir pour les vendeurs)
    if getattr(user, "role", None) == "vendor":
        temp_password = _generate_memorable_password()
    else:
        alphabet = string.ascii_letters + string.digits
        temp_password = ''.join(secrets.choice(alphabet) for i in range(12))

    user.set_password(temp_password)
    db.session.commit()

    log_access(
        "reset_password",
        "user",
        user.id,
        success=True
    )

    if _is_ajax_request():
        return jsonify(success=True, user_id=user.id, temp_password=temp_password)

    flash(f"Mot de passe réinitialisé pour {user.username}. Nouveau mot de passe: {temp_password}", "warning")
    return redirect(url_for('admin_users.user_detail', user_id=user.id))

@bp.route("/user/<int:user_id>/password-change-window", methods=["POST"])
def set_user_password_change_window(user_id):
    user = User.query.get_or_404(user_id)
    if _manager_hidden_user(user):
        return _hidden_user_response()
    if user.role != "vendor":
        if _is_ajax_request():
            return jsonify(success=False, message="Action réservée aux vendeurs."), 400
        flash("Action réservée aux vendeurs.", "warning")
        return redirect(url_for("admin_users.user_detail", user_id=user.id))

    enable = _bool_arg(request.form.get("enable", "1"))
    if enable:
        user.password_change_allowed_until = datetime.utcnow() + timedelta(minutes=PASSWORD_CHANGE_WINDOW_MINUTES)
        message = (
            f"Changement mot de passe activé {PASSWORD_CHANGE_WINDOW_MINUTES} min pour {user.username}."
        )
    else:
        user.password_change_allowed_until = None
        message = f"Changement mot de passe désactivé pour {user.username}."

    db.session.commit()
    log_access(
        "set_password_change_window",
        "user",
        user.id,
        success=True,
        changes={
            "enabled": bool(enable),
            "until": (
                user.password_change_allowed_until.isoformat()
                if user.password_change_allowed_until
                else None
            ),
        },
    )

    if _is_ajax_request():
        return jsonify(
            success=True,
            user_id=user.id,
            enabled=bool(user.password_change_window_active()),
            until=(
                user.password_change_allowed_until.isoformat()
                if user.password_change_allowed_until
                else None
            ),
            message=message,
        )

    flash(message, "success")
    return redirect(url_for("admin_users.user_detail", user_id=user.id))


@bp.route("/user/<int:user_id>/toggle-active", methods=["POST"])
def toggle_user_active(user_id):
    """Activer/désactiver un utilisateur"""
    user = User.query.get_or_404(user_id)
    if _manager_hidden_user(user):
        return _hidden_user_response()

    # Empêcher l'admin de se désactiver lui-même (optionnel mais recommandé)
    if user.id == current_user.id:
        if _is_ajax_request():
            return jsonify(success=False, message="Vous ne pouvez pas désactiver votre propre compte."), 400
        flash("Vous ne pouvez pas désactiver votre propre compte.", "danger")
        return redirect(url_for('admin_users.user_detail', user_id=user.id))

    # Inverser le statut
    user.is_active = not user.is_active

    db.session.commit()

    # Log de l'action
    log_access(
        "toggle_user_active",
        "user",
        user.id,
        success=True,
        changes={"is_active": user.is_active}
    )

    # Réponse AJAX ou redirection
    if _is_ajax_request():
        return jsonify(
            success=True,
            user_id=user.id,
            is_active=user.is_active,
            message=f"Utilisateur {'activé' if user.is_active else 'désactivé'}"
        )

    status = "activé" if user.is_active else "désactivé"
    flash(f"Utilisateur {user.username} {status}", "success")
    return redirect(url_for('admin_users.user_detail', user_id=user.id))


@bp.route("/user/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    """Supprimer un utilisateur"""
    user = User.query.get_or_404(user_id)
    if _manager_hidden_user(user):
        return _hidden_user_response()

    # Vérifier si l'utilisateur a des dépendances
    if user.role == 'vendor':
        shop = Shop.query.filter_by(vendor_id=user.id).first()
        if shop:
            if _is_ajax_request():
                return jsonify(success=False, message="Suppression impossible : cet utilisateur a une boutique."), 400
            flash("Suppression impossible : cet utilisateur a une boutique.", "danger")
            return redirect(url_for('admin_users.user_detail', user_id=user.id))

    log_access(
        "delete_user",
        "user",
        user.id,
        success=True,
        changes={"username": user.username, "role": user.role}
    )
    db.session.delete(user)
    db.session.commit()

    if _is_ajax_request():
        return jsonify(success=True, user_id=user.id, redirect_url=url_for('admin_users.manage_users'))

    flash(f"Utilisateur {user.username} supprimé", "success")
    return redirect(url_for('admin_users.manage_users'))

# ==================== CRÉATION UTILISATEUR ====================
@bp.route("/user/create", methods=["GET", "POST"])
def create_user():
    """Créer un nouvel utilisateur"""
    if request.method == 'POST':
        try:
            # Récupération des champs
            username = request.form['username'].strip()
            email = request.form['email'].strip()
            password = request.form['password'].strip()
            role = _normalize_user_role(request.form.get('role'))
            full_name = request.form.get('full_name', '').strip()
            phone = request.form.get('phone', '').strip()
            address = request.form.get('address', '').strip()
            allowed_roles = _manageable_user_roles_for_current_user()
            shop = None
            shop_name = ""
            primary_type = "products"
            allowed_types = ["products"]

            # Validation rôle
            if not role or role not in allowed_roles:
                flash("Rôle invalide. Rôles autorisés: admin, manager, vendor.", "danger")
                return redirect(url_for('admin_users.create_user'))

            # Validation mot de passe
            if len(password) < 8:
                flash("Le mot de passe doit contenir au moins 8 caractères.", "danger")
                return redirect(url_for('admin_users.create_user'))

            # Validation email basique
            if '@' not in email or '.' not in email:
                flash("Email invalide.", "danger")
                return redirect(url_for('admin_users.create_user'))

            # Vérifier si l'utilisateur existe déjà
            if User.query.filter_by(username=username).first():
                flash("Nom d'utilisateur déjà utilisé", "danger")
                return redirect(url_for('admin_users.create_user'))

            if User.query.filter_by(email=email).first():
                flash("Email déjà utilisé", "danger")
                return redirect(url_for('admin_users.create_user'))

            # Créer l'utilisateur

            if role == "vendor":
                shop_name = request.form.get("shop_name", "").strip()
                if not shop_name:
                    flash("Le nom de la boutique est obligatoire pour un vendeur.", "danger")
                    return redirect(url_for('admin_users.create_user'))
                try:
                    primary_type, allowed_types = _shop_types_from_form()
                except Exception:
                    current_app.logger.exception("create_user.shop_types_error")
                    flash("Type de boutique invalide.", "danger")
                    return redirect(url_for('admin_users.create_user'))
                full_name = ""
                phone = ""
                address = ""

            user = User(
                username=username,
                email=email,
                role=role,
                full_name=full_name,
                phone=phone,
                address=address,
                created_at=datetime.utcnow()
            )
            user.set_password(password)

            db.session.add(user)
            db.session.flush()  # Pour obtenir l'ID

            if role == "vendor":
                shop = _create_shop_for_vendor(
                    user,
                    name=shop_name,
                    primary_type=primary_type,
                    allowed_types=allowed_types,
                )

            db.session.commit()

            # Logger la création d'utilisateur
            logging_service.log_activity(
                'admin', 'create_user',
                user=current_user,
                resource_type='user',
                resource_id=user.id,
                message=f"Administrateur {current_user.username} a créé l'utilisateur {username} (rôle: {role})"
            )
            log_access(
                "create_user",
                "user",
                user.id,
                success=True,
                changes={"role": role, "username": username}
            )

            if shop is not None:
                try:
                    log_access(
                        "create_shop",
                        "shop",
                        shop.id,
                        success=True,
                        changes={"name": shop.name, "vendor_id": user.id, "source": "create_user"}
                    )
                except Exception:
                    current_app.logger.warning(
                        "create_user.shop_audit_log_failed",
                        extra={"user_id": user.id, "shop_id": shop.id},
                    )
                flash(f"Utilisateur {username} et boutique {shop.name} créés avec succès.", "success")
                return redirect(url_for('admin_users.user_detail', user_id=user.id))

            if role == "vendor" and shop is None:
                flash(f"Utilisateur {username} créé avec succès. La boutique doit être créée séparément.", "success")
            else:
                flash(f"Utilisateur {username} créé avec succès", "success")
            return redirect(url_for('admin_users.user_detail', user_id=user.id))

        except Exception as e:
            db.session.rollback()
            # Ne pas exposer les détails techniques en production
            if current_app.debug:
                flash(f"Erreur: {str(e)}", "danger")
            else:
                flash("Erreur lors de la création de l'utilisateur.", "danger")

    return render_template(
        "admin/create_user.html",
        manageable_roles=_manageable_user_roles_for_current_user(),
        shop_type_order=SHOP_TYPE_ORDER,
        shop_type_labels=SHOP_TYPE_LABELS,
    )
# ==================== GESTION BOUTIQUES ====================
@bp.route("/shops")
def manage_shops():
    """Gérer toutes les boutiques"""
    page = page_from_args(request.args)
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '')

    query = Shop.query

    # Filtres
    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'inactive':
        query = query.filter_by(is_active=False)

    if search:
        query = query.filter(
            db.or_(
                Shop.name.ilike(f'%{search}%'),
                Shop.description.ilike(f'%{search}%'),
                Shop.contact_email.ilike(f'%{search}%')
            )
        )

    # Jointure avec utilisateur pour obtenir le nom du vendeur
    query = query.join(User, Shop.vendor_id == User.id).add_entity(User)

    # Pagination
    pagination = query.order_by(Shop.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )

    shops_with_vendors = pagination.items

    return render_template(
        "admin/shops.html",
        shops_with_vendors=shops_with_vendors,
        pagination=pagination,
        status_filter=status_filter,
        search=search
    )

@bp.route("/shop/<int:shop_id>")
def shop_detail(shop_id):
    """Détail d'une boutique"""
    shop = Shop.query.get_or_404(shop_id)
    vendor = User.query.get(shop.vendor_id)

    return render_template(
        "admin/shop_detail.html",
        shop=shop,
        vendor=vendor,
        shop_type_order=SHOP_TYPE_ORDER,
        shop_type_labels=SHOP_TYPE_LABELS,
    )


@bp.route("/shop/<int:shop_id>/update", methods=["POST"])
def update_shop(shop_id):
    """Mettre à jour une boutique"""
    shop = Shop.query.get_or_404(shop_id)

    before = {
        "name": shop.name,
        "slug": shop.slug,
        "description": shop.description,
        "contact_email": shop.contact_email,
        "contact_phone": shop.contact_phone,
        "address": shop.address,
        "primary_type": shop.primary_type,
        "allowed_types_json": shop.allowed_types_json,
    }

    if request.form.get('name'):
        shop.name = request.form['name'].strip()

    slug_input = request.form.get("slug", "")
    new_slug = _sanitize_shop_slug(slug_input, fallback_name=shop.name)
    if not new_slug:
        flash("Slug invalide.", "warning")
        return redirect(url_for('admin_users.shop_detail', shop_id=shop.id))
    if new_slug in RESERVED_ROOT_SHOP_SLUGS:
        flash("Ce slug est réservé. Choisissez un autre slug.", "warning")
        return redirect(url_for('admin_users.shop_detail', shop_id=shop.id))
    if new_slug != shop.slug:
        counter = 1
        original_slug = new_slug
        while Shop.query.filter(Shop.slug == new_slug, Shop.id != shop.id).first():
            new_slug = f"{original_slug}-{counter}"
            counter += 1
        shop.slug = new_slug

    if request.form.get('description'):
        shop.description = request.form['description']

    if request.form.get('contact_email'):
        shop.contact_email = request.form['contact_email']

    if request.form.get('contact_phone'):
        shop.contact_phone = request.form['contact_phone']

    if request.form.get('address'):
        shop.address = request.form['address']

    if request.form.get("primary_type") is not None or request.form.getlist("allowed_types") or request.form.get("allow_all_types"):
        primary_type, allowed_types = _shop_types_from_form()
        shop.primary_type = primary_type
        shop.set_allowed_types(allowed_types)

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

    flash(f"Boutique {shop.name} mise à jour", "success")
    return redirect(url_for('admin_users.shop_detail', shop_id=shop.id))

@bp.route("/shop/<int:shop_id>/toggle", methods=["POST"])
def toggle_shop(shop_id):
    """Activer/désactiver une boutique"""
    shop = Shop.query.get_or_404(shop_id)
    shop.is_active = not shop.is_active

    # Désactiver aussi les produits si la boutique est désactivée
    if not shop.is_active:
        products = Product.query.filter_by(shop_id=shop.id).all()
        for product in products:
            product.is_active = False

    db.session.commit()
    bump_catalog_version()
    log_access(
        "toggle_shop",
        "shop",
        shop.id,
        success=True,
        changes={"is_active": shop.is_active}
    )

    status = "activée" if shop.is_active else "désactivée"
    if _is_ajax_request():
        return jsonify(success=True, shop_id=shop.id, is_active=shop.is_active)

    flash(f"Boutique {shop.name} {status}", "success")
    return redirect(url_for('admin_users.shop_detail', shop_id=shop.id))


@bp.route("/shop/<int:shop_id>/delete", methods=["POST"])
def delete_shop(shop_id):
    """Supprimer une boutique"""
    shop = Shop.query.get_or_404(shop_id)

    has_orders = (
        db.session.query(OrderItem.id)
        .join(Product, OrderItem.product_id == Product.id)
        .filter(Product.shop_id == shop.id)
        .first()
    )
    if has_orders:
        message = "Impossible de supprimer: la boutique a un historique produit legacy."
        if _is_ajax_request():
            return jsonify(success=False, message=message), 400
        flash(message, "danger")
        return redirect(url_for('admin_users.shop_detail', shop_id=shop.id))

    log_access(
        "delete_shop",
        "shop",
        shop.id,
        success=True,
        changes={"name": shop.name, "vendor_id": shop.vendor_id}
    )
    db.session.delete(shop)
    db.session.commit()

    if _is_ajax_request():
        return jsonify(success=True, shop_id=shop.id, redirect_url=url_for('admin_users.manage_shops'))

    flash(f"Boutique {shop.name} supprimée", "success")
    return redirect(url_for('admin_users.manage_shops'))


@bp.route("/shop/create", methods=["GET", "POST"])
def create_shop():
    """Créer une nouvelle boutique pour un vendeur existant"""
    if request.method == "POST":
        try:
            # ✅ Conversion explicite en int (évite les erreurs de type silencieuses)
            try:
                vendor_id = int(request.form["vendor_id"])
            except (KeyError, ValueError, TypeError):
                flash("Vendeur invalide.", "danger")
                return redirect(url_for("admin_users.create_shop"))

            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            contact_email = request.form.get("contact_email", "").strip()
            contact_phone = request.form.get("contact_phone", "").strip()
            address = request.form.get("address", "").strip()

            # Validation du nom
            if not name:
                flash("Le nom de la boutique est obligatoire.", "danger")
                return redirect(url_for("admin_users.create_shop"))

            # Récupération et validation du type de boutique
            try:
                primary_type, allowed_types = _shop_types_from_form()
            except Exception:
                current_app.logger.exception(
                    "create_shop.shop_types_error — vendor_id=%s", vendor_id
                )
                flash("Type de boutique invalide.", "danger")
                return redirect(url_for("admin_users.create_shop"))

            # Vérifier si le vendeur existe
            vendor = db.session.get(User, vendor_id)
            if not vendor or vendor.role != "vendor":
                flash("Vendeur introuvable ou rôle invalide.", "danger")
                return redirect(url_for("admin_users.create_shop"))

            # Vérifier si le vendeur a déjà une boutique
            existing_shop = Shop.query.filter_by(vendor_id=vendor_id).first()
            if existing_shop:
                flash("Ce vendeur a déjà une boutique.", "warning")
                return redirect(url_for("admin_users.shop_detail", shop_id=existing_shop.id))

            shop = _create_shop_for_vendor(
                vendor,
                name=name,
                description=description,
                contact_email=contact_email,
                contact_phone=contact_phone,
                address=address,
                primary_type=primary_type,
                allowed_types=allowed_types,
            )

            db.session.commit()

            # Log d'audit (non bloquant)
            try:
                log_access(
                    "create_shop",
                    "shop",
                    shop.id,
                    success=True,
                    changes={"name": shop.name, "vendor_id": vendor_id},
                )
            except Exception:
                current_app.logger.warning(
                    "create_shop.audit_log_failed — shop_id=%s", shop.id
                )

            current_app.logger.info(
                "create_shop.success — shop_id=%s vendor_id=%s name=%s",
                shop.id, vendor_id, name,
            )
            flash(f"Boutique « {name} » créée pour {vendor.username}.", "success")
            return redirect(url_for("admin_users.shop_detail", shop_id=shop.id))

        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception(
                "create_shop.db_error — vendor_id=%s name=%s",
                request.form.get("vendor_id"),
                request.form.get("name"),
            )
            flash("Erreur base de données. Merci de réessayer.", "danger")
            return redirect(url_for("admin_users.create_shop"))

        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "create_shop.unexpected_error — vendor_id=%s",
                request.form.get("vendor_id"),
            )
            flash("Une erreur inattendue s'est produite. Merci de réessayer.", "danger")
            return redirect(url_for("admin_users.create_shop"))

    # GET — Récupérer tous les vendeurs sans boutique
    try:
        vendors_without_shop = (
            User.query
            .filter_by(role="vendor")
            .filter(~User.id.in_(db.session.query(Shop.vendor_id).filter(Shop.vendor_id.isnot(None))))
            .order_by(User.username.asc())
            .all()
        )
    except Exception:
        current_app.logger.exception("create_shop.vendors_load_error")
        vendors_without_shop = []
        flash("Impossible de charger la liste des vendeurs.", "warning")

    return render_template(
        "admin/create_shop.html",
        vendors_without_shop=vendors_without_shop,
        shop_type_order=SHOP_TYPE_ORDER,
        shop_type_labels=SHOP_TYPE_LABELS,
    )

# ==================== LOGS & ACTIVITÉ ====================
@bp.route("/logs")
def view_logs():
    """Voir les logs d'activité"""
    # Paramètres de filtrage
    category_filter = request.args.get('category', '')
    level_filter = request.args.get('level', '')
    user_filter = request.args.get('user', '')
    days = request.args.get('days', 7, type=int)
    page = page_from_args(request.args)
    audit_action_filter = request.args.get('audit_action', '')
    audit_entity_filter = request.args.get('audit_entity', '')
    audit_user_filter = request.args.get('audit_user', '')

    # Récupérer les logs avec filtres
    logs = logging_service.get_recent_logs(
        limit=50,
        category=category_filter if category_filter else None,
        level=level_filter if level_filter else None,
        user_id=int(user_filter) if user_filter else None,
        days=days
    )

    # Statistiques des logs
    stats = logging_service.get_logs_stats(days=days)

    # Historique audit (déplacé ici)
    audit_query = AuditLog.query
    if audit_action_filter:
        audit_query = audit_query.filter_by(action=audit_action_filter)
    if audit_entity_filter:
        audit_query = audit_query.filter_by(entity_type=audit_entity_filter)
    if audit_user_filter:
        try:
            audit_query = audit_query.filter_by(user_id=int(audit_user_filter))
        except ValueError:
            pass

    audit_pagination = audit_query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    audit_logs = audit_pagination.items
    audit_actions = [a[0] for a in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
    audit_entities = [e[0] for e in db.session.query(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type).all()]
    audit_users = User.query.order_by(User.username.asc()).all()
    since_7d = datetime.utcnow() - timedelta(days=7)
    logs_summary = _cache_get_or_build(
        "admin:logs:audit_summary:v1",
        ADMIN_METRICS_CACHE_TTL_MEDIUM,
        lambda: {
            "audit_total_logs": AuditLog.query.count(),
            "audit_logs_7d": AuditLog.query.filter(AuditLog.created_at >= since_7d).count(),
        },
    )
    audit_total_logs = int(logs_summary.get("audit_total_logs", 0) or 0)
    audit_logs_7d = int(logs_summary.get("audit_logs_7d", 0) or 0)

    # Liste des utilisateurs pour le filtre
    active_users = User.query.filter_by(is_active=True).order_by(User.username).all()

    return render_template(
        "admin/logs.html",
        logs=logs,
        stats=stats,
        active_users=active_users,
        category_filter=category_filter,
        level_filter=level_filter,
        user_filter=user_filter,
        days=days,
        audit_logs=audit_logs,
        audit_pagination=audit_pagination,
        audit_actions=audit_actions,
        audit_entities=audit_entities,
        audit_users=audit_users,
        audit_action_filter=audit_action_filter,
        audit_entity_filter=audit_entity_filter,
        audit_user_filter=audit_user_filter,
        audit_total_logs=audit_total_logs,
        audit_logs_7d=audit_logs_7d
    )

@bp.route("/audit")
def audit_logs():
    """Voir les logs d'audit"""
    flash("La page audit a été retirée.", "info")
    return redirect(url_for("admin.dashboard"))

@bp.route("/activity")
def activity_log():
    """Vue activité marketplace (ops)."""
    flash("L'activité marketplace est maintenant sur le dashboard.", "info")
    return redirect(url_for("admin.dashboard"))


@bp.route("/reconciliation")
def reconciliation():
    page = page_from_args(request.args)
    status = (request.args.get("status") or "").strip().lower()
    per_page = 50
    now = datetime.utcnow()
    settings = PlatformSettings.get()
    date_filter = resolve_date_filter(request.args, default="month")
    global_free_until = settings.vendor_free_until
    global_free_active = bool(global_free_until and global_free_until >= now)

    base_query = User.query.filter_by(role="vendor").options(selectinload(User.shop))

    if status == "active":
        if global_free_active:
            base_query = base_query.filter(User.is_active == True)
        else:
            base_query = base_query.filter(
                User.is_active == True,
                or_(User.subscription_expires_at >= now, User.subscription_free_until >= now)
            )
    elif status == "overdue":
        if not global_free_active:
            base_query = base_query.filter(
                User.is_active == True,
                or_(
                    User.subscription_expires_at.is_(None),
                    User.subscription_expires_at < now
                ),
                or_(User.subscription_free_until.is_(None), User.subscription_free_until < now)
            )
        else:
            base_query = base_query.filter(User.is_active == True)
    elif status == "blocked":
        base_query = base_query.filter(User.is_active == False)

    pagination = base_query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    total_vendors = User.query.filter_by(role="vendor").count()
    if global_free_active:
        active_subs = User.query.filter(User.role == "vendor", User.is_active == True).count()
        overdue_subs = 0
    else:
        active_subs = User.query.filter(
            User.role == "vendor",
            User.is_active == True,
            or_(User.subscription_expires_at >= now, User.subscription_free_until >= now)
        ).count()
        overdue_subs = User.query.filter(
            User.role == "vendor",
            User.is_active == True,
            or_(User.subscription_expires_at.is_(None), User.subscription_expires_at < now),
            or_(User.subscription_free_until.is_(None), User.subscription_free_until < now)
        ).count()
    blocked_vendors = User.query.filter(
        User.role == "vendor",
        User.is_active == False
    ).count()

    subscription_row = (
        db.session.query(
            db.func.coalesce(db.func.sum(SubscriptionPayment.amount_cents), 0).label("amount"),
            db.func.count(SubscriptionPayment.id).label("count"),
        )
        .select_from(SubscriptionPayment)
        .filter(
            SubscriptionPayment.paid_at >= date_filter.start_at,
            SubscriptionPayment.paid_at < date_filter.end_at,
        )
        .first()
    )
    subscription_total_cents = int((subscription_row.amount if subscription_row else 0) or 0)
    subscription_count = int((subscription_row.count if subscription_row else 0) or 0)

    return render_template(
        "admin/reconciliation.html",
        vendors=pagination.items,
        pagination=pagination,
        now=now,
        status=status,
        settings=settings,
        global_free_until=global_free_until,
        global_free_active=global_free_active,
        range_filter=date_filter.range_filter,
        date_range_label=date_filter.label,
        date_from=date_filter.date_from,
        date_to=date_filter.date_to,
        total_vendors=total_vendors,
        active_subs=active_subs,
        overdue_subs=overdue_subs,
        blocked_vendors=blocked_vendors,
        subscription_total_cents=subscription_total_cents,
        subscription_count=subscription_count,
    )


@bp.route("/reconciliation/mark-subscription/<int:user_id>", methods=["POST"])
def mark_subscription_paid(user_id):
    user = User.query.get_or_404(user_id)
    months = request.form.get("months", type=int) or 1
    if months < 1:
        months = 1
    if months > 24:
        months = 24

    note = (request.form.get("note") or "").strip()[:200]
    now = datetime.utcnow()
    settings = PlatformSettings.get()
    monthly_cents = int(settings.vendor_subscription_monthly_cents or 0)
    paid_amount_cents = max(0, monthly_cents * months)

    base = user.subscription_expires_at if user.subscription_expires_at and user.subscription_expires_at > now else now
    user.subscription_last_paid_at = now
    user.subscription_expires_at = base + timedelta(days=30 * months)
    if note:
        user.subscription_note = note

    if not user.is_active:
        user.is_active = True
    if user.shop and not user.shop.is_active:
        user.shop.is_active = True

    payment = SubscriptionPayment(
        user_id=user.id,
        months=months,
        amount_cents=paid_amount_cents,
        paid_at=now,
        created_by_id=current_user.id if current_user.is_authenticated else None,
        note=note or None,
    )
    db.session.add(payment)
    actor_label = (
        (getattr(current_user, "username", None) or getattr(current_user, "email", None) or "").strip()
        if current_user.is_authenticated
        else ""
    ) or "admin"
    target_label = ((user.username or "").strip() or (user.email or "").strip() or f"user#{user.id}")
    finance_note = f"Paiement abonnement pour {target_label} enregistre par {actor_label}"
    if note:
        finance_note = f"{finance_note} - note: {note}"
    record_subscription_entry(payment, note=finance_note)

    db.session.commit()

    log_access(
        "subscription_paid",
        "user",
        user.id,
        success=True,
        changes={
            "months": months,
            "amount_cents": paid_amount_cents,
            "subscription_payment_id": payment.id,
            "expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
        }
    )

    flash("Abonnement mis à jour", "success")
    return redirect(request.referrer or url_for("admin_users.reconciliation"))


@bp.route("/reconciliation/free-vendor/<int:user_id>", methods=["POST"])
def subscription_free_vendor(user_id):
    user = User.query.get_or_404(user_id)
    days = request.form.get("days", type=int) or 7
    if days < 1:
        days = 1
    if days > 365:
        days = 365

    now = datetime.utcnow()
    user.subscription_free_until = now + timedelta(days=days)
    if not user.is_active:
        user.is_active = True
    if user.shop and not user.shop.is_active:
        user.shop.is_active = True

    db.session.commit()

    log_access(
        "subscription_free_vendor",
        "user",
        user.id,
        success=True,
        changes={"free_days": days, "free_until": user.subscription_free_until.isoformat()}
    )

    flash("Mode free activé pour ce vendeur", "success")
    return redirect(request.referrer or url_for("admin_users.reconciliation"))



@bp.route("/reconciliation/settings", methods=["POST"])
def subscription_settings():
    settings = PlatformSettings.get()
    now = datetime.utcnow()

    monthly_amount = request.form.get("monthly_amount", type=float)
    if monthly_amount is not None:
        if monthly_amount < 0:
            monthly_amount = 0
        settings.vendor_subscription_monthly_cents = int(round(monthly_amount * 100))

    free_days_all = request.form.get("free_days_all", type=int)
    if free_days_all is not None:
        if free_days_all <= 0:
            settings.vendor_free_until = None
        else:
            if free_days_all > 365:
                free_days_all = 365
            settings.vendor_free_until = now + timedelta(days=free_days_all)

    db.session.commit()
    flash("Paramètres d'abonnement mis à jour", "success")
    return redirect(request.referrer or url_for("admin_users.reconciliation"))

@bp.route("/reconciliation/block-vendor/<int:user_id>", methods=["POST"])
def subscription_block_vendor(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = False
    if user.shop:
        user.shop.is_active = False
    db.session.commit()

    log_access(
        "subscription_block_vendor",
        "user",
        user.id,
        success=True,
        changes={"is_active": False}
    )

    flash("Vendeur bloqué", "warning")
    return redirect(request.referrer or url_for("admin_users.reconciliation"))


@bp.route("/reconciliation/unblock-vendor/<int:user_id>", methods=["POST"])
def subscription_unblock_vendor(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    if user.shop:
        user.shop.is_active = True
    db.session.commit()

    log_access(
        "subscription_unblock_vendor",
        "user",
        user.id,
        success=True,
        changes={"is_active": True}
    )

    flash("Vendeur débloqué", "success")
    return redirect(request.referrer or url_for("admin_users.reconciliation"))


@bp.route("/fraud")
def fraud_monitor():
    days = normalize_limit(request.args.get("days", 2, type=int), default=2, max_limit=365)
    threshold = normalize_limit(request.args.get("threshold", 3, type=int), default=3, max_limit=50)
    limit_1h = normalize_limit(request.args.get("limit_1h", 5, type=int), default=5, max_limit=50)
    limit_24h = normalize_limit(request.args.get("limit_24h", 12, type=int), default=12, max_limit=50)
    cancel_limit = normalize_limit(request.args.get("cancel_limit", 3, type=int), default=3, max_limit=50)
    ip_phones_limit = normalize_limit(request.args.get("ip_phones_limit", 4, type=int), default=4, max_limit=50)
    addr_min_len = normalize_limit(request.args.get("addr_min_len", 8, type=int), default=8, max_limit=64)
    max_rows = normalize_limit(
        request.args.get("max_rows", FRAUD_MAX_ROWS_DEFAULT, type=int),
        default=FRAUD_MAX_ROWS_DEFAULT,
        max_limit=FRAUD_MAX_ROWS_CAP,
    )

    if days < 1:
        days = 1
    if threshold < 2:
        threshold = 2
    if limit_1h < 2:
        limit_1h = 2
    if limit_24h < 2:
        limit_24h = 2
    if cancel_limit < 2:
        cancel_limit = 2
    if ip_phones_limit < 2:
        ip_phones_limit = 2
    if addr_min_len < 4:
        addr_min_len = 4
    if max_rows < 10:
        max_rows = 10

    now = datetime.utcnow()
    since = now - timedelta(days=days)
    since_1h = now - timedelta(hours=1)
    since_24h = now - timedelta(hours=24)

    phone_filter = [Order.phone_digits.isnot(None), Order.phone_digits != ""]
    ip_filter = [Order.order_ip.isnot(None), Order.order_ip != ""]

    def _grouped_metric(value_column, filters, since_dt, min_count, *, cancelled_only=False):
        query = (
            db.session.query(
                value_column,
                db.func.count(Order.id).label("cnt"),
                db.func.max(Order.created_at).label("last"),
            )
            .filter(Order.created_at >= since_dt, *filters)
        )
        if cancelled_only:
            query = query.filter(Order.status == "cancelled")
        return (
            query.group_by(value_column)
            .having(db.func.count(Order.id) >= min_count)
            .order_by(db.desc("cnt"), db.desc("last"))
            .limit(max_rows)
            .all()
        )

    phone_groups = _grouped_metric(Order.phone_digits, phone_filter, since, threshold)
    ip_groups = _grouped_metric(Order.order_ip, ip_filter, since, threshold)
    phone_1h = _grouped_metric(Order.phone_digits, phone_filter, since_1h, limit_1h)
    ip_1h = _grouped_metric(Order.order_ip, ip_filter, since_1h, limit_1h)
    phone_24h = _grouped_metric(Order.phone_digits, phone_filter, since_24h, limit_24h)
    ip_24h = _grouped_metric(Order.order_ip, ip_filter, since_24h, limit_24h)
    cancelled_phones = _grouped_metric(Order.phone_digits, phone_filter, since, cancel_limit, cancelled_only=True)
    cancelled_ips = _grouped_metric(Order.order_ip, ip_filter, since, cancel_limit, cancelled_only=True)

    ip_phone_mix = (
        db.session.query(
            Order.order_ip.label("ip"),
            db.func.count(db.distinct(Order.phone_digits)).label("phones"),
            db.func.count(Order.id).label("orders"),
            db.func.max(Order.created_at).label("last")
        )
        .filter(Order.created_at >= since, *ip_filter, *phone_filter)
        .group_by(Order.order_ip)
        .having(db.func.count(db.distinct(Order.phone_digits)) >= ip_phones_limit)
        .order_by(db.desc("phones"))
        .limit(max_rows)
        .all()
    )

    addr = db.func.trim(Order.address)
    addr_lower = db.func.lower(Order.address)
    suspicious_keywords = [
        "test", "xxxx", "xxx", "unknown", "inconnu", "n/a", "na", "none", "sans adresse", "no address", "rien"
    ]
    suspicious_filters = [
        Order.address.is_(None),
        addr == "",
        db.func.length(addr) < addr_min_len,
    ]
    for kw in suspicious_keywords:
        suspicious_filters.append(addr_lower.like(f"%{kw}%"))

    suspicious_orders = (
        Order.query
        .options(
            load_only(
                Order.id,
                Order.phone_digits,
                Order.order_ip,
                Order.address,
                Order.status,
                Order.created_at,
            )
        )
        .filter(Order.created_at >= since)
        .filter(db.or_(*suspicious_filters))
        .order_by(Order.created_at.desc())
        .limit(max_rows)
        .all()
    )

    tracked_phones = set()
    tracked_ips = set()

    for phone, _, _ in phone_groups + phone_1h + phone_24h + cancelled_phones:
        if phone:
            tracked_phones.add(phone)
    for ip, _, _ in ip_groups + ip_1h + ip_24h + cancelled_ips:
        if ip:
            tracked_ips.add(ip)
    for ip, _, _, _ in ip_phone_mix:
        if ip:
            tracked_ips.add(ip)
    for order in suspicious_orders:
        if order.phone_digits:
            tracked_phones.add(order.phone_digits)
        if order.order_ip:
            tracked_ips.add(order.order_ip)

    blocked_filters = []
    if tracked_phones:
        blocked_filters.append(and_(BlockedContact.kind == "phone", BlockedContact.value.in_(tracked_phones)))
    if tracked_ips:
        blocked_filters.append(and_(BlockedContact.kind == "ip", BlockedContact.value.in_(tracked_ips)))

    blocked = (
        BlockedContact.query
        .filter(BlockedContact.is_active == True)
        .filter(or_(*blocked_filters))
        .all()
    ) if blocked_filters else []
    blocked_map = {(b.kind, b.value): b for b in blocked}

    return render_template(
        "admin/fraud.html",
        now=now,
        days=days,
        threshold=threshold,
        since=since,
        limit_1h=limit_1h,
        limit_24h=limit_24h,
        cancel_limit=cancel_limit,
        ip_phones_limit=ip_phones_limit,
        addr_min_len=addr_min_len,
        max_rows=max_rows,
        phone_groups=phone_groups,
        ip_groups=ip_groups,
        phone_1h=phone_1h,
        ip_1h=ip_1h,
        phone_24h=phone_24h,
        ip_24h=ip_24h,
        cancelled_phones=cancelled_phones,
        cancelled_ips=cancelled_ips,
        ip_phone_mix=ip_phone_mix,
        suspicious_orders=suspicious_orders,
        blocked_map=blocked_map
    )


@bp.route("/fraud/block", methods=["POST"])
def fraud_block():
    kind = (request.form.get("kind") or "").strip()
    value = (request.form.get("value") or "").strip()
    reason = (request.form.get("reason") or "").strip()[:200]

    if kind not in ("phone", "ip"):
        flash("Type invalide", "danger")
        return redirect(request.referrer or url_for("admin_users.fraud_monitor"))

    if kind == "phone":
        value = re.sub(r"\D", "", value)
    if not value:
        flash("Valeur invalide", "danger")
        return redirect(request.referrer or url_for("admin_users.fraud_monitor"))

    blocked = BlockedContact.query.filter_by(kind=kind, value=value).first()
    if blocked:
        blocked.is_active = True
        blocked.reason = reason or blocked.reason
        blocked.created_by_id = current_user.id
    else:
        blocked = BlockedContact(
            kind=kind,
            value=value,
            reason=reason,
            is_active=True,
            created_by_id=current_user.id
        )
        db.session.add(blocked)

    db.session.commit()

    log_access(
        "block_contact",
        "blocked_contact",
        blocked.id,
        success=True,
        changes={"kind": kind, "value": value, "reason": reason}
    )

    flash("Contact bloqué.", "success")
    return redirect(request.referrer or url_for("admin_users.fraud_monitor"))


@bp.route("/fraud/unblock/<int:block_id>", methods=["POST"])
def fraud_unblock(block_id):
    blocked = BlockedContact.query.get_or_404(block_id)
    blocked.is_active = False
    db.session.commit()

    log_access(
        "unblock_contact",
        "blocked_contact",
        blocked.id,
        success=True,
        changes={"kind": blocked.kind, "value": blocked.value}
    )

    flash("Contact débloqué.", "success")
    return redirect(request.referrer or url_for("admin_users.fraud_monitor"))


@bp.route("/catalog-quality")
def catalog_quality():
    page = page_from_args(request.args)
    no_image = request.args.get("no_image") == "1"
    no_desc = request.args.get("no_desc") == "1"
    out_of_stock = request.args.get("out_of_stock") == "1"
    inactive = request.args.get("inactive") == "1"

    page_params = {}
    if no_image:
        page_params["no_image"] = "1"
    if no_desc:
        page_params["no_desc"] = "1"
    if out_of_stock:
        page_params["out_of_stock"] = "1"
    if inactive:
        page_params["inactive"] = "1"

    query = Product.query.options(
        selectinload(Product.shop),
        selectinload(Product.vendor)
    )
    if no_image:
        query = query.filter(or_(Product.image_file.is_(None), Product.image_file == ""))
    if no_desc:
        query = query.filter(or_(Product.description.is_(None), Product.description == ""))
    if out_of_stock:
        query = query.filter(Product.stock <= 0)
    if inactive:
        query = query.filter(Product.is_active == False)

    pagination = query.order_by(Product.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    products = pagination.items

    count_no_image = Product.query.filter(or_(Product.image_file.is_(None), Product.image_file == "")).count()
    count_no_desc = Product.query.filter(or_(Product.description.is_(None), Product.description == "")).count()
    count_out = Product.query.filter(Product.stock <= 0).count()

    return render_template(
        "admin/catalog_quality.html",
        products=products,
        pagination=pagination,
        page_params=page_params,
        no_image=no_image,
        no_desc=no_desc,
        out_of_stock=out_of_stock,
        inactive=inactive,
        count_no_image=count_no_image,
        count_no_desc=count_no_desc,
        count_out=count_out
    )


@bp.route("/catalog-quality/toggle/<int:product_id>", methods=["POST"])
def catalog_toggle_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_active = not product.is_active
    db.session.commit()
    bump_catalog_version()

    log_access(
        "toggle_product",
        "product",
        product.id,
        success=True,
        changes={"is_active": product.is_active}
    )

    flash("Produit mis à jour.", "success")
    return redirect(request.referrer or url_for("admin_users.catalog_quality"))


@bp.route("/catalog-quality/hide-out-of-stock", methods=["POST"])
def catalog_hide_out_of_stock():
    updated = Product.query.filter(Product.stock <= 0, Product.is_active == True).update(
        {Product.is_active: False}, synchronize_session=False
    )
    db.session.commit()
    bump_catalog_version()

    log_access(
        "hide_out_of_stock",
        "product",
        0,
        success=True,
        changes={"count": updated}
    )

    flash(f"{updated} produits masqués.", "success")
    return redirect(request.referrer or url_for("admin_users.catalog_quality"))


# ==================== API POUR ADMIN ====================
@bp.route("/api/stats")
def api_stats():
    """API pour les statistiques admin"""
    total_users = User.query.count()
    total_vendors = User.query.filter_by(role='vendor').count()
    total_shops = Shop.query.count()
    total_products = Product.query.count()
    total_product_contacts = ProductContactLead.query.filter_by(source="product_whatsapp").count()

    today = datetime.utcnow().date()
    product_contacts_today = ProductContactLead.query.filter(
        db.func.date(ProductContactLead.created_at) == today,
        ProductContactLead.source == "product_whatsapp",
    ).count()
    express_delivery_revenue_today = Order.query.filter(
        db.func.date(Order.created_at) == today,
        Order.delivery_source == "special",
        Order.delivery_status == "delivered",
    ).with_entities(db.func.sum(Order.delivery_platform_fee_cents)).scalar() or 0

    return jsonify({
        'total_users': total_users,
        'total_vendors': total_vendors,
        'total_shops': total_shops,
        'total_products': total_products,
        'total_product_contacts': total_product_contacts,
        'product_contacts_today': product_contacts_today,
        'express_delivery_revenue_today': express_delivery_revenue_today / 100,
    })

@bp.route("/api/user/<int:user_id>/quick-info")
def api_user_quick_info(user_id):
    """Info rapide sur un utilisateur"""
    user = User.query.get_or_404(user_id)

    info = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'role': user.role,
        'created_at': user.created_at.isoformat() if user.created_at else None
    }

    if user.role == 'vendor':
        shop = Shop.query.filter_by(vendor_id=user.id).first()
        if shop:
            info['shop'] = {
                'id': shop.id,
                'name': shop.name,
                'is_active': shop.is_active
            }

    return jsonify(info)
