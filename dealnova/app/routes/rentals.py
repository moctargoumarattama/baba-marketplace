from datetime import datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from slugify import slugify
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models.platform_settings import PlatformSettings
from ..models.rental import RentalArchive, RentalListing, RentalMedia
from ..models.shop import Shop
from ..models.user import User
from ..services.audit import log_access
from ..services.pagination import page_from_args
from ..services.shop_access import ensure_shop_allows, ensure_vendor_allows
from ..services.rentals import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_COUNT,
    MAX_VIDEO_BYTES,
    archive_and_remove_listing,
    cents_to_dh,
    commission_amount_from_owner_fee,
    delete_static_file,
    save_rental_image,
    save_rental_video,
)


bp = Blueprint("rentals", __name__)


def _is_ajax_request() -> bool:
    return (
        request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )


def _support_whatsapp_number() -> str:
    raw = (
        current_app.config.get("SUPPORT_WHATSAPP_NUMBER")
        or current_app.config.get("ADMIN_PHONE")
        or "212770010264"
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
        raise ValueError(f"{field_name} doit tre positif.")
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


def _listing_whatsapp_url(listing: RentalListing, include_fields: bool = True) -> str:
    listing_url = url_for("rentals.location_detail", slug=listing.slug, _external=True)
    price_txt = cents_to_dh(listing.rent_cents)
    message = (
        f"Bonjour, je veux une visite pour: {listing.title} ({price_txt}).\n"
        f"Lien: {listing_url}"
    )
    if include_fields:
        message += "\nMon nom: \nTel: \nDate souhaite: \nMessage: "
    number = _support_whatsapp_number()
    return f"https://wa.me/{number}?text={quote(message)}"


def _bps_to_percent(rate_bps: int | None) -> float:
    return round((int(rate_bps or 0) / 100), 2)


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
        flash("Accs rserv aux propritaires.", "warning")
        return redirect(url_for("shop.home"))
    return None


def _admin_required():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if getattr(current_user, "role", None) != "admin":
        flash("Accs rserv aux administrateurs.", "warning")
        return redirect(url_for("shop.home"))
    return None


def _owner_shops(owner_id: int, location_only: bool = False):
    query = Shop.query.filter_by(vendor_id=owner_id)
    if location_only:
        query = query.filter(Shop.sql_allows_clause("location"))
    return query.order_by(Shop.name.asc()).all()


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
        selectinload(RentalListing.shop),
        selectinload(RentalListing.media),
    )

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

    try:
        if price_min:
            query = query.filter(RentalListing.rent_cents >= _to_cents(price_min, "Prix min"))
        if price_max:
            query = query.filter(RentalListing.rent_cents <= _to_cents(price_max, "Prix max"))
    except ValueError:
        flash("Filtre prix invalide.", "warning")

    pagination = query.order_by(RentalListing.created_at.desc()).paginate(page=page, per_page=12, error_out=False)
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

    can_count = True
    if current_user.is_authenticated:
        if current_user.role == "admin":
            can_count = False
        if current_user.id == listing.owner_id:
            can_count = False
    # Keep GET read-only; avoid state mutation during detail rendering.

    images = [m for m in (listing.media or []) if m.kind == "image"]
    videos = [m for m in (listing.media or []) if m.kind == "video"]
    whatsapp_url = _listing_whatsapp_url(listing)

    return render_template(
        "locations/detail.html",
        listing=listing,
        images=images,
        videos=videos,
        whatsapp_url=whatsapp_url,
        cents_to_dh=cents_to_dh,
    )


@bp.route("/location/<string:slug>/inquiry", methods=["GET", "POST"])
def location_inquiry(slug: str):
    listing = _public_listing_query().filter(RentalListing.slug == slug).first_or_404()
    whatsapp_url = _listing_whatsapp_url(listing)
    return redirect(whatsapp_url)


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

    listings = query.order_by(RentalListing.created_at.desc()).all()
    total_views = sum(int(l.view_count or 0) for l in listings)
    top_viewed = sorted(listings, key=lambda row: int(row.view_count or 0), reverse=True)[:5]
    active_count = sum(1 for row in listings if row.status == "active")
    expired_count = sum(
        1
        for row in listings
        if (row.expires_at and row.expires_at <= datetime.utcnow()) or row.status == "expired"
    )

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
    archive_cutoff = datetime.utcnow() - timedelta(days=30)
    owner_archives_query = (
        RentalArchive.query
        .filter(RentalArchive.owner_id == current_user.id)
        .filter(RentalArchive.closed_at >= archive_cutoff)
    )
    owner_archives_last_30_count = owner_archives_query.count()
    latest_archive = owner_archives_query.order_by(RentalArchive.closed_at.desc()).first()
    settings = PlatformSettings.get()

    return render_template(
        "locations/owner_index.html",
        listings=listings,
        shops=shops,
        status=status,
        selected_shop_id=shop_id,
        q=q,
        total_views=total_views,
        active_count=active_count,
        expired_count=expired_count,
        top_viewed=top_viewed,
        shop_stats=shop_stats,
        owner_archives_last_30_count=owner_archives_last_30_count,
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

    archive_cutoff = datetime.utcnow() - timedelta(days=30)
    query = (
        RentalArchive.query
        .options(selectinload(RentalArchive.shop))
        .filter(RentalArchive.owner_id == current_user.id)
        .filter(RentalArchive.closed_at >= archive_cutoff)
        .filter(RentalArchive.shop_id.in_(shop_ids))
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
        archive_cutoff=archive_cutoff,
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
        flash("Aucune boutique autorisee pour Location.", "warning")
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

            owner_fee_cents = _to_cents(request.form.get("owner_fee"), "Frais propritaire", required=False)
            owner_fee_text = (request.form.get("owner_fee_text") or "").strip()
            if len(owner_fee_text) > 255:
                raise ValueError("Texte frais propritaire trop long (max 255 caractres).")

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
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=6),
            )
            db.session.add(listing)
            db.session.flush()

            image_files = [f for f in request.files.getlist("images") if f and f.filename]
            if len(image_files) > MAX_IMAGE_COUNT:
                raise ValueError(f"Maximum {MAX_IMAGE_COUNT} images.")

            for image_file in image_files:
                image_rel = save_rental_image(image_file)
                saved_files.append(image_rel)
                db.session.add(RentalMedia(listing_id=listing.id, kind="image", file_path=image_rel))

            video_file = request.files.get("video")
            if video_file and video_file.filename:
                video_rel = save_rental_video(video_file)
                saved_files.append(video_rel)
                db.session.add(RentalMedia(listing_id=listing.id, kind="video", file_path=video_rel))

            db.session.commit()
            log_access(
                "create_rental_listing",
                "rental_listing",
                listing.id,
                success=True,
                changes={"shop_id": listing.shop_id, "listing_type": listing.listing_type},
            )
            flash("Annonce location cre.", "success")
            return redirect(url_for("rentals.owner_locations"))
        except ValueError as exc:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            flash(str(exc), "warning")
        except Exception:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            flash("Erreur lors de la cration de l'annonce.", "danger")

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

            listing.owner_fee_cents = _to_cents(request.form.get("owner_fee"), "Frais propritaire", required=False)
            owner_fee_text = (request.form.get("owner_fee_text") or "").strip()
            if len(owner_fee_text) > 255:
                raise ValueError("Texte frais propritaire trop long (max 255 caractres).")
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
            if len(existing_images) + len(image_files) > MAX_IMAGE_COUNT:
                raise ValueError(f"Maximum {MAX_IMAGE_COUNT} images.")

            new_video = request.files.get("video")
            if new_video and new_video.filename and existing_videos:
                raise ValueError("Supprimez la vido actuelle avant d'en ajouter une nouvelle.")

            for media_row in list(listing.media):
                if media_row.id in remove_media_ids:
                    delete_static_file(media_row.file_path)
                    db.session.delete(media_row)

            for image_file in image_files:
                image_rel = save_rental_image(image_file)
                saved_files.append(image_rel)
                db.session.add(RentalMedia(listing_id=listing.id, kind="image", file_path=image_rel))

            if new_video and new_video.filename:
                video_rel = save_rental_video(new_video)
                saved_files.append(video_rel)
                db.session.add(RentalMedia(listing_id=listing.id, kind="video", file_path=video_rel))

            db.session.commit()
            log_access(
                "update_rental_listing",
                "rental_listing",
                listing.id,
                success=True,
                changes={"shop_id": listing.shop_id, "status": listing.status},
            )
            flash("Annonce location mise  jour.", "success")
            return redirect(url_for("rentals.owner_location_edit", listing_id=listing.id))
        except ValueError as exc:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            flash(str(exc), "warning")
        except Exception:
            db.session.rollback()
            for rel_path in saved_files:
                delete_static_file(rel_path)
            flash("Erreur lors de la mise  jour.", "danger")

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
        flash("Annonce marque comme rserve.", "success")
        return redirect(request.referrer or url_for("rentals.owner_locations"))

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
    flash("Annonce clture et archive.", "success")
    return redirect(request.referrer or url_for("rentals.owner_locations"))


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
    flash("Annonce supprime et archive.", "success")
    return redirect(request.referrer or url_for("rentals.owner_locations"))


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
    flash("Mdia supprim.", "success")
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

    listings_pg = lq.order_by(RentalListing.created_at.desc()).paginate(
        page=page, per_page=PER, error_out=False
    )

    #  Archives 
    archives_pg = (
        RentalArchive.query
        .options(
            selectinload(RentalArchive.shop),
            selectinload(RentalArchive.owner),
        )
        .order_by(RentalArchive.closed_at.desc())
        .paginate(page=a_page, per_page=A_PER, error_out=False)
    )

    owners          = User.query.filter_by(role="vendor").order_by(User.username.asc()).all()
    archives_count  = RentalArchive.query.count()
    active_count    = RentalListing.query.count()
    expired_pending = RentalListing.query.filter(
        RentalListing.expires_at <= datetime.utcnow()
    ).count()
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
    flash("Annonce supprime par admin et archive.", "success")
    return redirect(request.referrer or url_for("rentals.admin_locations"))


@bp.route("/admin/locations/cleanup", methods=["POST"])
@login_required
def admin_locations_cleanup():
    guard = _admin_required()
    if guard:
        return guard

    cli_hint = "flask cleanup --mode full --days 21"
    message = f"Cleanup des locations deplace vers CLI: {cli_hint}"
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
