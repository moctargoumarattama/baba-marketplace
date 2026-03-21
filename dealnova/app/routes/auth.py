from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, current_user
import hashlib
from ..extensions import db
from ..models.shop import Shop
from ..models.user import User
from .forms import LoginForm
from ..services.logging_service import logging_service
from ..services.audit import log_access
from ..services.traffic_stats import track_custom_event
from ..services.shop_access import shop_allows_any
from ..middleware.rate_limit import rate_limit
from datetime import datetime
from urllib.parse import urlparse, urljoin, quote
bp = Blueprint("auth", __name__)


def _is_safe_url(target):
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def _admin_whatsapp_number() -> str:
    raw = (
        current_app.config.get("ADMIN_PHONE")
        or current_app.config.get("SUPPORT_WHATSAPP_NUMBER")
        or "+212770010264"
    )
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits or "212770010264"


def _mask_email(email: str | None) -> str:
    value = (email or "").strip().lower()
    if not value or "@" not in value:
        return "-"
    local, domain = value.split("@", 1)
    if not local:
        return f"***@{domain}"
    visible = local[:1]
    return f"{visible}***@{domain}"


def _email_fingerprint(email: str | None) -> str:
    value = (email or "").strip().lower()
    if not value:
        return "-"
    secret = str(current_app.config.get("SECRET_KEY") or "dealnova")
    payload = f"{secret}|{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]

@bp.route("/register", methods=["GET", "POST"])
def register():
    flash("Les comptes sont créés par l’administration.", "info")
    if current_user.is_authenticated and (getattr(current_user, "role", "") or "").lower() == "admin":
        return redirect(url_for("admin_users.create_user"))
    return redirect(url_for("auth.login"))

@bp.route("/login", methods=["GET", "POST"])
@rate_limit(
    limit=6,
    window_seconds=60,
    key_prefix="login",
    methods=("POST",),
    key_func=lambda: f"{request.remote_addr}:{(request.form.get('email') or '').lower()}",
)
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            if not user.is_active:
                logging_service.log_activity(
                    'auth', 'login_blocked',
                    user=user,
                    resource_type='user',
                    resource_id=user.id,
                    message=f"Tentative de connexion sur compte inactif (uid={user.id}, email={_mask_email(user.email)})",
                    level='WARNING'
                )
                flash("Compte désactivé.", "danger")
                return render_template("auth/login.html", form=form)

            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            try:
                track_custom_event("login_success")
            except Exception:
                pass

            # Logger la connexion russie
            logging_service.log_activity(
                'auth', 'user_login',
                user=user,
                resource_type='user',
                resource_id=user.id,
                message=f"Connexion reussie (uid={user.id}, role={user.role})",
                level='INFO'
            )
            log_access("login", "user", user.id, success=True)

            # 1) Respecter "next" si safe
            next_page = request.args.get("next")
            if not _is_safe_url(next_page):
                next_page = None
            if next_page:
                return redirect(next_page)

            # 2) Sinon redirection selon rle
            role = (getattr(user, "role", "") or "").lower()

            if role in {"admin", "manager"}:
                return redirect("/admin/")  # dashboard admin

            if role == "courier":
                return redirect(url_for("courier.panel_home"))

            if role == "vendor":
                vendor_shop = Shop.query.filter_by(vendor_id=user.id).first()
                if vendor_shop and shop_allows_any(vendor_shop, "location") and not shop_allows_any(vendor_shop, "products", "services"):
                    return redirect(url_for("rentals.owner_locations"))
                return redirect(url_for("vendor.dashboard"))  # => /vendor/dashboard

            # 3) Sinon role non reconnu: retour accueil public
            return redirect(url_for("shop.home"))

        else:
            # Logger la tentative de connexion choue
            logging_service.log_activity(
                'auth', 'login_failed',
                message=(
                    "Tentative de connexion echouee "
                    f"(email={_mask_email(form.email.data)}, fp={_email_fingerprint(form.email.data)})"
                ),
                level='WARNING'
            )
            flash("Identifiants incorrects.", "danger")

    return render_template("auth/login.html", form=form)

@bp.route("/logout", methods=["POST"])
def logout():
    # Logger la dconnexion avant de dconnecter l'utilisateur
    if current_user.is_authenticated:
        logging_service.log_activity(
            'auth', 'user_logout',
            user=current_user,
            resource_type='user',
            resource_id=current_user.id,
            message=f"Deconnexion (uid={current_user.id}, role={getattr(current_user, 'role', 'unknown')})",
            level='INFO'
        )
        log_access("logout", "user", current_user.id, success=True)

    logout_user()
    flash("Déconnecté.", "info")
    return redirect(url_for("shop.home"))


@bp.route("/forgot-password", methods=["GET", "POST"])
@rate_limit(limit=5, window_seconds=300, key_prefix="forgot_password", methods=("POST",))
def forgot_password():
    """Demande de rinitialisation de mot de passe via WhatsApp admin."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        shop_or_role = request.form.get("shop_or_role", "").strip()
        note = request.form.get("note", "").strip()

        if not email:
            flash("Veuillez renseigner votre email.", "warning")
            return redirect(url_for("auth.forgot_password"))

        if len(full_name) > 120:
            full_name = full_name[:120]
        if len(shop_or_role) > 160:
            shop_or_role = shop_or_role[:160]
        if len(note) > 500:
            note = note[:500]

        user = User.query.filter_by(email=email).first()
        if user:
            logging_service.log_activity(
                'auth', 'password_reset_requested',
                user=user,
                resource_type='user',
                resource_id=user.id,
                message=f"Demande de reinitialisation WhatsApp (uid={user.id}, email={_mask_email(email)})",
                level='INFO'
            )
        else:
            logging_service.log_activity(
                'auth', 'password_reset_requested_unknown_email',
                message=(
                    "Demande reset WhatsApp sur email inconnu "
                    f"(email={_mask_email(email)}, fp={_email_fingerprint(email)})"
                ),
                level='INFO'
            )

        lines = [
            "Bonjour Baba Market,",
            "Demande: MOT DE PASSE OUBLIE",
            f"Email: {email}",
            f"Nom: {full_name or '-'}",
            f"Boutique/Role: {shop_or_role or '-'}",
            f"Message: {note or 'Veuillez reinitialiser mon acces, merci.'}",
        ]
        wa_number = _admin_whatsapp_number()
        wa_url = f"https://api.whatsapp.com/send?phone={wa_number}&text={quote(chr(10).join(lines))}"
        flash("Demande prête. Cliquez sur le bouton si WhatsApp ne s’ouvre pas.", "info")
        return render_template(
            "auth/forgot_password.html",
            whatsapp_url=wa_url,
            auto_open_whatsapp=True,
            submitted_email=email,
        )

    return render_template(
        "auth/forgot_password.html",
        whatsapp_url=None,
        auto_open_whatsapp=False,
        submitted_email=None,
    )

@bp.route("/reset-password/<token>", methods=["GET"])
def reset_password(_token):
    """Ancien flux email/token dsactive: redirection vers WhatsApp."""
    flash("Le reset par e-mail est désactivé. Utilisez WhatsApp.", "info")
    return redirect(url_for("auth.forgot_password"))


@bp.route("/vendor-access", methods=["GET", "POST"])
def vendor_access():
    """Demande d'acces vendeur via formulaire site puis ouverture WhatsApp."""
    form_data = {
        "full_name": "",
        "phone": "",
        "city": "",
        "shop_name": "",
        "shop_type": "",
    }
    wa_url = None
    auto_open_whatsapp = False

    if request.method == "POST":
        form_data["full_name"] = (request.form.get("full_name") or "").strip()
        form_data["phone"] = (request.form.get("phone") or "").strip()
        form_data["city"] = (request.form.get("city") or "").strip()
        form_data["shop_name"] = (request.form.get("shop_name") or "").strip()
        form_data["shop_type"] = (request.form.get("shop_type") or "").strip()

        if not form_data["full_name"] or not form_data["phone"] or not form_data["city"]:
            flash("Nom, téléphone et ville sont obligatoires.", "warning")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                whatsapp_url=None,
                auto_open_whatsapp=False,
            )

        if len(form_data["full_name"]) > 120:
            form_data["full_name"] = form_data["full_name"][:120]
        if len(form_data["phone"]) > 40:
            form_data["phone"] = form_data["phone"][:40]
        if len(form_data["city"]) > 80:
            form_data["city"] = form_data["city"][:80]
        if len(form_data["shop_name"]) > 160:
            form_data["shop_name"] = form_data["shop_name"][:160]
        if len(form_data["shop_type"]) > 80:
            form_data["shop_type"] = form_data["shop_type"][:80]

        lines = [
            f"Bonjour 👋 Je souhaite devenir vendeur sur {current_app.config.get('SITE_NAME') or 'Baba Market'}.",
            f"Nom: {form_data['full_name']}",
            f"Telephone: {form_data['phone']}",
            f"Ville: {form_data['city']}",
            f"Nom de la boutique: {form_data['shop_name'] or '-'}",
            f"Type (Produits/Services location): {form_data['shop_type'] or '-'}",
            "Merci.",
        ]
        wa_number = _admin_whatsapp_number()
        wa_url = f"https://api.whatsapp.com/send?phone={wa_number}&text={quote(chr(10).join(lines))}"
        auto_open_whatsapp = True
        flash("Demande prête. Cliquez sur le bouton si WhatsApp ne s’ouvre pas.", "info")

        logging_service.log_activity(
            "auth",
            "vendor_access_requested",
            message=(
                "Demande acces vendeur preparee "
                f"(name={form_data['full_name'][:40]}, city={form_data['city'][:30]})"
            ),
            level="INFO",
        )
        log_access(
            "vendor_access_requested",
            "user",
            getattr(current_user, "id", 0) if getattr(current_user, "is_authenticated", False) else 0,
            success=True,
            changes={
                "city": form_data["city"],
                "shop_type": form_data["shop_type"] or None,
            },
        )

    return render_template(
        "auth/vendor_access.html",
        form_data=form_data,
        whatsapp_url=wa_url,
        auto_open_whatsapp=auto_open_whatsapp,
    )



@bp.route("/moctar")
def login_safe():
    return redirect(url_for("auth.login"))
