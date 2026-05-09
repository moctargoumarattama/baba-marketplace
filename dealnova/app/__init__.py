import os
import re
import secrets
import sqlite3
import click
from datetime import datetime
from flask import Flask, render_template, session, request, redirect, url_for, flash, jsonify, current_app, g, Response, make_response
from flask_compress import Compress
from urllib.parse import urlparse, urljoin
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_wtf.csrf import generate_csrf, validate_csrf
from wtforms.validators import ValidationError
from sqlalchemy import event, or_, case
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import load_only
from .config import Config
from .extensions import db, login_manager, migrate
from .models.user import User
from .models.product import Product
from .models.shop import Shop
from .models.rental import RentalListing, RentalMedia
from .models.featured_item import FeaturedItem
from .models.product_contact_lead import ProductContactLead
from .routes import auth, shop, vendor, cart, booking, admin, admin_categories, admin_users, rentals, delivery
from .services.logging_service import logging_service
from .services.image import image_variant
from .services.cache import cache
from .services.migration import (
    ensure_featured_items_table,
    ensure_admin_performance_indexes,
    ensure_platform_settings_columns,
    ensure_promo_workflow_columns,
    ensure_vendor_application_table,
    ensure_vendor_change_request_table,
    ensure_vendor_push_subscription_table,
)
from .services.shop_access import is_safe_public_shop_slug, normalize_public_shop_slug
from .services.i18n_labels import (
    label_delivery_status,
    label_location_status,
    label_order_status,
    label_source,
    label_vendor_payout_status,
)
from .services.maintenance import init_cli_commands  # ← IMPORT AJOUTÉ

from .services.i18n_runtime import build_client_i18n_payload, translate_text

_SCRIPT_NONCE_RE = re.compile(r"(<script\b)(?![^>]*\bnonce=)", re.IGNORECASE)
_STYLE_NONCE_RE = re.compile(r"(<style\b)(?![^>]*\bnonce=)", re.IGNORECASE)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    Compress(app)

    if app.config.get("TRUST_PROXY", False):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=max(0, int(app.config.get("PROXY_FIX_X_FOR", 1))),
            x_proto=max(0, int(app.config.get("PROXY_FIX_X_PROTO", 1))),
            x_host=max(0, int(app.config.get("PROXY_FIX_X_HOST", 1))),
            x_port=max(0, int(app.config.get("PROXY_FIX_X_PORT", 0))),
            x_prefix=max(0, int(app.config.get("PROXY_FIX_X_PREFIX", 0))),
        )

    # Extensions
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if db_uri.startswith("sqlite:///"):
        db_path = db_uri.replace("sqlite:///", "", 1)
        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        except Exception:
            pass
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
    login_manager.login_message_category = "warning"
    login_manager.needs_refresh_message = "Votre session a expiré. Veuillez vous reconnecter."
    login_manager.needs_refresh_message_category = "warning"
    login_manager.session_protection = "basic"
    cache.init_app(app)
    with app.app_context():
        logging_service.setup_logging()
        ensure_featured_items_table()
        ensure_vendor_application_table()
        ensure_vendor_change_request_table()
        ensure_vendor_push_subscription_table()
        ensure_platform_settings_columns()
        ensure_promo_workflow_columns()
        ensure_admin_performance_indexes()
        if app.config.get("SECRET_KEY") == "dev":
            app.logger.warning("SECURITY: SECRET_KEY par défaut détectée. Configurez une clé forte.")

    if (app.config.get("SQLALCHEMY_DATABASE_URI") or "").startswith("sqlite:///"):
        _register_sqlite_pragmas()

    from .services.maintenance_mode import get_maintenance_state as _get_maintenance_state
    from .services.traffic_stats import track_request_hit as _track_request_hit

    def _is_static_like_request() -> bool:
        endpoint = request.endpoint or ""
        path = request.path or ""
        return (
            endpoint.endswith(".static")
            or path.startswith("/static/")
            or path in {"/health", "/favicon.ico", "/sw.js"}
        )

    @app.route("/sw.js")
    def service_worker():
        response = current_app.send_static_file("sw.js")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.route("/favicon.ico")
    def favicon():
        response = current_app.send_static_file("favicon.ico")
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    @app.route("/health")
    def health():
        return jsonify(status="ok"), 200

    @app.route("/maintenance")
    def maintenance_page():
        state = _get_maintenance_state(force_refresh=True)
        status_code = 503 if state.get("active") else 200
        response = make_response(render_template("maintenance.html", maintenance=state), status_code)
        response.headers["X-BM-Maintenance"] = "1"
        return response

    @app.before_request
    def redirect_to_www():
        host = (request.host or "").split(":", 1)[0].strip().lower()
        if host != "babamarket.ma":
            return None

        target = f"https://www.babamarket.ma{request.full_path}"
        if target.endswith("?"):
            target = target[:-1]
        return redirect(target, code=301)


    # Handlers d'erreur
    @app.errorhandler(400)
    def bad_request_error(error):
        return render_template("errors/400.html"), 400

    @app.errorhandler(401)
    def unauthorized_error(error):
        return render_template("errors/401.html"), 401

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def rate_limit_error(error):
        return render_template("errors/429.html"), 429

    @app.errorhandler(413)
    def payload_too_large_error(error):
        flash("Fichiers trop volumineux pour la limite serveur actuelle. Rduisez la taille ou contactez l'admin.", "warning")
        return redirect(request.referrer or url_for("rentals.owner_location_new"))

    @app.errorhandler(500)
    def internal_error(error):
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            current_app.logger.exception(
                "http.500",
                extra={
                    "path": request.path if request else None,
                    "method": request.method if request else None,
                },
            )
        except Exception:
            pass
        try:
            from .services.maintenance import log_http_error

            log_http_error(
                path=request.path if request else None,
                method=request.method if request else None,
                status_code=500,
                message=str(error),
            )
        except Exception:
            pass
        return render_template("errors/500.html"), 500

    @app.context_processor
    def inject_csrf_token():
        return {
            "csrf_token": generate_csrf,
            "image_variant": image_variant,
            "app_static_version": app.config.get("APP_STATIC_VERSION", "dev"),
            "pwa_session_scope": _pwa_session_scope(),
        }

    PWA_PUBLIC_CACHEABLE_HTML_ENDPOINTS = {
        "landing",
        "global_search",
        "shop.home",
        "shop.product_detail",
        "shops.list_shops",
        "shops.shop_detail",
        "rentals.locations_home",
        "rentals.location_detail",
    }

    def _current_cart_count_value() -> int:
        from flask_login import current_user
        from sqlalchemy.orm.exc import DetachedInstanceError

        key = None

        try:
            user_id = getattr(current_user, "id", None)
            if user_id:
                key = f"cart_user_{user_id}"
        except DetachedInstanceError:
            key = None
        except Exception:
            key = None

        if not key:
            if "cart_guest" in session:
                key = "cart_guest"
            else:
                for session_key in session.keys():
                    if session_key.startswith("cart_guest_"):
                        key = session_key
                        break

        if not key:
            return 0

        cart = session.get(key, {})
        return sum(cart.values()) if isinstance(cart, dict) else 0

    def _pwa_session_scope() -> str:
        from flask_login import current_user
        from sqlalchemy.orm.exc import DetachedInstanceError

        try:
            user_id = getattr(current_user, "id", None)
            if user_id:
                return f"auth:{user_id}"
        except DetachedInstanceError:
            return "anon"
        except Exception:
            return "anon"
        return "anon"

    def _should_mark_response_public_for_pwa(response) -> bool:
        if request.method != "GET":
            return False
        if response.status_code != 200 or response.mimetype != "text/html":
            return False
        if _is_static_like_request():
            return False
        endpoint = request.endpoint or ""
        if endpoint not in PWA_PUBLIC_CACHEABLE_HTML_ENDPOINTS:
            return False

        is_fetch_request = request.headers.get("X-Requested-With") in ("XMLHttpRequest", "fetch")
        is_public_listing_fragment = (
            is_fetch_request
            and (request.args.get("_fragment") or "").strip().lower() == "listing"
            and endpoint in {
                "shop.home",
                "shops.list_shops",
                "rentals.locations_home",
                "global_search",
            }
        )
        if is_fetch_request and not is_public_listing_fragment:
            return False

        if _pwa_session_scope() != "anon":
            return False
        if _current_cart_count_value() > 0:
            return False
        return True

    def _get_lang():
        if request.path.startswith("/admin"):
            return "fr"
        lang = session.get("lang")
        if lang in app.config.get("LANGUAGES", []):
            return lang
        cookie_lang = request.cookies.get(app.config.get("LANG_COOKIE_NAME", "lang"))
        if cookie_lang in app.config.get("LANGUAGES", []):
            return cookie_lang
        return app.config.get("DEFAULT_LANG", "fr")

    @app.before_request
    def set_language():
        if _is_static_like_request():
            return None
        if request.path.startswith("/admin"):
            g.lang = "fr"
            return
        g.set_lang_cookie = None
        if request.path.startswith("/lang/") and request.method == "GET":
            g.lang = _get_lang()
            return
        lang_cookie_name = app.config.get("LANG_COOKIE_NAME", "lang")
        cookie_lang = request.cookies.get(lang_cookie_name)
        languages = app.config.get("LANGUAGES", [])
        lang = request.args.get("lang")
        transient_lang = bool(lang and lang in languages)
        if transient_lang:
            # Read-only override for current request (no state write on GET).
            g.lang = lang
        elif cookie_lang in languages:
            if session.get("lang") != cookie_lang:
                session["lang"] = cookie_lang
            g.lang = _get_lang()
        else:
            g.lang = _get_lang()
        if (not transient_lang) and g.lang and g.lang in languages and g.lang != cookie_lang:
            g.set_lang_cookie = g.lang

    @app.before_request
    def ensure_analytics_visitor_id():
        if _is_static_like_request():
            return None
        visitor_id = (request.cookies.get("bm_vid") or "").strip()
        if not visitor_id:
            visitor_id = secrets.token_urlsafe(18)
            g.set_analytics_visitor_cookie = visitor_id
        g.analytics_visitor_id = visitor_id[:80]

    @app.before_request
    def track_live_traffic():
        if _is_static_like_request():
            return None
        try:
            _track_request_hit(path=request.path, endpoint=request.endpoint)
        except Exception:
            return None

    MAINTENANCE_WHITELIST_PREFIXES = (
        "/maintenance",
        "/admin",
        "/static",
        "/health",
        "/login",
        "/logout",
        "/moctar",
        "/sw.js",
    )

    def _maintenance_whitelisted(path: str) -> bool:
        normalized = path or "/"
        for prefix in MAINTENANCE_WHITELIST_PREFIXES:
            if normalized == prefix or normalized.startswith(prefix + "/"):
                return True
        return False

    @app.before_request
    def enforce_maintenance_mode():
        path = request.path or "/"
        if _maintenance_whitelisted(path):
            return None

        try:
            from flask_login import current_user

            role = (getattr(current_user, "role", "") or "").lower()
            if current_user.is_authenticated and role == "admin":
                return None
        except Exception:
            pass

        try:
            state = _get_maintenance_state()
            if state.get("active"):
                response = make_response(render_template("maintenance.html", maintenance=state), 503)
                response.headers["X-BM-Maintenance"] = "1"
                return response
        except Exception:
            # Safe fallback requested by product: maintenance OFF on DB/runtime issue.
            return None

        return None

    @app.before_request
    def enforce_vendor_private_mode():
        endpoint = request.endpoint or ""
        path = request.path or "/"

        if endpoint.endswith(".static") or path.startswith("/static/"):
            return None

        try:
            from flask_login import current_user
        except Exception:
            return None

        if not getattr(current_user, "is_authenticated", False):
            return None

        role = (getattr(current_user, "role", "") or "").lower()
        if role != "vendor":
            return None

        allowed_endpoints = {
            "auth.logout",
            "set_language_route",
            "service_worker",
            "health",
            "maintenance_page",
        }
        if endpoint in allowed_endpoints:
            return None

        if endpoint.startswith("vendor.") or endpoint.startswith("rentals.owner_"):
            return None

        # Exception explicite: le vendeur peut voir sa propre boutique publique.
        if endpoint == "shops.shop_detail":
            shop_slug = normalize_public_shop_slug((request.view_args or {}).get("shop_slug"))
            if shop_slug and is_safe_public_shop_slug(shop_slug):
                own_shop = (
                    Shop.query.with_entities(Shop.id)
                    .filter(Shop.vendor_id == current_user.id, Shop.slug == shop_slug)
                    .first()
                )
                if own_shop:
                    return None

        # Exception explicite: le vendeur peut voir la fiche publique de son propre produit.
        if endpoint == "shop.product_detail":
            product_id = (request.view_args or {}).get("pid")
            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                product_id = None
            if product_id:
                own_product = (
                    Product.query.with_entities(Product.id)
                    .filter(Product.id == product_id, Product.vendor_id == current_user.id)
                    .first()
                )
                if own_product:
                    return None

        target_url = url_for("vendor.manage_shop")
        if request.path == target_url:
            return None

        is_ajax = request.headers.get("X-Requested-With") in ("XMLHttpRequest", "fetch")
        wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
        if is_ajax or wants_json:
            return jsonify({"error": "vendor_private_mode", "redirect_url": target_url}), 403

        return redirect(target_url)

    @app.context_processor
    def inject_lang():
        def _translate(value, lang=None):
            target_lang = lang or getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr"))
            return translate_text(value, target_lang)

        def _label_delivery(status, lang=None):
            target_lang = lang or getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr"))
            return label_delivery_status(status, target_lang)

        def _label_order(status, lang=None):
            target_lang = lang or getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr"))
            return label_order_status(status, target_lang)

        def _label_source(value, lang=None):
            target_lang = lang or getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr"))
            return label_source(value, target_lang)

        def _label_location_status(value, lang=None):
            target_lang = lang or getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr"))
            return label_location_status(value, target_lang)

        def _label_vendor_payout_status(value, lang=None):
            target_lang = lang or getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr"))
            return label_vendor_payout_status(value, target_lang)

        return {
            "current_lang": getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr")),
            "supported_langs": app.config.get("LANGUAGES", ["fr", "en", "ary"]),
            "rtl_langs": app.config.get("RTL_LANGUAGES", []),
            "t": _translate,
            "client_i18n_payload": build_client_i18n_payload(
                getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr"))
            ),
            "label_delivery_status": _label_delivery,
            "label_order_status": _label_order,
            "label_source": _label_source,
            "label_location_status": _label_location_status,
            "label_vendor_payout_status": _label_vendor_payout_status,
        }

    @app.route("/lang/<lang_code>", methods=["GET", "POST"])
    def set_language_route(lang_code):
        default_lang = app.config.get("DEFAULT_LANG", "fr")
        if lang_code not in app.config.get("LANGUAGES", []):
            lang_code = default_lang

        next_url = request.values.get("next")
        if not next_url or not _is_safe_url(next_url):
            try:
                from flask_login import current_user
                if getattr(current_user, "is_authenticated", False) and (getattr(current_user, "role", "") or "").lower() == "vendor":
                    next_url = request.referrer or url_for("vendor.manage_shop")
                else:
                    next_url = request.referrer or url_for("landing")
            except Exception:
                next_url = request.referrer or url_for("landing")

        # Persist the chosen language for both POST and GET.
        # This keeps language switching reliable even if the click falls back
        # to a normal link navigation before the JS helper runs.
        session["lang"] = lang_code
        response = redirect(next_url)
        response.set_cookie(
            app.config.get("LANG_COOKIE_NAME", "lang"),
            lang_code,
            max_age=app.config.get("LANG_COOKIE_MAX_AGE", 63072000),
            samesite=app.config.get("LANG_COOKIE_SAMESITE", "Lax"),
            secure=app.config.get("LANG_COOKIE_SECURE", False),
        )
        return response

    def _is_safe_url(target):
        if not target:
            return False
        ref_url = urlparse(request.host_url)
        test_url = urlparse(urljoin(request.host_url, target))
        return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc

    @app.before_request
    def csrf_protect():
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return None
        if request.endpoint is None:
            return None
        if request.endpoint.endswith(".static"):
            return None
        token = (
            request.form.get("csrf_token")
            or request.headers.get("X-CSRFToken")
            or request.headers.get("X-CSRF-Token")
        )
        try:
            validate_csrf(token)
        except ValidationError:
            if (
                request.is_json
                or request.headers.get("X-Requested-With") in ("XMLHttpRequest", "fetch")
                or "application/json" in (request.headers.get("Accept") or "")
            ):
                return jsonify({"error": "csrf"}), 400
            flash("Session expirée ou action non autorisée.", "danger")
            if request.path.startswith("/cart/checkout"):
                return redirect(url_for("cart.checkout"))
            if request.path.startswith("/delivery"):
                return redirect(url_for("delivery_special.delivery_form"))
            if request.referrer and _is_safe_url(request.referrer):
                return redirect(request.referrer)
            try:
                from flask_login import current_user
                if getattr(current_user, "is_authenticated", False) and (getattr(current_user, "role", "") or "").lower() == "vendor":
                    return redirect(url_for("vendor.manage_shop"))
            except Exception:
                pass
            return redirect(url_for("landing"))

    @app.before_request
    def attach_csp_nonce():
        g.csp_nonce = None

    def _inject_csp_nonce_html(response, nonce: str):
        if not nonce:
            return response
        if response.direct_passthrough:
            return response
        if response.mimetype != "text/html":
            return response
        try:
            body = response.get_data(as_text=True)
        except Exception:
            return response
        if not body:
            return response
        lower_body = body.lower()
        if "<script" not in lower_body and "<style" not in lower_body:
            return response

        # Add nonce to inline/external script/style tags only if missing.
        updated_body = body
        if "<script" in lower_body:
            updated_body = _SCRIPT_NONCE_RE.sub(rf'\1 nonce="{nonce}"', updated_body)
        if "<style" in lower_body:
            updated_body = _STYLE_NONCE_RE.sub(rf'\1 nonce="{nonce}"', updated_body)
        if updated_body != body:
            response.set_data(updated_body)
            response.headers.pop("Content-Length", None)
        return response

    def _build_csp_header(nonce: str | None) -> str:
        strict_inline = bool(app.config.get("SECURITY_CSP_STRICT_INLINE", False))
        allow_style_inline = bool(app.config.get("SECURITY_CSP_ALLOW_STYLE_INLINE", True))
        nonce_token = f"'nonce-{nonce}' " if nonce else ""
        script_inline_token = "" if strict_inline else "'unsafe-inline' "
        # If a nonce is present in style-src, browsers ignore 'unsafe-inline' for style attributes.
        # Keep nonce protection for styles only when inline styles are explicitly disabled.
        style_inline_token = "'unsafe-inline' " if allow_style_inline else ""
        style_nonce_token = "" if allow_style_inline else nonce_token
        return (
            "default-src 'self'; "
            "img-src 'self' data: blob: https://images.unsplash.com; "
            "media-src 'self' data: blob:; "
            "font-src 'self' https://fonts.gstatic.com; "
            f"style-src 'self' {style_inline_token}{style_nonce_token}https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            f"script-src 'self' {script_inline_token}{nonce_token}https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

    @app.after_request
    def set_security_headers(response):
        if not app.config.get("SECURITY_HEADERS_ENABLED", True):
            return response

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        permissions_policy = (app.config.get("SECURITY_PERMISSIONS_POLICY", "") or "").strip()
        if permissions_policy:
            response.headers.setdefault("Permissions-Policy", permissions_policy)

        hsts_enabled = bool(app.config.get("SECURITY_HSTS_ENABLED"))
        request_is_secure = bool(request.is_secure)
        if (
            not request_is_secure
            and app.config.get("SECURITY_HSTS_TRUST_X_FORWARDED_PROTO", False)
        ):
            forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
            request_is_secure = forwarded_proto == "https"

        if hsts_enabled and request_is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        is_html_response = response.mimetype == "text/html"
        nonce = getattr(g, "csp_nonce", None)
        if (
            is_html_response
            and app.config.get("SECURITY_CSP_NONCE_ENABLED", True)
            and not nonce
        ):
            nonce = secrets.token_urlsafe(16)
            g.csp_nonce = nonce
        if app.config.get("SECURITY_CSP_ENABLED", True):
            csp = _build_csp_header(nonce)
            response.headers.setdefault("Content-Security-Policy", csp)

        if not request.path.startswith("/admin"):
            desired_lang = getattr(g, "set_lang_cookie", None)
            if desired_lang and desired_lang in app.config.get("LANGUAGES", []):
                response.set_cookie(
                    app.config.get("LANG_COOKIE_NAME", "lang"),
                    desired_lang,
                    max_age=app.config.get("LANG_COOKIE_MAX_AGE", 63072000),
                    samesite=app.config.get("LANG_COOKIE_SAMESITE", "Lax"),
                    secure=app.config.get("LANG_COOKIE_SECURE", False),
                )

        analytics_visitor_id = getattr(g, "set_analytics_visitor_cookie", None)
        if analytics_visitor_id:
            response.set_cookie(
                "bm_vid",
                analytics_visitor_id,
                max_age=60 * 60 * 24 * 180,
                samesite="Lax",
                secure=bool(app.config.get("SESSION_COOKIE_SECURE", False)),
                httponly=False,
            )

        if request.path.startswith("/static/") and response.status_code < 400:
            try:
                max_age = int(app.config.get("STATIC_CACHE_MAX_AGE", 86400))
            except Exception:
                max_age = 86400
            response.headers.setdefault("Cache-Control", f"public, max-age={max(300, max_age)}")

        # Enforce UTF-8 for HTML responses to avoid mojibake.
        if is_html_response:
            response.headers["X-BM-PWA-Session-Scope"] = "anon" if _pwa_session_scope() == "anon" else "auth"
            response.headers["X-BM-PWA-Cache"] = (
                "public" if _should_mark_response_public_for_pwa(response) else "private"
            )
            if app.config.get("SECURITY_CSP_NONCE_ENABLED", True) and nonce:
                response = _inject_csp_nonce_html(response, nonce)
            content_type = response.headers.get("Content-Type", "")
            if "charset=" not in content_type.lower():
                response.headers["Content-Type"] = "text/html; charset=utf-8"

        return response

    @app.teardown_request
    def cleanup_request(exception=None):
        if exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        db.session.remove()

    #  IMPORTATION DES BLUEPRINTS EXISTANTS
    fail_fast_critical_blueprints = bool(app.config.get("FAIL_FAST_CRITICAL_BLUEPRINTS", False))
    try:
        from .routes.shops import bp as shops_bp
        has_shops = True
    except ImportError as exc:
        if fail_fast_critical_blueprints:
            raise RuntimeError("Critical blueprint missing: app.routes.shops") from exc
        app.logger.warning("Module shops non trouve, mode degrade active")
        from flask import Blueprint
        shops_bp = Blueprint("shops", __name__)
        has_shops = False

    try:
        from .routes.api import bp as api_bp
        has_api = True
    except ImportError as exc:
        if fail_fast_critical_blueprints:
            raise RuntimeError("Critical blueprint missing: app.routes.api") from exc
        app.logger.warning("Module API non trouve, mode degrade active")
        from flask import Blueprint
        api_bp = Blueprint("api", __name__)
        has_api = False


    # Blueprints
    app.register_blueprint(auth.bp, url_prefix="/")
    app.register_blueprint(shop.bp, url_prefix="/shop")
    app.register_blueprint(vendor.bp, url_prefix="/vendor")
    app.register_blueprint(cart.bp)
    app.register_blueprint(booking.bp)
    app.register_blueprint(rentals.bp)
    app.register_blueprint(delivery.bp)
    app.register_blueprint(admin.bp)  # Blueprint deja prefixe /admin
    app.register_blueprint(admin_categories.bp)
    app.register_blueprint(admin_users.bp)  # Blueprint deja prefixe /admin

    #  ENREGISTRER LES AUTRES BLUEPRINTS
    if has_shops:
        app.register_blueprint(shops_bp, url_prefix="/")
    else:
        # Crer une route par dfaut pour shops
        @app.route("/shops")
        def list_shops_fallback():
            from .models.shop import Shop
            shops = Shop.query.filter_by(is_active=True).all()
            return render_template("shop/shops.html", shops=shops)

    if has_api:
        app.register_blueprint(api_bp)  # Blueprint deja prefixe /api


    # Compat: anciens liens /admin/admin/* -> /admin/*
    @app.route("/admin/admin/<path:subpath>")
    def compat_admin_redirect(subpath):
        return redirect(f"/admin/{subpath}")

    @app.route("/admin/admin/")
    def compat_admin_root_redirect():
        return redirect("/admin/")

    # Compat: anciens liens /api/api/* -> /api/*
    @app.route("/api/api/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def compat_api_redirect(subpath):
        return redirect(f"/api/{subpath}", code=307)

    @app.route("/api/api/", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def compat_api_root_redirect():
        return redirect("/api/", code=307)
    # Landing page - OPTIMISE POUR LE SYSTME DE BOUTIQUES
    @app.route("/")
    def landing():
        from .models.product import Product
        from .models.shop import Shop
        from .services.cache import get_categories, get_catalog_cache
        from .services.marketplace_feed import build_marketplace_feed

        def build_landing_payload():
            now = datetime.utcnow()
            promo_payload = build_marketplace_feed(page=1, per_page=12, promo_only="1")
            promo_data = list(promo_payload.get("data", []) or [])

            data = promo_data[:12]
            if len(data) < 12:
                fallback_payload = build_marketplace_feed(page=1, per_page=24)
                fallback_data = list(fallback_payload.get("data", []) or [])
                seen_keys = set()
                for item in data:
                    payload = item[0] if item else {}
                    seen_keys.add(
                        (
                            payload.get("item_type") or payload.get("kind") or "product",
                            payload.get("id") or payload.get("slug") or payload.get("name"),
                        )
                    )
                for item in fallback_data:
                    payload = item[0] if item else {}
                    item_key = (
                        payload.get("item_type") or payload.get("kind") or "product",
                        payload.get("id") or payload.get("slug") or payload.get("name"),
                    )
                    if item_key in seen_keys:
                        continue
                    data.append(item)
                    seen_keys.add(item_key)
                    if len(data) >= 12:
                        break

            featured_shops = (
                Shop.query
                .options(
                    load_only(
                        Shop.id,
                        Shop.name,
                        Shop.slug,
                        Shop.logo,
                        Shop.is_active,
                        Shop.is_verified,
                        Shop.created_at,
                    )
                )
                .filter_by(is_active=True, is_verified=True)
                .order_by(Shop.created_at.desc())
                .limit(4)
                .all()
            )

            shop_ids = [s.id for s in featured_shops]
            shop_counts = {}
            if shop_ids:
                shop_counts = dict(
                    db.session.query(Product.shop_id, db.func.count(Product.id))
                    .filter(Product.shop_id.in_(shop_ids), Product.is_active == True)
                    .group_by(Product.shop_id)
                    .all()
                )

            shops_data = []
            for featured_shop in featured_shops:
                shops_data.append({
                    "id": featured_shop.id,
                    "name": featured_shop.name,
                    "slug": featured_shop.slug,
                    "logo": featured_shop.logo,
                    "rating": 0.0,
                    "product_count": shop_counts.get(featured_shop.id, 0),
                })

            try:
                product_stats_row = (
                    db.session.query(
                        db.func.sum(
                            case((Product.kind == "physical", 1), else_=0)
                        ).label("physical"),
                        db.func.sum(
                            case((Product.kind == "service", 1), else_=0)
                        ).label("service"),
                    )
                    .filter(Product.is_active == True)
                    .first()
                )
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                product_stats_row = None

            products_count = int(getattr(product_stats_row, "physical", 0) or 0)
            services_count = int(getattr(product_stats_row, "service", 0) or 0)

            try:
                locations_count = int(
                    (
                        RentalListing.query
                        .join(Shop, Shop.id == RentalListing.shop_id)
                        .filter(
                            RentalListing.is_active == True,
                            RentalListing.status.in_(["active", "reserved"]),
                            RentalListing.expires_at > now,
                            Shop.is_active == True,
                            Shop.sql_allows_clause("location"),
                        )
                        .count()
                    )
                    or 0
                )
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                locations_count = 0

            return {
                "data": data,
                "featured_shops": shops_data,
                "market_stats": {
                    "products": int(products_count or 0),
                    "services": int(services_count or 0),
                    "locations": int(locations_count or 0),
                },
            }

        try:
            payload = get_catalog_cache("landing:v2", build_landing_payload, timeout=60)
        except Exception as exc:
            try:
                db.session.rollback()
            except Exception:
                pass
            current_app.logger.error("landing cache/build error: %s", exc)
            try:
                payload = build_landing_payload()
            except Exception as inner_exc:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                current_app.logger.error("landing fallback build error: %s", inner_exc)
                payload = {
                    "data": [],
                    "featured_shops": [],
                    "market_stats": {"products": 0, "services": 0, "locations": 0},
                }
        data = payload.get("data", [])
        featured_shops = payload.get("featured_shops", [])
        market_stats = payload.get("market_stats", {})

        categories = get_categories()

        return render_template(
            "home.html",
            data=data,
            categories=categories,
            featured_shops=featured_shops,
            market_stats=market_stats,
        )

    #  ROUTE POUR LA RECHERCHE GLOBALE
    @app.route("/search")
    def global_search():
        q = request.args.get("q", "").strip()
        search_type = request.args.get("type", "products")

        results = {
            "products": [],
            "shops": [],
            "categories": [],
            "locations": []
        }

        return render_template(
            "search/results.html",
            q=q,
            results=results,
            search_type=search_type
        )

    #  ROUTE POUR ACCDER  L'ADMIN (Bouton principal)
    @app.route("/admin-access")
    def admin_access_route():
        """Route d'accs au panel admin depuis le site principal"""
        from flask_login import current_user
        from flask import redirect, url_for, flash

        if not current_user.is_authenticated:
            flash("Veuillez vous connecter pour accéder à l'administration.", "warning")
            return redirect(url_for("auth.login"))

        if current_user.role != 'admin':
            flash("Accès réservé aux administrateurs.", "danger")
            return redirect(url_for("shop.home"))

        return redirect(url_for("admin_users.admin_dashboard"))

    @app.cli.command("cleanup_rentals")
    def cleanup_rentals_command():
        """Archive les locations expires/prises et supprime les mdias orphelins."""
        from .services.rentals import cleanup_expired_rentals

        result = cleanup_expired_rentals()
        click.echo(
            "cleanup_rentals => "
            f"archived={result.get('archived_count', 0)}, "
            f"media_removed={result.get('removed_media_files', 0)}, "
            f"orphan_removed={result.get('orphan_media_removed', 0)}, "
            f"archives_purged={result.get('purged_archives', 0)}"
        )

    @app.cli.command("cleanup")
    @click.option("--mode", type=click.Choice(["quick", "full"]), default="quick", show_default=True)
    @click.option("--days", type=int, default=6, show_default=True)
    def cleanup_command(mode: str, days: int):
        """Commande de nettoyage hors runtime web (a lancer via CLI)."""
        from .services.maintenance import run_and_store_maintenance_report

        safe_days = max(1, min(365, int(days)))
        report = run_and_store_maintenance_report(mode=mode, expired_days=safe_days)
        cleanup = report.get("cleanup", {})
        health = report.get("health", {})
        click.echo(
            "cleanup => "
            f"mode={report.get('mode')}, "
            f"days={safe_days}, "
            f"files_deleted={cleanup.get('files_deleted', 0)}, "
            f"orphans_removed={cleanup.get('orphan_media_removed', 0)}, "
            f"locations_purged={cleanup.get('locations_purged', 0)}, "
            f"cache_cleared={cleanup.get('cache_cleared', False)}, "
            f"sessions_deleted={cleanup.get('sessions_deleted', 0)}, "
            f"error_logs_purged={cleanup.get('error_logs_purged', 0)}, "
            f"uploads_size={health.get('uploads_size', 'N/A')}, "
            f"expired_locations={health.get('expired_locations_gt_days', 'N/A')}, "
            f"db_engine={health.get('db_engine', 'N/A')}, "
            f"persisted={report.get('persisted', False)}"
        )
        errors = (cleanup.get("errors") or []) + (health.get("errors") or [])
        if not report.get("persisted", False):
            click.echo(f"Persist warning: {report.get('persist_error', 'unknown')}")
        if errors:
            click.echo("Errors:")
            for err in errors[:20]:
                click.echo(f"- {err}")

    @app.cli.command("maintenance_cleanup")
    @click.option("--mode", type=click.Choice(["quick", "full"]), default="quick", show_default=True)
    @click.option("--days", type=int, default=6, show_default=True)
    def maintenance_cleanup_command(mode: str, days: int):
        """Nettoyage maintenance: quick/full."""
        from .services.maintenance import run_and_store_maintenance_report

        safe_days = max(1, min(365, int(days)))
        report = run_and_store_maintenance_report(mode=mode, expired_days=safe_days)
        cleanup = report.get("cleanup", {})
        health = report.get("health", {})
        click.echo(
            "maintenance_cleanup => "
            f"mode={report.get('mode')}, "
            f"days={safe_days}, "
            f"files_deleted={cleanup.get('files_deleted', 0)}, "
            f"orphans_removed={cleanup.get('orphan_media_removed', 0)}, "
            f"locations_purged={cleanup.get('locations_purged', 0)}, "
            f"cache_cleared={cleanup.get('cache_cleared', False)}, "
            f"sessions_deleted={cleanup.get('sessions_deleted', 0)}, "
            f"error_logs_purged={cleanup.get('error_logs_purged', 0)}, "
            f"uploads_size={health.get('uploads_size', 'N/A')}, "
            f"expired_locations={health.get('expired_locations_gt_days', 'N/A')}, "
            f"db_engine={health.get('db_engine', 'N/A')}, "
            f"persisted={report.get('persisted', False)}"
        )
        errors = (cleanup.get("errors") or []) + (health.get("errors") or [])
        if not report.get("persisted", False):
            click.echo(f"Persist warning: {report.get('persist_error', 'unknown')}")
        if errors:
            click.echo("Errors:")
            for err in errors[:20]:
                click.echo(f"- {err}")

    @app.cli.group("maintenance")
    def maintenance_mode_group():
        """Maintenance mode commands (manual + schedule)."""

    @maintenance_mode_group.command("enable")
    @click.option("--message", default=None, help="Maintenance message shown to visitors.")
    def maintenance_mode_enable_command(message: str | None):
        from .services.maintenance_mode import (
            enable_maintenance_mode,
            format_maintenance_datetime,
        )

        state = enable_maintenance_mode(message=message)
        click.echo("Maintenance: ON")
        click.echo(f"message={state.get('message') or ''}")
        click.echo(f"enabled_at={format_maintenance_datetime(state.get('enabled_at'))}")
        click.echo(f"starts_at={format_maintenance_datetime(state.get('starts_at'))}")
        click.echo(f"ends_at={format_maintenance_datetime(state.get('ends_at'))}")

    @maintenance_mode_group.command("disable")
    def maintenance_mode_disable_command():
        from .services.maintenance_mode import (
            disable_maintenance_mode,
            format_maintenance_datetime,
        )

        state = disable_maintenance_mode()
        click.echo("Maintenance: OFF")
        click.echo(f"message={state.get('message') or ''}")
        click.echo(f"enabled_at={format_maintenance_datetime(state.get('enabled_at'))}")
        click.echo(f"starts_at={format_maintenance_datetime(state.get('starts_at'))}")
        click.echo(f"ends_at={format_maintenance_datetime(state.get('ends_at'))}")

    @maintenance_mode_group.command("status")
    def maintenance_mode_status_command():
        from .services.maintenance_mode import (
            format_maintenance_datetime,
            get_maintenance_state,
        )

        state = get_maintenance_state(force_refresh=True)
        status_label = "ON" if state.get("active") else "OFF"
        click.echo(f"status={status_label}")
        click.echo(f"manual_enabled={bool(state.get('manual_enabled'))}")
        click.echo(f"scheduled_active={bool(state.get('scheduled_active'))}")
        click.echo(f"message={state.get('message') or ''}")
        click.echo(f"enabled_at={format_maintenance_datetime(state.get('enabled_at'))}")
        click.echo(f"starts_at={format_maintenance_datetime(state.get('starts_at'))}")
        click.echo(f"ends_at={format_maintenance_datetime(state.get('ends_at'))}")
        if not state.get("available", True):
            click.echo(f"warning={state.get('error') or 'settings unavailable'}")

    @maintenance_mode_group.command("schedule")
    @click.option("--start", "start_raw", required=True, help='Start datetime, e.g. "2026-02-25 02:00".')
    @click.option("--end", "end_raw", required=True, help='End datetime, e.g. "2026-02-25 02:15".')
    @click.option("--message", default=None, help="Optional maintenance message.")
    def maintenance_mode_schedule_command(start_raw: str, end_raw: str, message: str | None):
        from .services.maintenance_mode import (
            format_maintenance_datetime,
            parse_maintenance_datetime,
            schedule_maintenance_mode,
        )

        try:
            starts_at = parse_maintenance_datetime(start_raw)
            ends_at = parse_maintenance_datetime(end_raw)
            if starts_at is None or ends_at is None:
                raise ValueError("Both --start and --end are required.")
        except ValueError as exc:
            raise click.BadParameter(str(exc))

        state = schedule_maintenance_mode(starts_at=starts_at, ends_at=ends_at, message=message)
        click.echo("Maintenance schedule saved")
        click.echo(f"status={'ON' if state.get('active') else 'OFF'}")
        click.echo(f"message={state.get('message') or ''}")
        click.echo(f"starts_at={format_maintenance_datetime(state.get('starts_at'))}")
        click.echo(f"ends_at={format_maintenance_datetime(state.get('ends_at'))}")

        # Contexte global (ex: badge panier)
    @app.context_processor
    def inject_cart_count():
        from flask_login import current_user
        from sqlalchemy.orm.exc import DetachedInstanceError

        key = None

        # IMPORTANT: ne pas utiliser current_user.is_authenticated ici (peut déclencher DetachedInstanceError)
        try:
            user_id = getattr(current_user, "id", None)
            if user_id:
                key = f"cart_user_{user_id}"
        except DetachedInstanceError:
            key = None
        except Exception:
            key = None

        # Panier invité si pas d'utilisateur (ou si user détaché)
        if not key:
            if "cart_guest" in session:
                key = "cart_guest"
            else:
                for k in session.keys():
                    if k.startswith("cart_guest_"):
                        key = k
                        break

        if not key:
            return {"cart_count": 0}

        cart = session.get(key, {})
        count = 0
        if isinstance(cart, dict):
            for value in cart.values():
                try:
                    count += max(0, int(value or 0))
                except (TypeError, ValueError):
                    continue
        return {"cart_count": count}

    # User loader
    @login_manager.user_loader
    def load_user(user_id):
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None

        try:
            return db.session.get(User, uid)
        except OperationalError:
            try:
                db.session.remove()
            except Exception:
                pass
            try:
                return db.session.get(User, uid)
            except Exception:
                current_app.logger.exception(
                    "auth.load_user.db_connection_failed",
                    extra={"user_id": uid},
                )
                return None
        except Exception:
            try:
                db.session.remove()
            except Exception:
                pass
            current_app.logger.exception(
                "auth.load_user.unexpected_error",
                extra={"user_id": uid},
            )
            return None

    # ✅ INITIALISATION DES COMMANDES CLI (AJOUTÉ ICI)
    init_cli_commands(app)

    @app.route("/sitemap.xml")
    def sitemap():
        from xml.sax.saxutils import escape
        from .models.product import Product
        from .models.shop import Shop
        from .models.rental import RentalListing
        from .models.category import Category

        urls = []
        seen = set()

        def add_url(value):
            if not value:
                return
            url_value = str(value).strip()
            if not url_value or url_value in seen:
                return
            seen.add(url_value)
            urls.append(url_value)

        def build_category_url(category):
            category_slug = getattr(category, "slug", None)
            category_detail_endpoint = None
            for endpoint_name in ("category.detail", "categories.detail", "shop.category_detail"):
                if endpoint_name in app.view_functions:
                    category_detail_endpoint = endpoint_name
                    break
            if category_detail_endpoint and category_slug:
                return url_for(category_detail_endpoint, slug=category_slug, _external=True)
            return url_for("shop.home", cat=category.id, _external=True)

        # Pages statiques
        add_url(url_for("landing", _external=True))
        add_url(url_for("shops.list_shops", _external=True))
        add_url(url_for("rentals.locations_home", _external=True))
        add_url(url_for("shop.home", _external=True))
        add_url(url_for("global_search", _external=True))

        # ✅ Boutiques — avec limite pour éviter de charger toute la DB
        try:
            for shop in (
                Shop.query
                .filter(Shop.is_active == True)
                .order_by(Shop.id.asc())
                .limit(2000)
                .all()
            ):
                if getattr(shop, "slug", None):
                    add_url(url_for("shops.shop_detail", shop_slug=shop.slug, _external=True))
        except Exception:
            app.logger.exception("sitemap.shops_error")

        # ✅ Produits — avec limite
        try:
            for product in (
                Product.query
                .filter(Product.is_active == True)
                .order_by(Product.id.asc())
                .limit(5000)
                .all()
            ):
                add_url(url_for("shop.product_detail", pid=product.id, _external=True))
        except Exception:
            app.logger.exception("sitemap.products_error")

        # ✅ Locations — avec limite
        try:
            for listing in (
                RentalListing.query
                .filter(RentalListing.is_active == True)
                .order_by(RentalListing.id.asc())
                .limit(2000)
                .all()
            ):
                listing_slug = getattr(listing, "slug", None)
                if listing_slug:
                    add_url(url_for("rentals.location_detail", slug=listing_slug, _external=True))
        except Exception:
            app.logger.exception("sitemap.listings_error")

        # ✅ Catégories — avec limite
        try:
            categories_query = Category.query.order_by(Category.id.asc()).limit(500)
            if hasattr(Category, "is_active"):
                categories_query = categories_query.filter(Category.is_active == True)
            for category in categories_query.all():
                add_url(build_category_url(category))
        except Exception:
            app.logger.exception("sitemap.categories_error")

        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for url in urls:
            xml_lines.extend([
                "<url>",
                f"<loc>{escape(url)}</loc>",
                "</url>",
            ])
        xml_lines.append("</urlset>")
        xml = "\n".join(xml_lines)
        return Response(xml, mimetype="application/xml")

    return app


_SQLITE_PRAGMAS_REGISTERED = False


def _register_sqlite_pragmas():
    global _SQLITE_PRAGMAS_REGISTERED
    if _SQLITE_PRAGMAS_REGISTERED:
        return

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        if not isinstance(dbapi_connection, sqlite3.Connection):
            return
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()

    _SQLITE_PRAGMAS_REGISTERED = True
