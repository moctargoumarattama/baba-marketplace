from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from slugify import slugify
from sqlalchemy import func, or_
from sqlalchemy.orm import load_only, selectinload
from ..extensions import db
from ..models.audit import AuditLog
from ..models.platform_settings import PlatformSettings
from ..models.rental import RentalArchive, RentalListing, RentalMedia, rental_duration_days_for_type
from ..models.shop import Shop
from ..models.user import User
from ..services.audit import log_access
from ..services.db_session import safe_session_rollback
from ..services.pagination import paginate_with_clamped_page, page_from_args
from ..services.date_filters import resolve_date_filter
from ..services.shop_access import ensure_shop_allows, ensure_vendor_allows
from ..services.support_whatsapp import (
    append_support_request,
    build_support_whatsapp_url,
    safe_support_back_target,
    support_user_label,
)
from ..services.rentals import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_COUNT,
    MAX_VIDEO_BYTES,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    archive_and_remove_listing,
    cents_to_dh,
    commission_amount_from_owner_fee,
    delete_static_file,
    rental_existing_video_poster_rel_path,
    save_rental_image,
    save_rental_video,
)
from ..services.vendor_push import notify_location_inquiry


bp = Blueprint("rentals", __name__)
OWNER_LOCATION_HISTORY_DAYS = 7


def _is_location_form_modal_request() -> bool:
    modes = {"rentals.owner_location_new": "location-create", "rentals.owner_location_edit": "location-edit"}
    return request.endpoint in modes and request.headers.get("X-Vendor-Modal") == modes[request.endpoint]


def _location_form_json(payload: dict, status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Vary"] = "Cookie, X-Vendor-Modal"
    return response


@bp.before_request
def guard_location_form_modal():
    if not _is_location_form_modal_request():
        return None
    if not current_user.is_authenticated:
        listing_id = (request.view_args or {}).get("listing_id")
        target = url_for("rentals.owner_locations", edit_location=listing_id) if listing_id else url_for("rentals.owner_locations", new="location")
        return _location_form_json({
            "success": False,
            "message": "Votre session a expiré. Connectez-vous pour continuer.",
            "redirect_url": url_for("auth.login", next=target),
        }, 401)
    if getattr(current_user, "role", None) != "vendor":
        return _location_form_json({"success": False, "message": "Accès réservé aux propriétaires."}, 403)


def _location_form_cents(value: str | None, *, required: bool = True) -> int | None:
    raw = (value or "").strip().replace(",", ".")
    if not raw:
        if required:
            raise ValueError("Saisissez un montant.")
        return None
    try:
        amount = Decimal(raw)
        if not amount.is_finite() or amount < 0 or amount > Decimal("21474836.47"):
            raise ValueError("amount_invalid")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("amount_precision_invalid")
        return int(amount * 100)
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Saisissez un montant positif ou nul avec au maximum 2 décimales.") from exc


def _location_upload_size(file_obj) -> int:
    try:
        position = file_obj.stream.tell()
        file_obj.stream.seek(0, 2)
        size = int(file_obj.stream.tell())
        file_obj.stream.seek(position)
        return size
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError("Impossible de lire ce fichier. Sélectionnez-le à nouveau.") from exc


def _cleanup_location_files(saved_files: list[str]) -> None:
    for relative_path in saved_files:
        try:
            delete_static_file(relative_path)
        except Exception:
            current_app.logger.exception("rental.form.media_cleanup_failed")


def _is_ajax_request() -> bool:
    return (
        request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )


def _support_whatsapp_number() -> str:
    raw = (
        current_app.config.get("RENTAL_VISIT_WHATSAPP_NUMBER")
        or current_app.config.get("SUPPORT_WHATSAPP_NUMBER")
        or current_app.config.get("ADMIN_PHONE")
    )
    return "".join(ch for ch in str(raw) if ch.isdigit())


def _to_cents(value: str, field_name: str, required: bool = True) -> int | None:
    raw = (value or "").strip().replace(",", ".")
    if not raw:
        if required:
            raise ValueError(f"{field_name} est obligatoire.")
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} invalide.") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} doit être positif.")
    return int(round(parsed * 100))


def _format_dt(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%d/%m/%Y %H:%M")


def _build_listing_slug(title: str, exclude_id: int | None = None) -> str:
    base = slugify(title or "")[:180] or "location"
    candidate = base
    idx = 2
    while True:
        query = RentalListing.query.filter_by(slug=candidate)
        if exclude_id:
            query = query.filter(RentalListing.id != exclude_id)
        if not query.first():
            return candidate
        candidate = f"{base}-{idx}"
        idx += 1


def _bps_to_percent(rate_bps: int | None) -> float:
    return round((int(rate_bps or 0) / 100), 2)


def _coerce_duration_days(value, *, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(fallback)
    return max(1, min(3650, parsed))


def _redirect_internal_next(raw_target: str | None, fallback_endpoint: str, **fallback_values):
    target = str(raw_target or "").strip()
    if target.endswith("?"):
        target = target[:-1]
    if target.startswith("/"):
        return redirect(target)
    return redirect(url_for(fallback_endpoint, **fallback_values))


def _public_listing_query():
    now = datetime.utcnow()
    return (
        RentalListing.query
        .join(Shop, Shop.id == RentalListing.shop_id)
        .filter(RentalListing.is_active == True)
        .filter(RentalListing.status.in_(["active", "reserved"]))
        .filter(RentalListing.expires_at > now)
        .filter(Shop.is_active == True)
        .filter(Shop.sql_allows_clause("location"))
    )


def _owner_required():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if getattr(current_user, "role", None) != "vendor":
        flash("Accès réservé aux propriétaires.", "warning")
        return redirect(url_for("shop.home"))
    return None


@bp.route("/owner/support/whatsapp")
@login_required
def owner_support_whatsapp():
    guard = _owner_required()
    if guard:
        return guard

    page_name = (request.args.get("page") or "Mes locations").strip()[:120]
    page_url = (request.args.get("page_url") or "").strip()[:400]
    source = (request.args.get("source") or "").strip()[:160]
    item_name = (request.args.get("item") or "").strip()[:160]
    back_url = safe_support_back_target(request.args.get("back"), url_for("rentals.owner_locations"))
    shop = Shop.query.filter_by(vendor_id=current_user.id).first()

    lines = [
        "Bonjour, je signale un problème sur mes locations.",
        f"Compte: {support_user_label(current_user)} (id: {current_user.id})",
    ]
    if shop and getattr(shop, "name", None):
        lines.append(f"Espace: {shop.name}")
    lines.append(f"Page: {page_name}")
    if item_name:
        lines.append(f"Annonce: {item_name}")
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
        support_scope="Aide pour les locations",
        support_title="Signaler un problème",
        support_copy="Les informations sur l'annonce et votre compte sont ajoutées au message. Vérifiez-le dans WhatsApp avant de l'envoyer.",
        back_url=back_url,
        back_label="Retour à la page",
    )


def _admin_required():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if getattr(current_user, "role", None) not in {"admin", "manager"}:
        flash("Accès réservé aux administrateurs.", "warning")
        return redirect(url_for("shop.home"))
    return None


def _normalize_admin_locations_section(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in {"listings", "archives", "both"} else ""


def _owner_shops(owner_id: int, location_only: bool = False):
    query = Shop.query.filter_by(vendor_id=owner_id)
    if location_only:
        query = query.filter(Shop.sql_allows_clause("location"))
    return query.order_by(Shop.name.asc()).all()


@bp.route("/locations")
def locations_home():
    if not (request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest") or "application/json" in (request.headers.get("Accept") or "")):
        allowed = ("q", "city", "type", "listing_type", "property_type", "min", "max", "min_price", "max_price", "page", "sort", "shop")
        filters = {key: request.args[key] for key in allowed if request.args.get(key)}
        return redirect(url_for("landing", open="locations", **filters))
    q = (request.args.get("q") or "").strip()
    search_q = q if len(q) >= 2 else ""
    description_search_q = q if len(q) >= 3 else ""
    listing_type = (request.args.get("type") or "").strip().lower()
    property_type = (request.args.get("property_type") or "").strip().lower()
    city_area = (request.args.get("city") or "").strip()
    city_area_query = city_area if len(city_area) >= 2 else ""
    price_min = (request.args.get("min") or "").strip()
    price_max = (request.args.get("max") or "").strip()
    page = page_from_args(request.args)

    if listing_type not in ("monthly", "daily"):
        listing_type = ""
    if property_type not in ("room", "apartment", "studio", "store"):
        property_type = ""

    query = _public_listing_query().options(
        selectinload(RentalListing.media).load_only(
            RentalMedia.id,
            RentalMedia.kind,
            RentalMedia.file_path,
            RentalMedia.listing_id,
        ),
    )

    min_price_value = None
    max_price_value = None
    try:
        if price_min:
            min_price_value = float(price_min.replace(",", "."))
            query = query.filter(RentalListing.rent_cents >= _to_cents(price_min, "Prix min"))
        if price_max:
            max_price_value = float(price_max.replace(",", "."))
            query = query.filter(RentalListing.rent_cents <= _to_cents(price_max, "Prix max"))
    except ValueError:
        flash("Le prix saisi n'est pas valide. Saisissez un montant positif.", "warning")

    if q and not search_q:
        query = query.filter(False)
    elif search_q:
        like = f"%{search_q}%"
        search_clauses = [
            RentalListing.title.ilike(like),
            RentalListing.city.ilike(like),
            RentalListing.area.ilike(like),
        ]
        if description_search_q:
            search_clauses.append(RentalListing.description.ilike(f"%{description_search_q}%"))
        query = query.filter(or_(*search_clauses))
    if listing_type:
        query = query.filter(RentalListing.listing_type == listing_type)
    if property_type:
        query = query.filter(RentalListing.property_type == property_type)
    if city_area and not city_area_query:
        query = query.filter(False)
    elif city_area_query:
        like_city = f"%{city_area_query}%"
        query = query.filter((RentalListing.city.ilike(like_city)) | (RentalListing.area.ilike(like_city)))

    per_page = 12
    pagination = paginate_with_clamped_page(
        query.order_by(RentalListing.created_at.desc(), RentalListing.id.desc()),
        page=page,
        per_page=per_page,
        error_out=False,
    )
    listings = pagination.items
    has_active_filters = bool(q or listing_type or property_type or city_area or price_min or price_max)

    return render_template(
        "partials/_locations_listing.html",
        listings=listings,
        pagination=pagination,
        q=q,
        listing_type=listing_type,
        property_type=property_type,
        city_area=city_area,
        price_min=price_min,
        price_max=price_max,
        has_active_filters=has_active_filters,
        cents_to_dh=cents_to_dh,
        rental_video_poster_rel_path=rental_existing_video_poster_rel_path,
        now=datetime.utcnow(),
    )


@bp.route("/location/<string:slug>")
def location_detail(slug: str):
    listing = (
        _public_listing_query()
        .options(selectinload(RentalListing.media), selectinload(RentalListing.shop))
        .filter(RentalListing.slug == slug)
        .first_or_404()
    )

    images = [m for m in (listing.media or []) if m.kind == "image"]
    videos = [m for m in (listing.media or []) if m.kind == "video"]
    return render_template(
        "locations/detail.html",
        listing=listing,
        images=images,
        videos=videos,
        cents_to_dh=cents_to_dh,
        rental_video_poster_rel_path=rental_existing_video_poster_rel_path,
    )


@bp.route("/location/<string:slug>/inquiry", methods=["GET", "POST"])
def location_inquiry(slug: str):
    listing = _public_listing_query().filter(RentalListing.slug == slug).first_or_404()
    default_name = ""
    default_phone = ""
    if current_user.is_authenticated:
        default_name = (getattr(current_user, "full_name", "") or getattr(current_user, "username", "") or "").strip()
        default_phone = (getattr(current_user, "phone", "") or "").strip()

    form_data = {
        "name": default_name,
        "phone": default_phone,
        "desired_date": "",
        "message": "",
    }

    if request.method == "POST":
        form_data["name"] = (request.form.get("name") or "").strip()
        form_data["phone"] = (request.form.get("phone") or "").strip()
        form_data["desired_date"] = (request.form.get("desired_date") or "").strip()
        form_data["message"] = (request.form.get("message") or "").strip()

        if not form_data["name"] or not form_data["phone"]:
            flash("Nom et téléphone sont obligatoires.", "danger")
            return render_template(
                "locations/inquiry.html",
                listing=listing,
                form_data=form_data,
                cents_to_dh=cents_to_dh,
            )

        listing_url = url_for("rentals.location_detail", slug=listing.slug, _external=True)
        price_txt = cents_to_dh(listing.rent_cents)
        lines = [
            f"Bonjour, je veux une visite pour: {listing.title} ({price_txt}).",
            f"Lien: {listing_url}",
            f"Mon nom: {form_data['name']}",
            f"Tel: {form_data['phone']}",
            f"Date souhaitée: {form_data['desired_date'] or '-'}",
            f"Message: {form_data['message'] or '-'}",
        ]
        try:
            notify_location_inquiry(listing, form_data)
        except Exception:
            current_app.logger.exception(
                "vendor_push.location_inquiry_notify_failed",
                extra={"listing_id": getattr(listing, "id", None)},
            )
        wa_number = _support_whatsapp_number()
        wa_url = f"https://wa.me/{wa_number}?text={quote(chr(10).join(lines))}"
        return render_template(
            "support/open_whatsapp.html",
            wa_url=wa_url,
            support_scope="Demande de visite",
            support_title="Envoyer votre demande de visite",
            support_copy="Votre message contient l'annonce et vos coordonnées. Ouvrez WhatsApp pour le vérifier et l'envoyer.",
            support_hint="La date de visite reste à confirmer avec l'agence.",
            back_url=url_for("rentals.location_inquiry", slug=listing.slug),
            back_label="Retour au formulaire",
            secondary_url=url_for("rentals.location_detail", slug=listing.slug),
            secondary_label="Voir l'annonce",
            secondary_icon="bi-house-door",
        )

    return render_template(
        "locations/inquiry.html",
        listing=listing,
        form_data=form_data,
        cents_to_dh=cents_to_dh,
    )


@bp.route("/owner/locations")
@login_required
def owner_locations():
    guard = _owner_required()
    if guard:
        return guard
    access_guard = ensure_vendor_allows(
        current_user,
        "location",
        fallback_endpoint="vendor.manage_shop",
        strict_forbidden=True,
    )
    if access_guard:
        return access_guard

    status = (request.args.get("status") or "").strip().lower()
    shop_id = request.args.get("shop", type=int)
    q = (request.args.get("q") or "").strip()

    shops = _owner_shops(current_user.id, location_only=True)
    shop_ids = {shop.id for shop in shops}
    if not shop_ids:
        flash("Activez le type Location sur votre boutique pour utiliser cette section.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    # Requête de base pour les listings (avec pagination)
    query = (
        RentalListing.query
        .options(selectinload(RentalListing.media), selectinload(RentalListing.shop))
        .filter(RentalListing.owner_id == current_user.id)
        .filter(RentalListing.shop_id.in_(shop_ids))
    )
    if shop_id and shop_id in shop_ids:
        query = query.filter(RentalListing.shop_id == shop_id)
    if status and status in ("active", "reserved", "taken", "expired"):
        query = query.filter(RentalListing.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (RentalListing.title.ilike(like))
            | (RentalListing.city.ilike(like))
            | (RentalListing.area.ilike(like))
        )

    # PAGINATION AJOUTÉE
    page = page_from_args(request.args)
    per_page = 20
    pagination = paginate_with_clamped_page(
        query.order_by(RentalListing.created_at.desc(), RentalListing.id.desc()),
        page=page, per_page=per_page, error_out=False
    )
    listings = pagination.items

    # STATS OPTIMISÉES (plus de boucles Python)
    # Total des vues
    total_views = db.session.query(func.sum(RentalListing.view_count))\
        .filter(RentalListing.owner_id == current_user.id)\
        .filter(RentalListing.shop_id.in_(shop_ids))\
        .scalar() or 0

    # Top 5 des plus vues
    top_viewed = RentalListing.query\
        .filter(RentalListing.owner_id == current_user.id)\
        .filter(RentalListing.shop_id.in_(shop_ids))\
        .order_by(RentalListing.view_count.is_(None), RentalListing.view_count.desc())\
        .limit(5)\
        .all()

    # Comptage des actives
    active_count = RentalListing.query\
        .filter(RentalListing.owner_id == current_user.id)\
        .filter(RentalListing.shop_id.in_(shop_ids))\
        .filter(RentalListing.status == "active")\
        .count()

    # Comptage des expirées
    now = datetime.utcnow()
    expired_count = RentalListing.query\
        .filter(RentalListing.owner_id == current_user.id)\
        .filter(RentalListing.shop_id.in_(shop_ids))\
        .filter(
            (RentalListing.expires_at <= now) | (RentalListing.status == "expired")
        )\
        .count()

    # Stats par boutique (déjà optimisé)
    shop_location_rows = (
        db.session.query(
            RentalListing.shop_id,
            func.count(RentalListing.id),
            func.coalesce(func.sum(RentalListing.view_count), 0),
        )
        .filter(RentalListing.owner_id == current_user.id)
        .filter(RentalListing.shop_id.in_(shop_ids))
        .group_by(RentalListing.shop_id)
        .all()
    )
    shop_stats = {
        int(shop_id): {"count": int(count or 0), "views": int(views or 0)}
        for shop_id, count, views in shop_location_rows
    }

    # Archives (inchangé)
    history_cutoff = datetime.utcnow() - timedelta(days=OWNER_LOCATION_HISTORY_DAYS)
    owner_archives_query = (
        RentalArchive.query
        .filter(RentalArchive.owner_id == current_user.id)
        .filter(RentalArchive.closed_at >= history_cutoff)
    )
    owner_history_count = owner_archives_query.count()
    latest_archive = owner_archives_query.order_by(RentalArchive.closed_at.desc()).first()
    settings = PlatformSettings.get()

    return render_template(
        "locations/owner_index.html",
        listings=listings,
        pagination=pagination,  # Ajouté pour la pagination
        shops=shops,
        status=status,
        selected_shop_id=shop_id,
        q=q,
        total_views=total_views,
        active_count=active_count,
        expired_count=expired_count,
        top_viewed=top_viewed,
        shop_stats=shop_stats,
        owner_history_count=owner_history_count,
        owner_history_days=OWNER_LOCATION_HISTORY_DAYS,
        latest_archive_at=latest_archive.closed_at if latest_archive else None,
        settings=settings,
        cents_to_dh=cents_to_dh,
        bps_to_percent=_bps_to_percent,
        commission_amount_from_owner_fee=commission_amount_from_owner_fee,
        now=datetime.utcnow(),
    )


@bp.route("/owner/locations/archives")
@login_required
def owner_locations_archives():
    guard = _owner_required()
    if guard:
        return guard
    access_guard = ensure_vendor_allows(
        current_user,
        "location",
        fallback_endpoint="vendor.manage_shop",
        strict_forbidden=True,
    )
    if access_guard:
        return access_guard

    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().lower()
    shop_id = request.args.get("shop", type=int)
    page = page_from_args(request.args)
    per_page = 20

    shops = _owner_shops(current_user.id, location_only=True)
    shop_ids = {shop.id for shop in shops}
    if not shop_ids:
        flash("Activez le type Location sur votre boutique pour utiliser cette section.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    query = (
        RentalArchive.query
        .options(selectinload(RentalArchive.shop))
        .filter(RentalArchive.owner_id == current_user.id)
        .filter(RentalArchive.shop_id.in_(shop_ids))
        .filter(RentalArchive.closed_at >= datetime.utcnow() - timedelta(days=OWNER_LOCATION_HISTORY_DAYS))
    )

    if shop_id and shop_id in shop_ids:
        query = query.filter(RentalArchive.shop_id == shop_id)
    if status in ("taken", "expired", "deleted_by_owner", "deleted_by_admin"):
        query = query.filter(RentalArchive.closed_reason == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (RentalArchive.title.ilike(like))
            | (RentalArchive.city.ilike(like))
            | (RentalArchive.area.ilike(like))
        )

    pagination = paginate_with_clamped_page(
        query.order_by(RentalArchive.closed_at.desc(), RentalArchive.id.desc()),
        page=page, per_page=per_page, error_out=False
    )
    archives = pagination.items
    settings = PlatformSettings.get()

    return render_template(
        "locations/owner_archives.html",
        archives=archives,
        pagination=pagination,
        shops=shops,
        q=q,
        status=status,
        selected_shop_id=shop_id,
        settings=settings,
        history_days=OWNER_LOCATION_HISTORY_DAYS,
        cents_to_dh=cents_to_dh,
        bps_to_percent=_bps_to_percent,
        commission_amount_from_owner_fee=commission_amount_from_owner_fee,
    )


@bp.route("/owner/location/new", methods=["GET", "POST"])
@login_required
def owner_location_new():
    return _owner_location_form()


@bp.route("/owner/location/<int:listing_id>/edit", methods=["GET", "POST"])
@login_required
def owner_location_edit(listing_id: int):
    return _owner_location_form(listing_id)


def _owner_location_form(listing_id: int | None = None):
    """One validation and persistence path for the modal and the ordinary form."""
    editing = listing_id is not None
    modal_request = _is_location_form_modal_request()
    if not modal_request:
        guard = _owner_required()
        if guard:
            return guard
        access_guard = ensure_vendor_allows(
            current_user, "location", fallback_endpoint="vendor.manage_shop", strict_forbidden=True,
        )
        if access_guard:
            return access_guard

    owner_id = current_user.id
    shops = _owner_shops(owner_id, location_only=True)
    if not shops:
        if modal_request:
            return _location_form_json({
                "success": False,
                "message": "Votre boutique n'est pas autorisée à publier des locations.",
                "redirect_url": url_for("vendor.manage_shop"),
            }, 403)
        flash("Aucune boutique autorisée pour Location.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    listing = None
    if editing:
        listing = (RentalListing.query.options(selectinload(RentalListing.media), selectinload(RentalListing.shop))
                   .filter_by(id=listing_id, owner_id=owner_id).first())
        if not listing:
            if modal_request:
                return _location_form_json({"success": False, "message": "Cette annonce est introuvable."}, 404)
            abort(404)
        if listing.shop_id not in {shop.id for shop in shops}:
            if modal_request:
                return _location_form_json({"success": False, "message": "Cette boutique n'autorise pas les locations."}, 403)
            abort(403)

    settings = PlatformSettings.get()
    media = list(listing.media) if listing else []
    images = [item for item in media if item.kind == "image"]
    videos = [item for item in media if item.kind == "video"]
    existing_images = [{"id": item.id, "url": url_for("static", filename=item.file_path)} for item in images]
    existing_video = {"id": videos[0].id, "url": url_for("static", filename=videos[0].file_path)} if videos else None
    values = {
        "title": listing.title if listing else "", "description": listing.description if listing else "",
        "listing_type": listing.listing_type if listing else "monthly",
        "property_type": listing.property_type if listing else "apartment",
        "shop_id": str(listing.shop_id) if listing else str(shops[0].id) if len(shops) == 1 else "",
        "city": listing.city if listing else "", "area": (listing.area or "") if listing else "",
        "rent": f"{listing.rent_cents / 100:.2f}" if listing else "",
        "deposit_required": "1" if listing and listing.deposit_required else "0",
        "deposit": f"{listing.deposit_cents / 100:.2f}" if listing and listing.deposit_cents is not None else "",
        "owner_fee": f"{listing.owner_fee_cents / 100:.2f}" if listing and listing.owner_fee_cents is not None else "",
        "owner_fee_text": (listing.owner_fee_text or "") if listing else "",
    }
    if request.method == "POST":
        values.update({key: request.form.get(key, "") for key in values})
    context = dict(
        listing=listing,
        form_values=values,
        form_errors={},
        form_error="",
        existing_images=existing_images,
        existing_video=existing_video,
        deleted_image_ids=set(request.form.getlist("delete_images")) if request.method == "POST" else set(),
        delete_video=request.form.get("delete_video") == "1" if request.method == "POST" else False,
        shops=shops,
        settings=settings,
        max_images=MAX_IMAGE_COUNT,
        max_image_mb=int(MAX_IMAGE_BYTES / 1024 / 1024),
        max_video_mb=int(MAX_VIDEO_BYTES / 1024 / 1024),
        monthly_duration_days=rental_duration_days_for_type("monthly", settings=settings),
        daily_duration_days=rental_duration_days_for_type("daily", settings=settings),
        cents_to_dh=cents_to_dh,
        format_dt=_format_dt,
        admin_rental_rate_bps=int(settings.rental_success_commission_bps or 0),
        bps_to_percent=_bps_to_percent,
        commission_amount_from_owner_fee=commission_amount_from_owner_fee,
    )

    def reject(message: str, *, field: str | None = None, status: int = 422):
        if modal_request:
            return _location_form_json({
                "success": False, "message": message, "errors": {field: message} if field else {},
            }, status)
        flash(message, "warning" if status < 500 else "danger")
        context["form_errors"] = {field: message} if field else {}
        context["form_error"] = message
        return render_template("locations/owner_form.html", **context), status

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        listing_type = (request.form.get("listing_type") or "").strip().lower()
        property_type = (request.form.get("property_type") or "").strip().lower()
        city = (request.form.get("city") or "").strip()
        area = (request.form.get("area") or "").strip()
        shop_id = request.form.get("shop_id", type=int)
        owner_fee_text = (request.form.get("owner_fee_text") or "").strip()

        if not 6 <= len(title) <= 180:
            return reject("Saisissez un titre entre 6 et 180 caractères.", field="title")
        if listing_type not in ("monthly", "daily"):
            return reject("Choisissez une location au mois ou à la nuit.", field="listing_type")
        if property_type not in ("room", "apartment", "studio", "store"):
            return reject("Choisissez un type de bien valide.", field="property_type")
        if not city or len(city) > 120:
            return reject("Saisissez une ville entre 1 et 120 caractères.", field="city")
        if len(area) > 120:
            return reject("Le quartier doit contenir au maximum 120 caractères.", field="area")
        if not shop_id or shop_id not in {shop.id for shop in shops}:
            return reject("Choisissez une boutique de location qui vous appartient.", field="shop_id")
        if len(owner_fee_text) > 255:
            return reject("Le texte des frais doit contenir au maximum 255 caractères.", field="owner_fee_text")

        deposit_value = (request.form.get("deposit_required") or "0").strip()
        if deposit_value not in ("0", "1"):
            return reject("Indiquez si une caution est demandée.", field="deposit_required")
        deposit_required = deposit_value == "1"
        money_values = {}
        for field, required in (("rent", True), ("owner_fee", False), ("deposit", deposit_required)):
            if field == "deposit" and not deposit_required:
                money_values[field] = None
                continue
            try:
                money_values[field] = _location_form_cents(request.form.get(field), required=required)
            except ValueError as exc:
                return reject(str(exc), field=field)

        image_files = [f for f in request.files.getlist("images") if f and (f.filename or "").strip()]
        video_files = [f for f in request.files.getlist("video") if f and (f.filename or "").strip()]
        removed_ids = {int(value) for value in request.form.getlist("delete_images") + request.form.getlist("remove_media_ids") if str(value).isascii() and str(value).isdigit()}
        if request.form.get("delete_video") == "1":
            removed_ids.update(item.id for item in videos)
        removed_media = [item for item in media if item.id in removed_ids]
        removed_files = [item.file_path for item in removed_media]
        retained_images = [item for item in images if item.id not in removed_ids]
        retained_videos = [item for item in videos if item.id not in removed_ids]
        if len(image_files) + len(retained_images) > MAX_IMAGE_COUNT:
            return reject("Conservez au maximum 4 photos. Retirez une photo pour en ajouter une autre.", field="images")
        if len(video_files) + len(retained_videos) > 1:
            return reject("Conservez une seule vidéo. Retirez la vidéo actuelle pour la remplacer.", field="video")
        for file_obj in image_files:
            if "." not in file_obj.filename or file_obj.filename.rsplit(".", 1)[-1].lower() not in IMAGE_EXTENSIONS:
                return reject("Choisissez des photos au format JPG, PNG ou WebP.", field="images")
            try:
                if _location_upload_size(file_obj) > MAX_IMAGE_BYTES:
                    return reject("Chaque photo doit rester inférieure à 12 Mo.", field="images")
            except ValueError as exc:
                return reject(str(exc), field="images")
        if video_files:
            video_name = video_files[0].filename
            if "." not in video_name or video_name.rsplit(".", 1)[-1].lower() not in VIDEO_EXTENSIONS:
                return reject("Choisissez une vidéo dans un format pris en charge, comme MP4, MOV ou WebM.", field="video")
            try:
                if _location_upload_size(video_files[0]) > MAX_VIDEO_BYTES:
                    return reject("La vidéo doit rester inférieure à 30 Mo.", field="video")
            except ValueError as exc:
                return reject(str(exc), field="video")

        saved_files: list[str] = []
        media_field = "images"
        try:
            new_images = []
            for file_obj in image_files:
                image_rel = save_rental_image(file_obj)
                saved_files.append(image_rel)
                new_images.append(image_rel)
            video_rel = None
            if video_files:
                media_field = "video"
                video_rel = save_rental_video(video_files[0], strict=True)
                saved_files.append(video_rel)

            media_field = None
            previous_type = listing.listing_type if editing else None
            listing_slug = _build_listing_slug(title, exclude_id=listing.id if editing else None)
            if not editing:
                listing = RentalListing(owner_id=owner_id, currency="MAD", status="active", is_active=True, created_at=datetime.utcnow())
            # Do not renew an existing announcement merely because it was edited.
            if not editing or listing_type != previous_type:
                listing.expires_at = (listing.created_at or datetime.utcnow()) + timedelta(days=rental_duration_days_for_type(listing_type, settings=settings))
            listing.shop_id = shop_id
            listing.title = title
            listing.slug = listing_slug
            listing.description = description
            listing.listing_type = listing_type
            listing.property_type = property_type
            listing.city = city
            listing.area = area or None
            listing.rent_cents = money_values["rent"] or 0
            listing.deposit_required = deposit_required
            listing.deposit_cents = money_values["deposit"]
            listing.owner_fee_cents = money_values["owner_fee"]
            listing.owner_fee_text = owner_fee_text or None
            listing.owner_fee_negotiable = False
            listing.platform_commission_mode = "success_commission"
            listing.platform_commission_rate_bps = int(settings.rental_success_commission_bps or 0)
            listing.platform_commission_fixed_cents = 0
            if not editing:
                db.session.add(listing)
            for item in removed_media:
                db.session.delete(item)
            db.session.flush()
            for image_rel in new_images:
                db.session.add(RentalMedia(listing_id=listing.id, kind="image", file_path=image_rel))
            if video_rel:
                db.session.add(RentalMedia(listing_id=listing.id, kind="video", file_path=video_rel))
            listing_payload = {
                "id": listing.id, "title": listing.title, "slug": listing.slug,
                "listing_type": listing.listing_type, "property_type": listing.property_type,
                "city": listing.city, "area": listing.area or "", "rent_cents": listing.rent_cents,
                "status": listing.status, "shop_id": listing.shop_id,
                "expires_at": listing.expires_at.isoformat() + "Z",
            }
            db.session.commit()
        except ValueError as exc:
            safe_session_rollback()
            _cleanup_location_files(saved_files)
            current_app.logger.warning("Validation error saving listing: %s", exc)
            return reject(str(exc) if media_field else "Les informations de l'annonce sont invalides.", field=media_field)
        except Exception:
            safe_session_rollback()
            _cleanup_location_files(saved_files)
            current_app.logger.exception("Unexpected error saving listing owner_id=%s", owner_id)
            return reject("L'enregistrement a échoué. Votre saisie est conservée, réessayez dans quelques instants.", status=500)

        # Existing files remain usable if validation, uploads or the transaction fail.
        _cleanup_location_files(removed_files)
        try:
            log_access(
                "update_rental_listing" if editing else "create_rental_listing", "rental_listing", listing_payload["id"], success=True,
                changes={"shop_id": listing_payload["shop_id"], "listing_type": listing_payload["listing_type"]},
            )
        except Exception:
            current_app.logger.exception("rental.form.post_commit_failed listing_id=%s", listing_payload["id"])
        message = "Annonce de location mise à jour." if editing else "Annonce de location créée."
        if modal_request:
            return _location_form_json({"success": True, "listing": listing_payload, "message": message, "notices": []}, 200 if editing else 201)
        flash(message, "success")
        return redirect(url_for("rentals.owner_locations"))

    if modal_request:
        return _location_form_json({"success": True, "html": render_template("locations/partials/_owner_create_modal.html", **context)})
    if request.args.get("standalone") != "1":
        target = url_for("rentals.owner_locations", edit_location=listing.id) if editing else url_for("rentals.owner_locations", new="location")
        response = redirect(target, code=303)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Vary"] = "Cookie, X-Vendor-Modal"
        return response
    return render_template("locations/owner_form.html", **context)


@bp.route("/owner/location/<int:listing_id>/close", methods=["POST"])
@login_required
def owner_location_close(listing_id: int):
    guard = _owner_required()
    if guard:
        return guard
    access_guard = ensure_vendor_allows(
        current_user,
        "location",
        fallback_endpoint="vendor.manage_shop",
        strict_forbidden=True,
    )
    if access_guard:
        return access_guard

    listing = RentalListing.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    listing_guard = ensure_shop_allows(
        listing.shop,
        "location",
        fallback_endpoint="vendor.manage_shop",
    )
    if listing_guard:
        return listing_guard
    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    target_status = (request.form.get("status") or "").strip().lower()
    if target_status not in ("reserved", "taken"):
        target_status = "taken"

    if target_status == "reserved":
        listing.status = "reserved"
        listing.updated_at = datetime.utcnow()
        db.session.commit()
        log_access(
            "reserve_rental_listing",
            "rental_listing",
            listing.id,
            success=True,
            changes={"status": "reserved"},
        )
        flash("Annonce marquée comme réservée.", "success")
        return _redirect_internal_next(next_url, "rentals.owner_locations")

    settings = PlatformSettings.get()
    listing.platform_commission_mode = "success_commission"
    listing.platform_commission_rate_bps = int(settings.rental_success_commission_bps or 0)
    listing.platform_commission_fixed_cents = 0
    listing.updated_at = datetime.utcnow()

    result = archive_and_remove_listing(listing, closed_reason="taken")
    db.session.commit()
    log_access(
        "close_rental_listing_taken",
        "rental_listing",
        listing_id,
        success=True,
        changes={
            "removed_media_files": result.get("removed_files", 0),
            "platform_commission_rate_bps": listing.platform_commission_rate_bps,
            "platform_commission_amount_cents": commission_amount_from_owner_fee(
                listing.owner_fee_cents, listing.platform_commission_rate_bps
            ),
        },
    )
    flash("Annonce clôturée et archivée.", "success")
    return _redirect_internal_next(next_url, "rentals.owner_locations")


@bp.route("/owner/location/<int:listing_id>/delete", methods=["POST"])
@login_required
def owner_location_delete(listing_id: int):
    guard = _owner_required()
    if guard:
        return guard
    access_guard = ensure_vendor_allows(
        current_user,
        "location",
        fallback_endpoint="vendor.manage_shop",
        strict_forbidden=True,
    )
    if access_guard:
        return access_guard

    listing = RentalListing.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    listing_guard = ensure_shop_allows(
        listing.shop,
        "location",
        fallback_endpoint="vendor.manage_shop",
    )
    if listing_guard:
        return listing_guard
    next_url = (request.form.get("next") or request.args.get("next") or "").strip()
    reason = "deleted_by_owner"
    if listing.expires_at and listing.expires_at <= datetime.utcnow():
        reason = "expired"
    result = archive_and_remove_listing(listing, closed_reason=reason)
    db.session.commit()
    log_access(
        "delete_rental_listing_owner",
        "rental_listing",
        listing_id,
        success=True,
        changes={"reason": reason, "removed_media_files": result.get("removed_files", 0)},
    )
    flash("Annonce supprimée et archivée.", "success")
    return _redirect_internal_next(next_url, "rentals.owner_locations")


@bp.route("/owner/location/<int:listing_id>/media/<int:media_id>/delete", methods=["POST"])
@login_required
def owner_location_media_delete(listing_id: int, media_id: int):
    guard = _owner_required()
    if guard:
        return guard
    access_guard = ensure_vendor_allows(
        current_user,
        "location",
        fallback_endpoint="vendor.manage_shop",
        strict_forbidden=True,
    )
    if access_guard:
        return access_guard

    listing = RentalListing.query.filter_by(id=listing_id, owner_id=current_user.id).first_or_404()
    listing_guard = ensure_shop_allows(
        listing.shop,
        "location",
        fallback_endpoint="vendor.manage_shop",
    )
    if listing_guard:
        return listing_guard
    media = RentalMedia.query.filter_by(id=media_id, listing_id=listing.id).first_or_404()

    delete_static_file(media.file_path)
    db.session.delete(media)
    db.session.commit()

    log_access(
        "delete_rental_media_owner",
        "rental_media",
        media_id,
        success=True,
        changes={"listing_id": listing.id, "kind": media.kind},
    )
    flash("Média supprimé.", "success")
    return redirect(url_for("rentals.owner_location_edit", listing_id=listing.id))


@bp.route("/admin/locations")
@login_required
def admin_locations():
    guard = _admin_required()
    if guard:
        return guard

    section = _normalize_admin_locations_section(request.args.get("section")) if _is_ajax_request() else ""
    include_listings = section in {"", "listings", "both"}
    include_archives = section in {"", "archives", "both"}
    include_stats = section == "" or request.args.get("stats") == "1"
    partial_request = bool(section)

    q        = (request.args.get("q") or "").strip()
    status   = (request.args.get("status") or "").strip().lower()
    owner_id = request.args.get("owner_id", type=int)
    date_filter = resolve_date_filter(request.args, default="month")
    page     = page_from_args(request.args, "page")
    a_page   = page_from_args(request.args, "apage")
    PER      = 25
    A_PER    = 20

    #  Listings 
    lq = (
        RentalListing.query
        .options(
            selectinload(RentalListing.shop),
            selectinload(RentalListing.owner),
            selectinload(RentalListing.media),
        )
    )
    if q:
        like = f"%{q}%"
        lq = lq.filter(
            RentalListing.title.ilike(like)
            | RentalListing.city.ilike(like)
            | RentalListing.area.ilike(like)
        )
    if status in ("active", "reserved", "taken", "expired"):
        lq = lq.filter(RentalListing.status == status)
    if owner_id:
        lq = lq.filter(RentalListing.owner_id == owner_id)
    lq = lq.filter(
        RentalListing.created_at >= date_filter.start_at,
        RentalListing.created_at < date_filter.end_at,
    )

    listings_pg = None
    if include_listings:
        listings_pg = paginate_with_clamped_page(
            lq.order_by(RentalListing.created_at.desc(), RentalListing.id.desc()),
            page=page, per_page=PER, error_out=False
        )

    #  Archives 
    archives_query = (
        RentalArchive.query
        .options(
            selectinload(RentalArchive.shop),
            selectinload(RentalArchive.owner),
        )
    )
    archives_query = archives_query.filter(
        RentalArchive.closed_at >= date_filter.start_at,
        RentalArchive.closed_at < date_filter.end_at,
    )
    archives_pg = None
    if include_archives:
        archives_pg = paginate_with_clamped_page(
            archives_query.order_by(RentalArchive.closed_at.desc(), RentalArchive.id.desc()),
            page=a_page, per_page=A_PER, error_out=False
        )

    owners = []
    if not partial_request:
        owners = (
            User.query
            .options(load_only(User.id, User.username))
            .filter_by(role="vendor")
            .order_by(User.username.asc())
            .all()
        )
    archives_count = 0
    active_count = 0
    expired_pending = 0
    if include_stats:
        archives_count = int(archives_pg.total) if archives_pg is not None else archives_query.order_by(None).count()
        active_count = int(listings_pg.total) if listings_pg is not None else lq.order_by(None).count()
        expired_pending = lq.filter(RentalListing.expires_at <= datetime.utcnow()).order_by(None).count()
    settings = PlatformSettings.get() if (include_listings or not partial_request) else None
    duration_settings_history = []
    if not partial_request:
        try:
            duration_settings_history = (
                AuditLog.query
                .options(selectinload(AuditLog.user))
                .filter(AuditLog.action == "update_rental_duration_settings")
                .filter(AuditLog.entity_type == "platform_settings")
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(10)
                .all()
            )
        except Exception:
            db.session.rollback()

    context = dict(
        listings=listings_pg.items if listings_pg is not None else [],
        listings_pg=listings_pg,
        archives=archives_pg.items if archives_pg is not None else [],
        archives_pg=archives_pg,
        owners=owners,
        q=q,
        status=status,
        owner_id=owner_id,
        range_filter=date_filter.range_filter,
        date_range_label=date_filter.label,
        date_from=date_filter.date_from,
        date_to=date_filter.date_to,
        a_page=a_page,
        archives_count=archives_count,
        active_count=active_count,
        expired_pending=expired_pending,
        settings=settings,
        duration_settings_history=duration_settings_history,
        cents_to_dh=cents_to_dh,
        format_dt=_format_dt,
        bps_to_percent=_bps_to_percent,
        commission_amount_from_owner_fee=commission_amount_from_owner_fee,
    )

    if partial_request:
        return render_template(
            "admin/partials/_locations_fragment.html",
            include_listings=include_listings,
            include_archives=include_archives,
            include_stats=include_stats,
            **context,
        )

    return render_template("admin/locations.html", **context)


@bp.route("/admin/locations/duration-settings", methods=["POST"])
@login_required
def admin_locations_duration_settings():
    guard = _admin_required()
    if guard:
        return guard

    settings = PlatformSettings.get()
    previous_monthly_days = int(getattr(settings, "rental_monthly_duration_days", 14) or 14)
    previous_daily_days = int(getattr(settings, "rental_daily_duration_days", 14) or 14)

    try:
        monthly_days = _coerce_duration_days(
            request.form.get("rental_monthly_duration_days"),
            fallback=previous_monthly_days,
        )
        daily_days = _coerce_duration_days(
            request.form.get("rental_daily_duration_days"),
            fallback=previous_daily_days,
        )
    except Exception:
        flash("Durees invalides. Veuillez saisir des nombres entiers.", "warning")
        return redirect(request.referrer or url_for("rentals.admin_locations"))

    if monthly_days == previous_monthly_days and daily_days == previous_daily_days:
        flash("Aucun changement detecte sur les durees.", "info")
        return redirect(request.referrer or url_for("rentals.admin_locations"))

    settings.rental_monthly_duration_days = monthly_days
    settings.rental_daily_duration_days = daily_days
    db.session.commit()

    log_access(
        "update_rental_duration_settings",
        "platform_settings",
        settings.id or 0,
        success=True,
        changes={
            "rental_monthly_duration_days_before": previous_monthly_days,
            "rental_monthly_duration_days_after": monthly_days,
            "rental_daily_duration_days_before": previous_daily_days,
            "rental_daily_duration_days_after": daily_days,
        },
    )
    flash("Durees de disparition location mises a jour.", "success")
    return redirect(request.referrer or url_for("rentals.admin_locations"))


@bp.route("/admin/location/<int:listing_id>/delete", methods=["POST"])
@login_required
def admin_location_delete(listing_id: int):
    guard = _admin_required()
    if guard:
        return guard

    listing = RentalListing.query.get_or_404(listing_id)
    result = archive_and_remove_listing(listing, closed_reason="deleted_by_admin")
    db.session.commit()
    log_access(
        "delete_rental_listing_admin",
        "rental_listing",
        listing_id,
        success=True,
        changes={"removed_media_files": result.get("removed_files", 0)},
    )
    flash("Annonce supprimée par admin et archivée.", "success")
    return redirect(request.referrer or url_for("rentals.admin_locations"))
