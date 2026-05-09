import re
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, load_only

from ..extensions import db
from ..middleware.rate_limit import rate_limit
from ..models.blocked import BlockedContact
from ..models.booking import Booking
from ..models.product import Product
from ..models.shop import Shop
from ..services.pricing import prix_final
from ..services.traffic_stats import track_custom_event
from ..services.vendor_push import notify_service_booking


bp = Blueprint("booking", __name__, url_prefix="/booking")


def _booking_product_query():
    return Product.query.options(
        load_only(
            Product.id,
            Product.kind,
            Product.name,
            Product.description,
            Product.price,
            Product.price_cents_value,
            Product.is_active,
            Product.shop_id,
        ),
        joinedload(Product.shop).load_only(
            Shop.id,
            Shop.name,
            Shop.address,
            Shop.contact_phone,
            Shop.is_active,
            Shop.is_open,
            Shop.closed_until,
        ),
    )


def _booking_track_query():
    return Booking.query.options(
        load_only(
            Booking.id,
            Booking.token,
            Booking.product_id,
            Booking.shop_id,
            Booking.full_name,
            Booking.phone,
            Booking.scheduled_for,
            Booking.note,
            Booking.status,
        ),
        joinedload(Booking.product).load_only(
            Product.id,
            Product.name,
            Product.description,
            Product.price,
            Product.price_cents_value,
        ),
        joinedload(Booking.shop).load_only(
            Shop.id,
            Shop.name,
        ),
    )


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_phone(value: str) -> str:
    raw = (value or "").strip()
    digits = _digits_only(raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return f"+{digits}"
    return digits


def _client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or ""


def _shop_is_currently_open(shop) -> bool:
    """Vérifie si la boutique est ouverte (version robuste)."""
    if not shop or not shop.is_active:
        return False
    if shop.closed_until and shop.closed_until > datetime.utcnow():
        return False
    if hasattr(shop, 'is_open_now') and callable(shop.is_open_now):
        return shop.is_open_now()
    return bool(shop.is_open)


def _recent_booking_url(pid: int, max_age_seconds: int = 120) -> str | None:
    """Retourne une URL WhatsApp récente pour éviter les doubles soumissions."""
    url = session.get("last_booking_url")
    ts = session.get("last_booking_at")
    last_pid = session.get("last_booking_pid")
    if not url or not ts:
        return None
    if last_pid is not None and str(last_pid) != str(pid):
        return None
    try:
        last = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    if datetime.utcnow() - last <= timedelta(seconds=max_age_seconds):
        return url
    return None


def normalize_whatsapp_number(raw: str) -> str:
    """Normalise un numéro pour wa.me (format international sans '+').

    Règles (Maroc):
    - 06XXXXXXXX -> 2126XXXXXXXX
    - 07XXXXXXXX -> 2127XXXXXXXX
    - 6XXXXXXXX / 7XXXXXXXX -> 2126... / 2127...
    - 00CC... -> CC...
    """
    digits = _digits_only(raw)
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10 and digits[1] in ("6", "7"):
        return "212" + digits[1:]
    if len(digits) == 9 and digits[0] in ("6", "7"):
        return "212" + digits
    return digits


def _whatsapp_number_from_shop(product: Product) -> str:
    """Retourne un numéro WhatsApp (digits) du prestataire (boutique)."""
    shop = getattr(product, "shop", None)
    if not shop:
        return ""
    raw = getattr(shop, "contact_phone", "") or ""
    return normalize_whatsapp_number(raw)


def build_whatsapp_booking_message(booking: Booking) -> str:
    product = booking.product
    shop = booking.shop
    site_name = current_app.config.get("SITE_NAME", "Baba Market Place")

    final_price = prix_final(product)
    when = booking.scheduled_for.strftime("%Y-%m-%d %H:%M") if booking.scheduled_for else "À confirmer"
    track_url = f"{request.host_url.rstrip('/')}/booking/track/{booking.token}"

    lines = []
    lines.append("========== NOUVELLE RÉSERVATION ==========")
    lines.append(f"Site: {site_name}")
    if shop:
        lines.append(f"Boutique: {shop.name}")
    lines.append("--------------------------------------")
    lines.append(f"Service: {product.name}")
    lines.append(f"Prix: {final_price:.2f} MAD")
    lines.append(f"Date/Heure: {when}")
    lines.append("--------------------------------------")
    lines.append(f"Client: {booking.full_name}")
    lines.append(f"Téléphone: {booking.phone}")
    if booking.note:
        note = booking.note.strip()
        if len(note) > 300:
            note = note[:300].rstrip() + "…"
        lines.append(f"Note: {note}")
    lines.append("--------------------------------------")
    lines.append(f"Suivi: {track_url}")
    msg = "\n".join(lines)
    # Eviter les URLs WhatsApp trop longues.
    if len(msg) > 900:
        msg = msg[:900].rstrip() + "\n..."
    return msg


@bp.route("/<int:pid>", methods=["GET", "POST"])
@rate_limit(limit=20, window_seconds=300, key_prefix="booking", methods=("POST",))
def book(pid):
    product = _booking_product_query().filter(Product.id == pid).first_or_404()
    kind = (getattr(product, "kind", "physical") or "physical").strip().lower()

    if kind != "service":
        flash("Cet article est un produit livrable. Ajoutez-le au panier.", "info")
        return redirect(url_for("shop.product_detail", pid=product.id))

    if not product.is_active:
        flash("Ce service n'est plus disponible.", "warning")
        return redirect(url_for("shop.home"))

    shop = getattr(product, "shop", None)

    # Si la boutique est fermée, on propose directement WhatsApp
    if shop and not _shop_is_currently_open(shop):
        recent = _recent_booking_url(product.id)
        if recent:
            return render_template(
                "support/open_whatsapp.html",
                wa_url=recent,
                support_scope="Rendez-vous",
                support_title="WhatsApp deja pret",
                support_copy="Votre lien de rendez-vous est deja prepare. Ouvrez WhatsApp pour continuer.",
                back_url=url_for("shop.home"),
                back_label="Revenir au catalogue",
            )

        number = _whatsapp_number_from_shop(product)
        if not number:
            flash("Contact boutique manquant.", "warning")
            return redirect(url_for("shop.product_detail", pid=product.id))

        shop_name = (getattr(shop, "name", "") or "").strip() or "Boutique"
        service_url = url_for("shop.product_detail", pid=product.id, _external=True)
        message = (
            f"Bonjour 👋 Je souhaite un rendez-vous pour: {product.name} chez {shop_name}. "
            "Vous êtes disponible quand ? Merci.\n"
            f"Lien: {service_url}"
        )
        wa_url = f"https://wa.me/{number}?text={quote(message)}"

        session["last_booking_url"] = wa_url
        session["last_booking_at"] = datetime.utcnow().isoformat()
        session["last_booking_pid"] = product.id
        try:
            track_custom_event("whatsapp_open")
        except Exception:
            pass

        return render_template(
            "support/open_whatsapp.html",
            wa_url=wa_url,
            support_scope="Rendez-vous",
            support_title="Demande de rendez-vous prete",
            support_copy="Votre message WhatsApp est pret pour contacter la boutique.",
            back_url=url_for("shop.home"),
            back_label="Revenir au catalogue",
        )

    if request.method == "POST":
        recent = _recent_booking_url(product.id)
        if recent:
            return render_template(
                "support/open_whatsapp.html",
                wa_url=recent,
                support_scope="Rendez-vous",
                support_title="WhatsApp deja pret",
                support_copy="Votre lien de rendez-vous est deja prepare. Ouvrez WhatsApp pour continuer.",
                back_url=url_for("shop.home"),
                back_label="Revenir au catalogue",
            )

        full_name = (request.form.get("full_name") or "").strip()[:100]
        phone_raw = (request.form.get("phone") or "").strip()
        scheduled_raw = (request.form.get("scheduled_for") or "").strip()
        note = (request.form.get("note") or "").strip()[:2000]

        phone = normalize_phone(phone_raw)
        phone_digits = _digits_only(phone)
        client_ip = _client_ip()

        if not full_name or not phone:
            flash("Veuillez renseigner votre nom et votre téléphone.", "danger")
            return redirect(url_for("booking.book", pid=product.id))

        if len(phone_digits) < 6:
            flash("Numéro de téléphone invalide.", "danger")
            return redirect(url_for("booking.book", pid=product.id))

        blocked_phone = (
            BlockedContact.query.filter_by(
                kind="phone",
                value=phone_digits,
                is_active=True,
            ).first()
            if phone_digits else None
        )
        blocked_ip = (
            BlockedContact.query.filter_by(
                kind="ip",
                value=client_ip,
                is_active=True,
            ).first()
            if client_ip else None
        )

        if blocked_phone or blocked_ip:
            flash("Réservation bloquée. Contactez le support.", "danger")
            return redirect(url_for("booking.book", pid=product.id))

        scheduled_for = None
        if scheduled_raw:
            try:
                scheduled_for = datetime.fromisoformat(scheduled_raw)
            except ValueError:
                flash("Date/heure invalide.", "danger")
                return redirect(url_for("booking.book", pid=product.id))

            # Pas trop strict : on refuse seulement une date clairement passée
            if scheduled_for < datetime.utcnow() - timedelta(minutes=5):
                flash("La date de rendez-vous semble être dans le passé.", "danger")
                return redirect(url_for("booking.book", pid=product.id))

        number = _whatsapp_number_from_shop(product)
        if not number:
            flash("Le prestataire n'a pas configuré de numéro de contact WhatsApp.", "warning")
            return redirect(url_for("shop.product_detail", pid=product.id))

        try:
            booking = Booking(
                buyer_id=current_user.id if current_user.is_authenticated else None,
                product_id=product.id,
                shop_id=shop.id if shop else None,
                full_name=full_name,
                phone=phone,
                phone_digits=phone_digits,
                scheduled_for=scheduled_for,
                note=note or None,
                status="pending",
                booking_ip=client_ip,
            )
            db.session.add(booking)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Erreur réservation")
            flash("Erreur serveur. Merci de réessayer.", "danger")
            return redirect(url_for("booking.book", pid=product.id))

        try:
            notify_service_booking(booking)
        except Exception:
            current_app.logger.exception(
                "vendor_push.service_booking_notify_failed",
                extra={"booking_id": getattr(booking, "id", None), "product_id": product.id},
            )

        session["booking_phone"] = phone

        message = build_whatsapp_booking_message(booking)
        wa_url = f"https://wa.me/{number}?text={quote(message)}"

        session["last_booking_url"] = wa_url
        session["last_booking_at"] = datetime.utcnow().isoformat()
        session["last_booking_pid"] = product.id
        try:
            track_custom_event("whatsapp_open")
        except Exception:
            pass

        return render_template(
            "support/open_whatsapp.html",
            wa_url=wa_url,
            support_scope="Rendez-vous",
            support_title="Reservation prete",
            support_copy="Votre demande est prete dans WhatsApp. Vous pouvez aussi suivre votre reservation.",
            back_url=url_for("shop.home"),
            back_label="Revenir au catalogue",
            secondary_url=url_for("booking.track", token=booking.token),
            secondary_label="Suivre ma reservation",
            secondary_icon="bi-calendar-check",
        )

    remembered_phone = session.get("booking_phone", "")
    return render_template(
        "booking/booking_form.html",
        product=product,
        shop=shop,
        remembered_phone=remembered_phone,
        prix_final=prix_final,
    )

@bp.route("/track/<token>")
def track(token):
    booking = _booking_track_query().filter_by(token=token).first_or_404()
    return render_template("booking/track_booking.html", booking=booking, prix_final=prix_final)
