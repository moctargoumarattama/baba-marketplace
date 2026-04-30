from datetime import datetime
from urllib.parse import quote, unquote

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models.order import Order
from ..models.platform_settings import PlatformSettings
from ..services.delivery_context import (
    DELIVERY_SOURCE_SPECIAL,
    canonical_city_name,
    make_maps_url,
    safe_float,
)
from ..services.pricing import (
    get_delivery_platform_fee_cents,
    get_delivery_price_cents,
    list_delivery_cities,
)
from ..services.traffic_stats import track_custom_event
from ..middleware.rate_limit import rate_limit

bp = Blueprint("delivery_special", __name__)

MAX_TEXT_LENGTH = 500
MIN_PHONE_DIGITS = 8
MAX_PHONE_DIGITS = 15


def _digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _validate_phone(phone: str) -> bool:
    digits = _digits_only(phone)
    return MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS


def _support_whatsapp_number() -> str:
    return (
        _digits_only(current_app.config.get("SUPPORT_WHATSAPP_NUMBER"))
        or _digits_only(current_app.config.get("ADMIN_PHONE"))
    )


def _clean(value: str | None, max_length: int = MAX_TEXT_LENGTH) -> str:
    cleaned = (value or "").strip()
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def _safe_maps_url(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("https://www.google.com/maps") or raw.startswith("https://maps.google.com"):
        return raw
    return ""


def _format_price_dh(price_cents: int) -> str:
    return f"{(int(price_cents or 0) / 100):.2f}"


def _parse_datetime(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed_dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        return parsed_dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return raw


@bp.route("/delivery/whatsapp")
def delivery_whatsapp_redirect():
    encoded_url = (request.args.get("wa") or "").strip()
    if not encoded_url:
        flash("Lien WhatsApp manquant.", "warning")
        return redirect(url_for("delivery_special.delivery_form"))

    wa_url = unquote(encoded_url)
    if not wa_url.startswith("https://wa.me/"):
        flash("Lien WhatsApp invalide.", "warning")
        return redirect(url_for("delivery_special.delivery_form"))

    try:
        track_custom_event("delivery_whatsapp_open")
    except Exception:
        pass

    return render_template(
        "support/open_whatsapp.html",
        wa_url=wa_url,
        support_scope="Livraison",
        support_title="Demande de livraison prête",
        support_copy="Votre message WhatsApp est prêt pour la livraison express.",
        back_url=url_for("delivery_special.delivery_form"),
        back_label="Retour au formulaire",
    )


@bp.route("/delivery", methods=["GET"])
def delivery_form_get():
    cities = list_delivery_cities()
    return render_template("delivery.html", cities=cities)


@bp.route("/delivery", methods=["POST"])
@rate_limit(limit=8, window_seconds=3600)
def delivery_form_post():
    cities = list_delivery_cities()

    city = _clean(request.form.get("city"))
    name = _clean(request.form.get("name"), max_length=100)
    phone = _clean(request.form.get("phone"))

    current_app.logger.info(
        "special_delivery_post_start city=%s has_name=%s has_phone=%s",
        city,
        bool(name),
        bool(phone),
    )

    if not city or not name or not phone:
        flash("Ville, nom et téléphone sont obligatoires.", "warning")
        return render_template("delivery.html", cities=cities)

    if not _validate_phone(phone):
        flash("Numéro de téléphone invalide.", "warning")
        return render_template("delivery.html", cities=cities)

    try:
        settings = PlatformSettings.get()
    except Exception:
        current_app.logger.exception("delivery_special_settings_unavailable")
        flash("Configuration livraison indisponible. Merci de réessayer.", "danger")
        return render_template("delivery.html", cities=cities)

    price_cents = get_delivery_price_cents(city, settings=settings)
    if price_cents <= 0:
        flash("Ville non supportée pour la livraison express.", "warning")
        return render_template("delivery.html", cities=cities)

    order_city = canonical_city_name(city, Order.CITIES)
    if not order_city:
        flash("Ville invalide pour la livraison.", "warning")
        return render_template("delivery.html", cities=cities)

    item_text = _clean(request.form.get("item_text"))
    pickup_text = _clean(request.form.get("pickup_text"))
    dropoff_text = _clean(request.form.get("dropoff_text"))
    note_text = _clean(request.form.get("note_text"))

    urgent = bool(request.form.get("urgent"))
    pickup_lat = safe_float(request.form.get("pickup_lat"))
    pickup_lng = safe_float(request.form.get("pickup_lng"))
    dropoff_lat = safe_float(request.form.get("dropoff_lat"))
    dropoff_lng = safe_float(request.form.get("dropoff_lng"))

    pickup_maps_from_form = _safe_maps_url(request.form.get("pickup_maps_url"))
    dropoff_maps_from_form = _safe_maps_url(request.form.get("dropoff_maps_url"))

    desired_raw = _clean(request.form.get("desired_datetime"))
    desired_text = _parse_datetime(desired_raw)

    phone_digits = _digits_only(phone)
    dropoff_address = dropoff_text or None

    pickup_maps = pickup_maps_from_form or make_maps_url(
        lat=pickup_lat,
        lng=pickup_lng,
        address=pickup_text,
        city=city,
    )
    dropoff_maps = dropoff_maps_from_form or make_maps_url(
        lat=dropoff_lat,
        lng=dropoff_lng,
        address=dropoff_text,
        city=city,
    )

    delivery_platform_fee_cents = get_delivery_platform_fee_cents(settings=settings)

    try:
        order = Order(
            full_name=name,
            phone=phone,
            phone_digits=phone_digits,
            customer_name=name,
            customer_phone=phone,
            city=order_city,
            address=dropoff_address or "N/A",
            status="pending",
            total=price_cents,
            shipping=price_cents,
            commission=0,
            vendor_net=0,
            delivery_source=DELIVERY_SOURCE_SPECIAL,
            delivery_city=city,
            delivery_address=dropoff_address,
            delivery_lat=dropoff_lat,
            delivery_lng=dropoff_lng,
            delivery_maps_url=dropoff_maps or None,
            delivery_price_cents=price_cents,
            delivery_platform_fee_cents=delivery_platform_fee_cents,
            special_item=item_text or None,
            special_pickup_address=pickup_text or None,
            special_pickup_lat=pickup_lat,
            special_pickup_lng=pickup_lng,
            special_pickup_maps_url=pickup_maps or None,
            special_dropoff_address=dropoff_text or None,
            special_dropoff_lat=dropoff_lat,
            special_dropoff_lng=dropoff_lng,
            special_dropoff_maps_url=dropoff_maps or None,
            special_note=note_text or None,
            special_datetime=desired_text or desired_raw or None,
            special_is_urgent=urgent,
        )

        db.session.add(order)
        db.session.commit()

        try:
            track_custom_event("delivery_inquiry_created")
        except Exception:
            pass

    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("delivery_special_order_create_failed")
        flash("Erreur base de données. Merci de réessayer.", "danger")
        return render_template("delivery.html", cities=cities)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("delivery_special_unexpected_failed")
        flash("Création de demande impossible pour le moment.", "danger")
        return render_template("delivery.html", cities=cities)

    lines = [
        "Demande de livraison express",
        f"Référence : #{order.id}",
        f"Ville : {city}",
        f"Prix estimé : {_format_price_dh(price_cents)} DH",
        "",
        f"Nom : {name}",
        f"Téléphone : {phone}",
        "",
    ]

    if item_text:
        lines.append(f"Objet : {item_text}")
    if pickup_text:
        lines.append(f"Départ : {pickup_text}")
    if pickup_maps:
        lines.append(f"Maps départ : {pickup_maps}")
    if dropoff_text:
        lines.append(f"Arrivée : {dropoff_text}")
    if dropoff_maps:
        lines.append(f"Maps arrivée : {dropoff_maps}")
    if note_text:
        lines.append(f"Repère : {note_text}")
    if urgent:
        lines.append("Urgent : Oui")
    if desired_text:
        lines.append(f"Heure souhaitée : {desired_text}")

    lines.extend(["", "Merci de me confirmer la suite."])
    message = "\n".join(lines)

    whatsapp_url = f"https://wa.me/{_support_whatsapp_number()}?text={quote(message)}"
    return redirect(url_for("delivery_special.delivery_whatsapp_redirect", wa=quote(whatsapp_url, safe="")))


@bp.route("/delivery", methods=["GET", "POST"])
def delivery_form():
    if request.method == "GET":
        return delivery_form_get()
    return delivery_form_post()
