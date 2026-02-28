import os
import re
import secrets
import sqlite3
import click
from datetime import datetime
from flask import Flask, render_template, session, request, redirect, url_for, flash, jsonify, current_app, g
from urllib.parse import urlparse, urljoin
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_wtf.csrf import generate_csrf, validate_csrf
from wtforms.validators import ValidationError
from sqlalchemy import event, or_
from sqlalchemy.engine import Engine
from .config import Config
from .extensions import db, login_manager, migrate
from .models.user import User
from .models.shop import Shop
from .models.rental import RentalListing, RentalMedia
from .routes import auth, shop, vendor, cart, booking, admin, admin_categories, admin_users, rentals, delivery, courier
from .services.logging_service import logging_service
from .services.image import image_variant
from .services.cache import cache
from .services.i18n_labels import (
    label_delivery_status,
    label_location_status,
    label_order_status,
    label_source,
)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

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
    login_manager.login_message_category = "warning"
    login_manager.session_protection = "basic"
    cache.init_app(app)
    with app.app_context():
        logging_service.setup_logging()
        if app.config.get("SECRET_KEY") == "dev":
            app.logger.warning("SECURITY: SECRET_KEY par dfaut dtect. Configurez une cl forte.")

    if (app.config.get("SQLALCHEMY_DATABASE_URI") or "").startswith("sqlite:///"):
        _register_sqlite_pragmas()

    @app.route("/sw.js")
    def service_worker():
        response = current_app.send_static_file("sw.js")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.route("/health")
    def health():
        return jsonify(status="ok"), 200

    @app.route("/maintenance")
    def maintenance_page():
        from .services.maintenance_mode import get_maintenance_state

        state = get_maintenance_state(force_refresh=True)
        status_code = 503 if state.get("active") else 200
        return render_template("maintenance.html", maintenance=state), status_code


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
        }

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
    def track_live_traffic():
        try:
            from .services.traffic_stats import track_request_hit as _track_request_hit

            _track_request_hit(path=request.path, endpoint=request.endpoint)
        except Exception:
            return None

    MAINTENANCE_WHITELIST_PREFIXES = (
        "/maintenance",
        "/admin",
        "/static",
        "/health",
        "/cart/track",
        "/login",
        "/logout",
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
            from .services.maintenance_mode import get_maintenance_state

            state = get_maintenance_state()
            if state.get("active"):
                return render_template("maintenance.html", maintenance=state), 503
        except Exception:
            # Safe fallback requested by product: maintenance OFF on DB/runtime issue.
            return None

        return None

    @app.before_request
    def enforce_vendor_private_mode():
        try:
            from flask_login import current_user
        except Exception:
            return None

        if not getattr(current_user, "is_authenticated", False):
            return None

        role = (getattr(current_user, "role", "") or "").lower()
        if role != "vendor":
            return None

        endpoint = request.endpoint or ""
        path = request.path or "/"

        if endpoint.endswith(".static") or path.startswith("/static/"):
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
            shop_slug = (request.view_args or {}).get("shop_slug")
            if shop_slug:
                own_shop = (
                    Shop.query.with_entities(Shop.id)
                    .filter(Shop.vendor_id == current_user.id, Shop.slug == shop_slug)
                    .first()
                )
                if own_shop:
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

        return {
            "current_lang": getattr(g, "lang", app.config.get("DEFAULT_LANG", "fr")),
            "supported_langs": app.config.get("LANGUAGES", ["fr", "en", "ary"]),
            "rtl_langs": app.config.get("RTL_LANGUAGES", []),
            "label_delivery_status": _label_delivery,
            "label_order_status": _label_order,
            "label_source": _label_source,
            "label_location_status": _label_location_status,
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

        if request.method == "POST":
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

        # GET is non-mutating by design.
        return redirect(next_url)

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
            flash("Session expiree ou action non autorisee.", "danger")
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
        if app.config.get("SECURITY_CSP_NONCE_ENABLED", True):
            g.csp_nonce = secrets.token_urlsafe(16)
        else:
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

        # Add nonce to inline/external script/style tags only if missing.
        body = re.sub(
            r"(<script\b)(?![^>]*\bnonce=)",
            rf'\1 nonce="{nonce}"',
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(
            r"(<style\b)(?![^>]*\bnonce=)",
            rf'\1 nonce="{nonce}"',
            body,
            flags=re.IGNORECASE,
        )
        response.set_data(body)
        response.headers.pop("Content-Length", None)
        return response

    def _build_csp_header(nonce: str | None) -> str:
        strict_inline = bool(app.config.get("SECURITY_CSP_STRICT_INLINE", False))
        allow_style_inline = bool(app.config.get("SECURITY_CSP_ALLOW_STYLE_INLINE", True))
        nonce_token = f"'nonce-{nonce}' " if nonce else ""
        script_inline_token = "" if strict_inline else "'unsafe-inline' "
        style_inline_token = "'unsafe-inline' " if allow_style_inline else ""
        return (
            "default-src 'self'; "
            "img-src 'self' data: https://images.unsplash.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            f"style-src 'self' {style_inline_token}{nonce_token}https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
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
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=()",
        )

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

        nonce = getattr(g, "csp_nonce", None)
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

        if request.path.startswith("/static/") and response.status_code < 400:
            try:
                max_age = int(app.config.get("STATIC_CACHE_MAX_AGE", 86400))
            except Exception:
                max_age = 86400
            response.headers.setdefault("Cache-Control", f"public, max-age={max(300, max_age)}")

        # Enforce UTF-8 for HTML responses to avoid mojibake.
        if response.mimetype == "text/html":
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
    app.register_blueprint(courier.bp)
    
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
        from .models.promo import Promo
        from .services.pricing import prix_final
        from .services.cache import get_categories, get_catalog_cache
        
        def build_landing_payload():
            products = Product.query.filter_by(is_active=True)\
                .order_by(Product.created_at.desc())\
                .limit(12).all()

            product_ids = [p.id for p in products]
            now = datetime.utcnow()
            promos = Promo.query.filter(
                Promo.product_id.in_(product_ids), Promo.end_date >= now
            ).all() if product_ids else []
            promo_map = {}
            for pr in promos:
                if pr.product_id not in promo_map or pr.end_date < promo_map[pr.product_id].end_date:
                    promo_map[pr.product_id] = pr

            product_entries = []
            for p in products:
                promo = promo_map.get(p.id)
                final = prix_final(p, promo)
                discount = promo.value if promo and promo.type == "percentage" else 0
                product_dict = {
                    "id": p.id,
                    "name": p.name,
                    "price": float(p.price or 0),
                    "stock": p.stock or 0,
                    "image_file": p.image_file,
                    "kind": (getattr(p, "kind", None) or "physical"),
                }
                product_entries.append((product_dict, final, discount))

            active_locations = (
                RentalListing.query
                .join(Shop, Shop.id == RentalListing.shop_id)
                .filter(
                    RentalListing.is_active == True,
                    RentalListing.status.in_(["active", "reserved"]),
                    RentalListing.expires_at > now,
                    Shop.is_active == True,
                    Shop.sql_allows_clause("location"),
                )
                .order_by(RentalListing.created_at.desc())
                .limit(6)
                .all()
            )

            location_cover_map = {}
            listing_ids = [listing.id for listing in active_locations]
            if listing_ids:
                media_rows = (
                    db.session.query(RentalMedia.listing_id, RentalMedia.file_path)
                    .filter(
                        RentalMedia.listing_id.in_(listing_ids),
                        RentalMedia.kind == "image",
                    )
                    .order_by(RentalMedia.listing_id.asc(), RentalMedia.id.asc())
                    .all()
                )
                for listing_id, file_path in media_rows:
                    if listing_id not in location_cover_map and file_path:
                        location_cover_map[listing_id] = str(file_path)

            location_entries = []
            for listing in active_locations:
                location_dict = {
                    "id": listing.id,
                    "slug": listing.slug,
                    "name": listing.title,
                    "price": float((listing.rent_cents or 0) / 100),
                    "stock": None,
                    "image_file": location_cover_map.get(listing.id, ""),
                    "kind": "location",
                    "city": listing.city,
                    "area": listing.area,
                    "listing_type": listing.listing_type,
                }
                location_entries.append((location_dict, float((listing.rent_cents or 0) / 100), 0))

            data = []
            max_len = max(len(product_entries), len(location_entries))
            for idx in range(max_len):
                if idx < len(product_entries):
                    data.append(product_entries[idx])
                if idx < len(location_entries):
                    data.append(location_entries[idx])

            data = data[:12]

            featured_shops = Shop.query.filter_by(is_active=True, is_verified=True)\
                .order_by(Shop.created_at.desc())\
                .limit(4).all()

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
                    "rating": featured_shop.rating,
                    "product_count": shop_counts.get(featured_shop.id, 0),
                })

            products_count = Product.query.filter(
                Product.is_active == True,
                Product.kind == "physical",
            ).count()
            services_count = Product.query.filter(
                Product.is_active == True,
                Product.kind == "service",
            ).count()
            locations_count = (
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

            return {
                "data": data,
                "featured_shops": shops_data,
                "market_stats": {
                    "products": int(products_count or 0),
                    "services": int(services_count or 0),
                    "locations": int(locations_count or 0),
                },
            }

        payload = get_catalog_cache("landing", build_landing_payload, timeout=60)
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
        from .models.product import Product
        from .models.shop import Shop
        from .models.category import Category
        from .models.rental import RentalListing
        from flask import request
        
        q = request.args.get("q", "").strip()
        search_type = request.args.get("type", "products")
        
        results = {
            "products": [],
            "shops": [],
            "categories": [],
            "locations": []
        }
        
        if q:
            # Recherche de produits
            if search_type in ["products", "all"]:
                product_results = Product.query.filter(
                    Product.is_active == True,
                    Product.name.ilike(f"%{q}%")
                ).limit(10).all()
                results["products"] = product_results
            
            # Recherche de boutiques
            if search_type in ["shops", "all"]:
                shop_results = Shop.query.filter(
                    Shop.is_active == True,
                    (Shop.name.ilike(f"%{q}%") | Shop.description.ilike(f"%{q}%"))
                ).limit(10).all()
                results["shops"] = shop_results
            
            # Recherche de catgories
            if search_type in ["products", "all"]:
                category_results = Category.query.filter(
                    Category.name.ilike(f"%{q}%")
                ).limit(5).all()
                results["categories"] = category_results

            # Recherche de locations
            if search_type in ["locations", "all"]:
                now = datetime.utcnow()
                location_results = RentalListing.query.filter(
                    RentalListing.is_active == True,
                    RentalListing.status.in_(["active", "reserved"]),
                    RentalListing.expires_at > now,
                    or_(
                        RentalListing.title.ilike(f"%{q}%"),
                        RentalListing.city.ilike(f"%{q}%"),
                        RentalListing.area.ilike(f"%{q}%")
                    )
                ).limit(10).all()
                results["locations"] = location_results
        
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
            flash("Veuillez vous connecter pour accder  l'administration", "warning")
            return redirect(url_for("auth.login"))
        
        if current_user.role != 'admin':
            flash("Accs rserv aux administrateurs", "danger")
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
        from .services.guest_session import GuestSessionManager

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
                    guest_id = GuestSessionManager.get_or_create_guest_token()
                    key = f"cart_guest_{guest_id}"

        cart = session.get(key, {})
        count = sum(cart.values()) if isinstance(cart, dict) else 0
        return {"cart_count": count}

    # User loader
    @login_manager.user_loader
    def load_user(user_id):
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None
        return db.session.get(User, uid)


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
