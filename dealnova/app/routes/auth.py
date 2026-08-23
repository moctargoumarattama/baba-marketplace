from datetime import datetime
import hashlib
import re
import unicodedata
from urllib.parse import quote, urljoin, urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..middleware.rate_limit import rate_limit
from ..models.shop import Shop
from ..models.user import User
from ..models.vendor_application import VendorApplication
from ..services.audit import log_access
from ..services.email_service import build_public_url, send_account_created_email
from ..services.logging_service import logging_service
from ..services.shop_access import shop_allows_any
from ..services.support_whatsapp import (
    append_support_request,
    build_support_whatsapp_url,
    safe_support_back_target,
    support_user_label,
)
from ..services.traffic_stats import track_custom_event
from .forms import LoginForm, RegisterForm

bp = Blueprint("auth", __name__)

_PHONE_DIGIT_RE = re.compile(r"\d")
_EMAIL_BASIC_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_SAFE_RE = re.compile(r"[^a-z0-9_]+")
_ALLOWED_VENDOR_SHOP_TYPES = ("products", "services", "location")
_VENDOR_PASSWORD_BLOCKLIST = {"12345678", "0000000000"}


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
    )
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits


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


def _phone_digits(value: str | None) -> str:
    return "".join(_PHONE_DIGIT_RE.findall(str(value or "")))[:32]


def _normalize_optional_email(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if not candidate:
        return ""
    return candidate if _EMAIL_BASIC_RE.match(candidate) else ""


def _unique_customer_username(full_name: str | None, email: str) -> str:
    seed_source = (full_name or "").strip() or email.split("@", 1)[0]
    normalized = (
        unicodedata.normalize("NFKD", seed_source)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    base = _USERNAME_SAFE_RE.sub("_", normalized)
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        base = "client"
    if not base.startswith("client"):
        base = f"client_{base}"
    base = base[:50]

    candidate = base
    counter = 1
    while User.query.filter(func.lower(User.username) == candidate.lower()).first():
        suffix = f"_{counter}"
        candidate = f"{base[: max(1, 50 - len(suffix))]}{suffix}"
        counter += 1
        if counter > 2000:
            candidate = f"client_{int(datetime.utcnow().timestamp())}"
            if not User.query.filter(func.lower(User.username) == candidate.lower()).first():
                break
    return candidate


@bp.route("/support/whatsapp")
def support_whatsapp():
    role = (getattr(current_user, "role", "") or "").lower()
    if getattr(current_user, "is_authenticated", False) and role in {"vendor", "admin", "manager"}:
        flash("Interdit", "danger")
        return redirect(url_for("shop.home"))

    page_name = (request.args.get("page") or "Espace client").strip()[:120]
    page_url = (request.args.get("page_url") or "").strip()[:400]
    source = (request.args.get("source") or "").strip()[:160]
    item_name = (request.args.get("item") or "").strip()[:160]
    back_url = safe_support_back_target(request.args.get("back"), url_for("shop.home"))

    lines = [
        "Bonjour, je signale un probleme sur mon espace client.",
        f"Page: {page_name}",
    ]
    if getattr(current_user, "is_authenticated", False):
        lines.insert(1, f"Compte: {support_user_label(current_user)} (id: {current_user.id})")
    else:
        lines.insert(1, "Compte: Visiteur")
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
        support_scope="Support client",
        support_title="Signaler un probleme client",
        support_copy="Votre message est pret avec la page et votre compte client.",
        back_url=back_url,
        back_label="Retour a la page",
    )


@bp.route("/register", methods=["GET", "POST"])
@rate_limit(
    limit=5,
    window_seconds=900,
    key_prefix="register",
    methods=("POST",),
    key_func=lambda: f"{request.remote_addr}:{(request.form.get('email') or '').lower()}",
)
def register():
    if current_user.is_authenticated:
        role = (getattr(current_user, "role", "") or "").lower()
        if role in {"admin", "manager"}:
            return redirect("/admin/")
        if role == "vendor":
            vendor_shop = Shop.query.filter_by(vendor_id=current_user.id).first()
            if vendor_shop and shop_allows_any(vendor_shop, "location") and not shop_allows_any(vendor_shop, "products", "services"):
                return redirect(url_for("rentals.owner_locations"))
            return redirect(url_for("vendor.dashboard"))
        return redirect(url_for("shop.home"))

    form = RegisterForm()
    if form.validate_on_submit():
        full_name = (form.full_name.data or "").strip()
        email = _normalize_optional_email(form.email.data)
        raw_password = (form.password.data or "").strip()

        if not email:
            flash("Email invalide.", "warning")
            return render_template("auth/register.html", form=form)

        existing_user = (
            User.query
            .filter(func.lower(User.email) == email)
            .first()
        )
        if existing_user:
            flash("Cet email est deja utilise. Connectez-vous ou utilisez un autre email.", "warning")
            return render_template("auth/register.html", form=form)

        user = User(
            username=_unique_customer_username(full_name, email),
            email=email,
            role="customer",
            full_name=full_name,
            created_at=datetime.utcnow(),
            is_active=True,
        )
        user.set_password(raw_password)

        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Impossible de creer le compte pour le moment. Reessayez avec un autre email.", "danger")
            return render_template("auth/register.html", form=form)

        mail_result = send_account_created_email(
            recipient_email=user.email,
            account_email=user.email,
            password_plaintext=raw_password,
            login_url=build_public_url("auth.login"),
        )

        try:
            logging_service.log_activity(
                "auth",
                "customer_register",
                resource_type="user",
                resource_id=user.id,
                message=f"Nouveau compte client cree (uid={user.id}, email={_mask_email(user.email)})",
                level="INFO",
            )
        except Exception:
            current_app.logger.warning("auth.register.activity_log_failed user_id=%s", user.id)

        try:
            log_access(
                "customer_register",
                "user",
                user.id,
                success=True,
                changes={"role": "customer", "channel": "public_register"},
            )
        except Exception:
            current_app.logger.warning("auth.register.audit_log_failed user_id=%s", user.id)

        if mail_result.get("sent"):
            flash("Compte cree avec succes. Un e-mail de bienvenue vient d'etre envoye.", "success")
        else:
            flash("Compte cree avec succes. Vous pouvez deja vous connecter.", "success")
            flash("L'e-mail automatique n'a pas pu etre envoye pour le moment.", "warning")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


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
        login_identifier = (form.email.data or "").strip().lower()
        login_password = (form.password.data or "").strip()

        user = (
            User.query
            .filter(
                or_(
                    func.lower(User.email) == login_identifier,
                    func.lower(User.username) == login_identifier,
                )
            )
            .first()
        )
        if user and user.check_password(login_password):
            if not user.is_active:
                logging_service.log_activity(
                    "auth",
                    "login_blocked",
                    user=user,
                    resource_type="user",
                    resource_id=user.id,
                    message=f"Tentative de connexion sur compte inactif (uid={user.id}, email={_mask_email(user.email)})",
                    level="WARNING",
                )
                flash("Compte desactive.", "danger")
                return render_template("auth/login.html", form=form)

            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            try:
                track_custom_event("login_success")
            except Exception:
                pass

            logging_service.log_activity(
                "auth",
                "user_login",
                user=user,
                resource_type="user",
                resource_id=user.id,
                message=f"Connexion reussie (uid={user.id}, role={user.role})",
                level="INFO",
            )
            log_access("login", "user", user.id, success=True)

            next_page = request.args.get("next")
            if not _is_safe_url(next_page):
                next_page = None
            if next_page:
                return redirect(next_page)

            role = (getattr(user, "role", "") or "").lower()
            if role not in User.ALLOWED_ROLES:
                logout_user()
                flash("Compte non autorise.", "danger")
                return redirect(url_for("auth.login"))

            if role in {"admin", "manager"}:
                return redirect("/admin/")

            if role == "vendor":
                vendor_shop = Shop.query.filter_by(vendor_id=user.id).first()
                if vendor_shop and shop_allows_any(vendor_shop, "location") and not shop_allows_any(vendor_shop, "products", "services"):
                    return redirect(url_for("rentals.owner_locations"))
                return redirect(url_for("vendor.dashboard"))

            return redirect(url_for("shop.home"))

        logging_service.log_activity(
            "auth",
            "login_failed",
            message=(
                "Tentative de connexion echouee "
                f"(email={_mask_email(form.email.data)}, fp={_email_fingerprint(form.email.data)})"
            ),
            level="WARNING",
        )
        flash("Identifiants incorrects.", "danger")

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
def logout():
    if current_user.is_authenticated:
        logging_service.log_activity(
            "auth",
            "user_logout",
            user=current_user,
            resource_type="user",
            resource_id=current_user.id,
            message=f"Deconnexion (uid={current_user.id}, role={getattr(current_user, 'role', 'unknown')})",
            level="INFO",
        )
        log_access("logout", "user", current_user.id, success=True)

    logout_user()
    flash("Deconnecte.", "info")
    return redirect(url_for("shop.home"))


@bp.route("/forgot-password", methods=["GET", "POST"])
@rate_limit(limit=5, window_seconds=300, key_prefix="forgot_password", methods=("POST",))
def forgot_password():
    """Demande de reinitialisation de mot de passe via WhatsApp admin."""
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
                "auth",
                "password_reset_requested",
                user=user,
                resource_type="user",
                resource_id=user.id,
                message=f"Demande de reinitialisation WhatsApp (uid={user.id}, email={_mask_email(email)})",
                level="INFO",
            )
        else:
            logging_service.log_activity(
                "auth",
                "password_reset_requested_unknown_email",
                message=(
                    "Demande reset WhatsApp sur email inconnu "
                    f"(email={_mask_email(email)}, fp={_email_fingerprint(email)})"
                ),
                level="INFO",
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
        flash("Demande prete. Cliquez sur le bouton si WhatsApp ne s'ouvre pas.", "info")
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
    """Ancien flux email/token desactive: redirection vers WhatsApp."""
    flash("Le reset par e-mail est desactive. Utilisez WhatsApp.", "info")
    return redirect(url_for("auth.forgot_password"))


@bp.route("/vendor-access", methods=["GET", "POST"])
@rate_limit(limit=4, window_seconds=900, key_prefix="vendor_access", methods=("POST",))
def vendor_access():
    """Creation directe d'un compte vendeur public."""
    from .admin_users import (
        _create_shop_for_vendor,
        _shop_types_from_vendor_application,
        _unique_vendor_username,
    )

    form_data = {
        "full_name": "",
        "phone": "",
        "email": "",
        "city": "",
        "shop_name": "",
        "shop_type": "",
        "short_description": "",
    }
    request_submitted = False

    if request.method == "POST":
        raw_password = (request.form.get("password") or "").strip()
        raw_password_confirm = (request.form.get("password_confirm") or "").strip()
        form_data["full_name"] = (request.form.get("full_name") or "").strip()
        form_data["phone"] = (request.form.get("phone") or "").strip()
        form_data["email"] = (request.form.get("email") or "").strip()
        form_data["city"] = (request.form.get("city") or "").strip()
        form_data["shop_name"] = (request.form.get("shop_name") or "").strip()
        form_data["shop_type"] = (request.form.get("shop_type") or "").strip().lower()
        form_data["short_description"] = (request.form.get("short_description") or "").strip()

        if (
            not form_data["full_name"]
            or not form_data["phone"]
            or not form_data["email"]
            or not form_data["shop_name"]
            or not form_data["city"]
            or not form_data["shop_type"]
        ):
            flash("Nom, telephone, email, boutique, ville et type sont obligatoires.", "warning")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )

        if len(raw_password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caracteres.", "warning")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )
        if raw_password in _VENDOR_PASSWORD_BLOCKLIST:
            flash("Ce mot de passe est trop simple. Choisissez-en un autre.", "warning")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )
        if raw_password != raw_password_confirm:
            flash("La confirmation du mot de passe ne correspond pas.", "warning")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )

        if len(form_data["full_name"]) > 120:
            form_data["full_name"] = form_data["full_name"][:120]
        if len(form_data["phone"]) > 40:
            form_data["phone"] = form_data["phone"][:40]
        if len(form_data["email"]) > 120:
            form_data["email"] = form_data["email"][:120]
        if len(form_data["city"]) > 80:
            form_data["city"] = form_data["city"][:80]
        if len(form_data["shop_name"]) > 160:
            form_data["shop_name"] = form_data["shop_name"][:160]
        if len(form_data["short_description"]) > 500:
            form_data["short_description"] = form_data["short_description"][:500]

        if form_data["shop_type"] not in _ALLOWED_VENDOR_SHOP_TYPES:
            flash("Type de boutique invalide.", "warning")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )

        phone_digits = _phone_digits(form_data["phone"])
        if len(phone_digits) < 8:
            flash("Numero de telephone invalide.", "warning")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )

        email_normalized = _normalize_optional_email(form_data["email"])
        if not email_normalized:
            flash("Email invalide.", "warning")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )
        existing_user = (
            User.query
            .filter(func.lower(User.email) == email_normalized)
            .first()
        )
        if existing_user:
            flash(
                "Cet email est deja utilise. Connectez-vous avec cet email ou choisissez un autre email vendeur.",
                "warning",
            )
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )

        contact_match_filters = [VendorApplication.phone_digits == phone_digits]
        if email_normalized:
            contact_match_filters.append(VendorApplication.email_normalized == email_normalized)

        blocked_match = (
            VendorApplication.query
            .filter(
                VendorApplication.status == VendorApplication.STATUS_BLOCKED,
                or_(*contact_match_filters),
            )
            .order_by(VendorApplication.updated_at.desc())
            .first()
        )
        if blocked_match:
            flash("Votre demande ne peut pas etre enregistree. Contactez l'administration.", "danger")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )

        pending_requests = (
            VendorApplication.query
            .filter(
                VendorApplication.status == VendorApplication.STATUS_PENDING,
                or_(*contact_match_filters),
            )
            .order_by(VendorApplication.created_at.desc(), VendorApplication.id.desc())
            .all()
        )
        latest_pending_request = pending_requests[0] if pending_requests else None
        primary_type, allowed_types = _shop_types_from_vendor_application(form_data["shop_type"])
        username = _unique_vendor_username(form_data["shop_name"] or form_data["full_name"])
        auto_review_note = "Compte vendeur cree automatiquement via le formulaire public."

        try:
            user = User(
                username=username,
                email=email_normalized,
                role="vendor",
                full_name=form_data["full_name"],
                phone=form_data["phone"],
                address=form_data["city"],
                created_at=datetime.utcnow(),
                is_active=True,
            )
            user.set_password(raw_password)
            db.session.add(user)
            db.session.flush()

            shop = _create_shop_for_vendor(
                user,
                name=form_data["shop_name"],
                description=form_data["short_description"],
                contact_email=form_data["email"],
                contact_phone=form_data["phone"],
                address=form_data["city"],
                primary_type=primary_type,
                allowed_types=allowed_types,
            )

            if latest_pending_request is None:
                latest_pending_request = VendorApplication(
                    full_name=form_data["full_name"],
                    phone=form_data["phone"],
                    phone_digits=phone_digits,
                    email=form_data["email"],
                    email_normalized=email_normalized,
                    shop_name=form_data["shop_name"],
                    city=form_data["city"],
                    shop_type=form_data["shop_type"],
                    password_hash=user.password_hash,
                    short_description=form_data["short_description"] or None,
                    status=VendorApplication.STATUS_APPROVED,
                    review_note=auto_review_note,
                    reviewed_at=datetime.utcnow(),
                    reviewed_by_id=None,
                    created_user_id=user.id,
                    created_shop_id=shop.id,
                    source="web_form_auto",
                    request_ip=(request.remote_addr or "").strip()[:64] or None,
                )
                db.session.add(latest_pending_request)
            else:
                latest_pending_request.full_name = form_data["full_name"]
                latest_pending_request.phone = form_data["phone"]
                latest_pending_request.phone_digits = phone_digits
                latest_pending_request.email = form_data["email"]
                latest_pending_request.email_normalized = email_normalized
                latest_pending_request.shop_name = form_data["shop_name"]
                latest_pending_request.city = form_data["city"]
                latest_pending_request.shop_type = form_data["shop_type"]
                latest_pending_request.password_hash = user.password_hash
                latest_pending_request.short_description = form_data["short_description"] or None
                latest_pending_request.status = VendorApplication.STATUS_APPROVED
                latest_pending_request.review_note = auto_review_note
                latest_pending_request.reviewed_at = datetime.utcnow()
                latest_pending_request.reviewed_by_id = None
                latest_pending_request.created_user_id = user.id
                latest_pending_request.created_shop_id = shop.id
                latest_pending_request.source = "web_form_auto"
                latest_pending_request.request_ip = (request.remote_addr or "").strip()[:64] or None

            for stale_request in pending_requests[1:]:
                stale_request.status = VendorApplication.STATUS_REJECTED
                stale_request.review_note = "Remplace par une creation immediate de compte vendeur."
                stale_request.reviewed_at = datetime.utcnow()
                stale_request.reviewed_by_id = None

            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Impossible de creer le compte vendeur pour le moment. Verifiez les donnees puis reessayez.", "danger")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )
        except Exception:
            db.session.rollback()
            current_app.logger.exception("vendor_access.auto_create.failed email=%s", _mask_email(email_normalized))
            flash("Impossible de creer le compte vendeur pour le moment.", "danger")
            return render_template(
                "auth/vendor_access.html",
                form_data=form_data,
                request_submitted=False,
            )

        mail_result = send_account_created_email(
            recipient_email=user.email,
            account_email=user.email,
            password_plaintext=raw_password,
            login_url=build_public_url("auth.login"),
        )

        logging_service.log_activity(
            "auth",
            "vendor_account_created",
            resource_type="user",
            resource_id=user.id,
            message=(
                "Compte vendeur cree automatiquement "
                f"(uid={user.id}, shop_id={shop.id}, email={_mask_email(user.email)})"
            ),
            level="INFO",
        )
        log_access(
            "vendor_account_created",
            "user",
            user.id,
            success=True,
            changes={
                "shop_id": shop.id,
                "city": form_data["city"],
                "shop_type": form_data["shop_type"] or None,
            },
        )
        flash("Compte vendeur cree avec succes. Vous pouvez vous connecter immediatement.", "success")
        if not mail_result.get("sent"):
            flash("L'e-mail automatique n'a pas pu etre envoye pour le moment.", "warning")
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/vendor_access.html",
        form_data=form_data,
        request_submitted=request_submitted,
    )


@bp.route("/moctar")
def login_safe():
    return redirect(url_for("auth.login"))
