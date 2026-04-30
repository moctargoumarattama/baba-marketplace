from datetime import datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from slugify import slugify
from sqlalchemy import func
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy.exc import SQLAlchemyError
from ..extensions import db
from ..models.platform_settings import PlatformSettings
from ..models.rental import RENTAL_LISTING_DURATION_DAYS, RentalArchive, RentalListing, RentalMedia
from ..models.shop import Shop
from ..models.user import User
from ..services.audit import log_access
from ..services.marketplace_feed import CURATED_PAGE_LIMIT, build_location_feed
from ..services.pagination import SimplePagination, page_from_args
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
    archive_and_remove_listing,
    cents_to_dh,
    commission_amount_from_owner_fee,
    delete_static_file,
    rental_existing_video_poster_rel_path,
    save_rental_image,
    save_rental_video,
)


bp = Blueprint("rentals", __name__)
OWNER_LOCATION_HISTORY_DAYS = 7


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

    page_name = (request.args.get("page") or "Page owner location").strip()[:120]
    page_url = (request.args.get("page_url") or "").strip()[:400]
    source = (request.args.get("source") or "").strip()[:160]
    item_name = (request.args.get("item") or "").strip()[:160]
    back_url = safe_support_back_target(request.args.get("back"), url_for("rentals.owner_locations"))
    shop = Shop.query.filter_by(vendor_id=current_user.id).first()

    lines = [
        "Bonjour, je signale un probleme sur mon espace location.",
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
        support_scope="Support location",
        support_title="Signaler un probleme location",
        support_copy="Votre message est pret avec la page, l'annonce et votre compte owner.",
        back_url=back_url,
        back_label="Retour a la page",
    )


def _admin_required():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if getattr(current_user, "role", None) not in {"admin", "manager"}:
        flash("Accès réservé aux administrateurs.", "warning")
        return redirect(url_for("shop.home"))
    return None


def _owner_shops(owner_id: int, location_only: bool = False):
    query = Shop.query.filter_by(vendor_id=owner_id)
    if location_only:
        query = query.filter(Shop.sql_allows_clause("location"))
    return query.order_by(Shop.name.asc()).all()


def _media_name_sample(names: list[str], limit: int = 2) -> str:
    cleaned = [str(name or "").strip() for name in names if str(name or "").strip()]
    if not cleaned:
        return ""
    sample = cleaned[:limit]
    suffix = ""
    if len(cleaned) > limit:
        suffix = f" +{len(cleaned) - limit}"
    return ", ".join(sample) + suffix


def _save_uploaded_rental_images(
    files,
    *,
    remaining_slots: int,
    saved_files: list[str],
):
    saved_rel_paths: list[str] = []
    skipped_invalid: list[str] = []
    skipped_overflow: list[str] = []
    slots_left = max(0, int(remaining_slots))

    for file_obj in files or []:
        if not file_obj or not (getattr(file_obj, "filename", "") or "").strip():
            continue
        original_name = str(getattr(file_obj, "filename", "") or "").strip()

        if len(saved_rel_paths) >= slots_left:
            skipped_overflow.append(original_name)
            continue

        try:
            image_rel = save_rental_image(file_obj)
            saved_rel_paths.append(image_rel)
            saved_files.append(image_rel)
        except ValueError as exc:
            current_app.logger.warning(
                "rental.image_rejected owner_id=%s filename=%s reason=%s",
                getattr(current_user, "id", None),
                original_name,
                exc,
            )
            skipped_invalid.append(original_name)

    return saved_rel_paths, skipped_invalid, skipped_overflow


def _save_uploaded_rental_video(
    file_obj,
    *,
    has_existing_video: bool,
    saved_files: list[str],
):
    if not file_obj or not (getattr(file_obj, "filename", "") or "").strip():
        return None, None

    original_name = str(getattr(file_obj, "filename", "") or "").strip()
    if has_existing_video:
        return None, f"video ignoree ({original_name}) : supprimez la video actuelle avant d'en ajouter une nouvelle"

    try:
        video_rel = save_rental_video(file_obj)
        saved_files.append(video_rel)
        return video_rel, None
    except ValueError as exc:
        current_app.logger.warning(
            "rental.video_rejected owner_id=%s filename=%s reason=%s",
            getattr(current_user, "id", None),
            original_name,
            exc,
        )
        return None, f"video ignoree ({original_name}) : {exc}"


def _flash_rental_media_notice(
    *,
    skipped_invalid_images: list[str],
    skipped_overflow_images: list[str],
    video_notice: str | None,
):
    notes: list[str] = []
    if skipped_invalid_images:
        sample = _media_name_sample(skipped_invalid_images)
        detail = f" ({sample})" if sample else ""
        notes.append(
            f"{len(skipped_invalid_images)} photo(s) rejetee(s) car invalides, trop lourdes ou illisibles{detail}"
        )
    if skipped_overflow_images:
        sample = _media_name_sample(skipped_overflow_images)
        detail = f" ({sample})" if sample else ""
        notes.append(
            f"{len(skipped_overflow_images)} photo(s) ignoree(s) car la limite est de {MAX_IMAGE_COUNT}{detail}"
        )
    if video_notice:
        notes.append(video_notice)
    if notes:
        flash("Medias partiellement acceptes : " + " ; ".join(notes) + ".", "warning")


def _listing_owner_view(listing: RentalListing):
    media = listing.media or []
    images = [m for m in media if m.kind == "image"]
    videos = [m for m in media if m.kind == "video"]
    return {
        "listing": listing,
        "images": images,
        "videos": videos,
    }


@bp.route("/locations")
def locations_home():
    q = (request.args.get("q") or "").strip()
    listing_type = (request.args.get("type") or "").strip().lower()
    property_type = (request.args.get("property_type") or "").strip().lower()
    city_area = (request.args.get("city") or "").strip()
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
        flash("Filtre prix invalide.", "warning")

    if q:
        like = f"%{q}%"
        query = query.filter(
            (RentalListing.title.ilike(like))
            | (RentalListing.description.ilike(like))
            | (RentalListing.city.ilike(like))
            | (RentalListing.area.ilike(like))
        )
    if listing_type:
        query = query.filter(RentalListing.listing_type == listing_type)
    if property_type:
        query = query.filter(RentalListing.property_type == property_type)
    if city_area:
        like_city = f"%{city_area}%"
        query = query.filter((RentalListing.city.ilike(like_city)) | (RentalListing.area.ilike(like_city)))

    per_page = 12
    if page <= CURATED_PAGE_LIMIT:
        payload = build_location_feed(
            page=page,
            per_page=per_page,
            search_q=q,
            listing_type=listing_type,
            property_type=property_type,
            city_area=city_area,
            min_price=min_price_value,
            max_price=max_price_value,
        )
        listings = payload.get("items", [])
        total = payload.get("total", 0)
        pagination = SimplePagination(page, payload.get("per_page", per_page), total)
    else:
        pagination = query.order_by(RentalListing.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        listings = pagination.items
    has_active_filters = bool(q or listing_type or property_type or city_area or price_min or price_max)

    template_name = "partials/_locations_listing.html" if _is_ajax_request() else "locations/index.html"
    return render_template(
        template_name,
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
        wa_number = _support_whatsapp_number()
        wa_url = f"https://wa.me/{wa_number}?text={quote(chr(10).join(lines))}"
        return render_template(
            "support/open_whatsapp.html",
            wa_url=wa_url,
            support_scope="Visite location",
            support_title="Demande de visite prete",
            support_copy="Votre message WhatsApp est pret avec l'annonce et vos coordonnees.",
            support_hint="Le proprietaire recevra aussi le lien de l'annonce.",
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
    pagination = query.order_by(RentalListing.created_at.desc()).paginate(
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

    pagination = query.order_by(RentalArchive.closed_at.desc()).paginate(
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

    shops = _owner_shops(current_user.id, location_only=True)
    if not shops:
        flash("Aucune boutique autorisée pour Location.", "warning")
        return redirect(url_for("vendor.manage_shop"))

    settings = PlatformSettings.get()

    if request.method == "POST":
        saved_files: list[str] = []
        try:
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            listing_type = (request.form.get("listing_type") or "").strip().lower()
            property_type = (request.form.get("property_type") or "").strip().lower()
            city = (request.form.get("city") or "").strip()
            area = (request.form.get("area") or "").strip()
            shop_id = request.form.get("shop_id", type=int)

            if not title or len(title) < 6:
                raise ValueError("Titre trop court.")
            if listing_type not in ("monthly", "daily"):
                raise ValueError("Type d'annonce invalide.")
            if property_type not in ("room", "apartment", "studio", "store"):
                raise ValueError("Type de bien invalide.")
            if not city:
                raise ValueError("Ville obligatoire.")

            owner_shop_ids = {s.id for s in shops}
            if not shop_id or shop_id not in owner_shop_ids:
                raise ValueError("Boutique invalide.")

            rent_cents = _to_cents(request.form.get("rent"), "Loyer")

            deposit_required = (request.form.get("deposit_required") or "0") == "1"
            deposit_cents = None
            if deposit_required:
                deposit_cents = _to_cents(request.form.get("deposit"), "Caution")

            owner_fee_cents = _to_cents(request.form.get("owner_fee"), "Frais propriétaire", required=False)
            owner_fee_text = (request.form.get("owner_fee_text") or "").strip()
            if len(owner_fee_text) > 255:
                raise ValueError("Texte frais propriétaire trop long (max 255 caractères).")

            created_at = datetime.utcnow()
            listing = RentalListing(
                owner_id=current_user.id,
                shop_id=shop_id,
                title=title,
                slug=_build_listing_slug(title),
                description=description,
                listing_type=listing_type,
                property_type=property_type,
                city=city,
                area=area or None,
                rent_cents=rent_cents or 0,
                currency="MAD",
                deposit_required=deposit_required,
                deposit_cents=deposit_cents,
                owner_fee_cents=owner_fee_cents,
                owner_fee_text=owner_fee_text or None,
                owner_fee_negotiable=False,
                platform_commission_mode="success_commission",
                platform_commission_rate_bps=int(settings.rental_success_commission_bps or 0),
                platform_commission_fixed_cents=0,
                status="active",
                is_active=True,
                created_at=created_at,
                expires_at=created_at + timedelta(days=RENTAL_LISTING_DURATION_DAYS),
            )
            db.session.add(listing)
            db.session.flush()

            image_files = [f for f in request.files.getlist("images") if f and f.filename]
            new_images, skipped_invalid_images, skipped_overflow_images = _save_uploaded_rental_images(
                image_files,
                remaining_slots=MAX_IMAGE_COUNT,
                saved_files=saved_files,
            )
            for image_rel in new_images:
                db.session.add(RentalMedia(listing_id=listing.id, kind="image", file_path=image_rel))

            video_file = request.files.get("video")
            video_rel, video_notice = _save_uploaded_rental_video(
                video_file,
                has_existing_video=False,
                saved_files=saved_files,
            )
            if video_rel:
                db.session.add(RentalMedia(listing_id=listing.id, kind="video", file_path=video_rel))

            db.session.commit()
            log_access(
                "create_rental_listing",
                "rental_listing",
                listing.id,
                success=True,
                changes={"shop_id": listing.shop_id, "listing_type": listing.listing_type},
            )
            flash("Annonce location créée.", "success")
            _flash_rental_media_notice(
                skipped_invalid_images=skipped_invalid_images,
                skipped_overflow_images=skipped_overflow_images,
                video_notice=video_notice,
            )
            return redirect(url_for("rentals.owner_locations"))
        except ValueError as exc:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            current_app.logger.warning(f"Validation error creating listing: {exc}")
            flash(str(exc), "warning")
        except SQLAlchemyError as e:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            current_app.logger.error(f"Database error creating listing: {e}")
            flash("Erreur base de données lors de la création.", "danger")
        except Exception as e:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            current_app.logger.exception(f"Unexpected error creating listing: {e}")
            flash("Erreur inattendue lors de la création.", "danger")

    return render_template(
        "locations/owner_form.html",
        listing=None,
        shops=shops,
        max_images=MAX_IMAGE_COUNT,
        max_image_mb=int(MAX_IMAGE_BYTES / 1024 / 1024),
        max_video_mb=int(MAX_VIDEO_BYTES / 1024 / 1024),
        cents_to_dh=cents_to_dh,
        owner_view=None,
        format_dt=_format_dt,
        admin_rental_rate_bps=int(settings.rental_success_commission_bps or 0),
        bps_to_percent=_bps_to_percent,
        commission_amount_from_owner_fee=commission_amount_from_owner_fee,
    )


@bp.route("/owner/location/<int:listing_id>/edit", methods=["GET", "POST"])
@login_required
def owner_location_edit(listing_id: int):
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

    listing = (
        RentalListing.query
        .options(selectinload(RentalListing.media), selectinload(RentalListing.shop))
        .filter_by(id=listing_id, owner_id=current_user.id)
        .first_or_404()
    )
    shops = _owner_shops(current_user.id, location_only=True)
    owner_shop_ids = {s.id for s in shops}
    settings = PlatformSettings.get()
    listing_guard = ensure_shop_allows(
        listing.shop,
        "location",
        fallback_endpoint="vendor.manage_shop",
    )
    if listing_guard:
        return listing_guard

    if request.method == "POST":
        saved_files: list[str] = []
        try:
            listing.title = (request.form.get("title") or "").strip()
            listing.description = (request.form.get("description") or "").strip()
            listing.listing_type = (request.form.get("listing_type") or "").strip().lower()
            listing.property_type = (request.form.get("property_type") or "").strip().lower()
            listing.city = (request.form.get("city") or "").strip()
            listing.area = (request.form.get("area") or "").strip() or None
            listing.shop_id = request.form.get("shop_id", type=int)

            if not listing.title or len(listing.title) < 6:
                raise ValueError("Titre trop court.")
            if listing.listing_type not in ("monthly", "daily"):
                raise ValueError("Type d'annonce invalide.")
            if listing.property_type not in ("room", "apartment", "studio", "store"):
                raise ValueError("Type de bien invalide.")
            if not listing.shop_id or listing.shop_id not in owner_shop_ids:
                raise ValueError("Boutique invalide.")

            listing.slug = _build_listing_slug(listing.title, exclude_id=listing.id)
            listing.rent_cents = _to_cents(request.form.get("rent"), "Loyer") or 0

            listing.deposit_required = (request.form.get("deposit_required") or "0") == "1"
            if listing.deposit_required:
                listing.deposit_cents = _to_cents(request.form.get("deposit"), "Caution")
            else:
                listing.deposit_cents = None

            listing.owner_fee_cents = _to_cents(request.form.get("owner_fee"), "Frais propriétaire", required=False)
            owner_fee_text = (request.form.get("owner_fee_text") or "").strip()
            if len(owner_fee_text) > 255:
                raise ValueError("Texte frais propriétaire trop long (max 255 caractères).")
            listing.owner_fee_text = owner_fee_text or None
            listing.owner_fee_negotiable = False

            # Commission interne Baba Market: uniquement admin
            listing.platform_commission_mode = "success_commission"
            listing.platform_commission_rate_bps = int(settings.rental_success_commission_bps or 0)
            listing.platform_commission_fixed_cents = 0

            remove_media_ids = {
                int(mid)
                for mid in request.form.getlist("remove_media_ids")
                if str(mid).isdigit()
            }
            existing_images = [m for m in listing.media if m.kind == "image" and m.id not in remove_media_ids]
            existing_videos = [m for m in listing.media if m.kind == "video" and m.id not in remove_media_ids]

            image_files = [f for f in request.files.getlist("images") if f and f.filename]
            remaining_slots = max(0, MAX_IMAGE_COUNT - len(existing_images))
            new_video = request.files.get("video")

            for media_row in list(listing.media):
                if media_row.id in remove_media_ids:
                    delete_static_file(media_row.file_path)
                    db.session.delete(media_row)

            new_images, skipped_invalid_images, skipped_overflow_images = _save_uploaded_rental_images(
                image_files,
                remaining_slots=remaining_slots,
                saved_files=saved_files,
            )
            for image_rel in new_images:
                db.session.add(RentalMedia(listing_id=listing.id, kind="image", file_path=image_rel))

            video_rel, video_notice = _save_uploaded_rental_video(
                new_video,
                has_existing_video=bool(existing_videos),
                saved_files=saved_files,
            )
            if video_rel:
                db.session.add(RentalMedia(listing_id=listing.id, kind="video", file_path=video_rel))

            db.session.commit()
            log_access(
                "update_rental_listing",
                "rental_listing",
                listing.id,
                success=True,
                changes={"shop_id": listing.shop_id, "status": listing.status},
            )
            flash("Annonce location mise à jour.", "success")
            _flash_rental_media_notice(
                skipped_invalid_images=skipped_invalid_images,
                skipped_overflow_images=skipped_overflow_images,
                video_notice=video_notice,
            )
            return redirect(url_for("rentals.owner_location_edit", listing_id=listing.id))
        except ValueError as exc:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            current_app.logger.warning(f"Validation error editing listing {listing_id}: {exc}")
            flash(str(exc), "warning")
        except SQLAlchemyError as e:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            current_app.logger.error(f"Database error editing listing {listing_id}: {e}")
            flash("Erreur base de données lors de la mise à jour.", "danger")
        except Exception as e:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            current_app.logger.exception(f"Unexpected error editing listing {listing_id}: {e}")
            flash("Erreur inattendue lors de la mise à jour.", "danger")

    owner_view = _listing_owner_view(listing)
    return render_template(
        "locations/owner_form.html",
        listing=listing,
        shops=shops,
        max_images=MAX_IMAGE_COUNT,
        max_image_mb=int(MAX_IMAGE_BYTES / 1024 / 1024),
        max_video_mb=int(MAX_VIDEO_BYTES / 1024 / 1024),
        cents_to_dh=cents_to_dh,
        owner_view=owner_view,
        format_dt=_format_dt,
        admin_rental_rate_bps=int(settings.rental_success_commission_bps or 0),
        bps_to_percent=_bps_to_percent,
        commission_amount_from_owner_fee=commission_amount_from_owner_fee,
    )


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

    listings_pg = lq.order_by(RentalListing.created_at.desc()).paginate(
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
    archives_pg = archives_query.order_by(RentalArchive.closed_at.desc()).paginate(
        page=a_page, per_page=A_PER, error_out=False
    )

    owners          = (
        User.query
        .options(load_only(User.id, User.username))
        .filter_by(role="vendor")
        .order_by(User.username.asc())
        .all()
    )
    archives_count  = archives_query.order_by(None).count()
    active_count    = lq.order_by(None).count()
    expired_pending = lq.filter(RentalListing.expires_at <= datetime.utcnow()).order_by(None).count()
    settings = PlatformSettings.get()

    return render_template(
        "admin/locations.html",
        listings=listings_pg.items,
        listings_pg=listings_pg,
        archives=archives_pg.items,
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
        cents_to_dh=cents_to_dh,
        format_dt=_format_dt,
        bps_to_percent=_bps_to_percent,
        commission_amount_from_owner_fee=commission_amount_from_owner_fee,
    )
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


@bp.route("/admin/locations/cleanup", methods=["POST"])
@login_required
def admin_locations_cleanup():
    guard = _admin_required()
    if guard:
        return guard

    cli_hint = "flask cleanup --mode full --days 21"
    message = f"Cleanup des locations déplacé vers CLI: {cli_hint}"
    log_access(
        "cleanup_rental_listings_blocked_http",
        "rental_listing",
        0,
        success=False,
        changes={"cli": cli_hint},
    )
    if _is_ajax_request():
        return jsonify({"success": False, "message": message}), 409

    flash(message, "info")
    return redirect(url_for("rentals.admin_locations"))
