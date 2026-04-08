from datetime import datetime
from urllib.parse import quote, unquote

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models.order import Order
from ..models.platform_settings import PlatformSettings  # Import déplacé en haut
from ..services.delivery_context import (
    DELIVERY_SOURCE_SPECIAL,
    canonical_city_name,
    make_maps_url,
    safe_float,
)
from ..services.pricing import (
    get_delivery_courier_net_cents,
    get_delivery_platform_fee_cents,
    get_delivery_price_cents,
    list_delivery_cities,
)
from ..services.order_periods import get_or_create_open_order_period  # Import déplacé
from ..services.traffic_stats import track_order_created, track_custom_event  # Import déplacé
from ..middleware.rate_limit import rate_limit  # AJOUT : Rate limiting

bp = Blueprint("delivery_special", __name__)

# Constantes
MAX_TEXT_LENGTH = 500
MIN_PHONE_DIGITS = 8
MAX_PHONE_DIGITS = 15


def _digits_only(value: str | None) -> str:
    """Extrait uniquement les chiffres d'une chaîne."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _validate_phone(phone: str) -> bool:
    """Valide le format du téléphone (8-15 chiffres)."""
    digits = _digits_only(phone)
    return MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS


def _support_whatsapp_number() -> str:
    """Retourne le numéro WhatsApp de support."""
    return (
        _digits_only(current_app.config.get("SUPPORT_WHATSAPP_NUMBER"))
        or _digits_only(current_app.config.get("ADMIN_PHONE"))
        or "212770010264"
    )


def _clean(value: str | None, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Nettoie une chaîne et limite sa longueur."""
    cleaned = (value or "").strip()
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def _safe_maps_url(value: str | None) -> str:
    """Valide une URL Google Maps."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("https://www.google.com/maps") or raw.startswith("https://maps.google.com"):
        return raw
    return ""


def _format_price_dh(price_cents: int) -> str:
    """Formate un prix en centimes en DH."""
    return f"{(int(price_cents or 0) / 100):.2f}"


def _parse_datetime(raw: str) -> str:
    """Parse une date au format ISO et retourne un format lisible."""
    if not raw:
        return ""
    try:
        parsed_dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        return parsed_dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return raw


@bp.route("/delivery/whatsapp")
def delivery_whatsapp_redirect():
    """Redirection vers WhatsApp après création de commande."""
    encoded_url = (request.args.get("wa") or "").strip()
    if not encoded_url:
        flash("Lien WhatsApp manquant.", "warning")
        return redirect(url_for("delivery_special.delivery_form"))

    wa_url = unquote(encoded_url)
    if not wa_url.startswith("https://wa.me/"):
        flash("Lien WhatsApp invalide.", "warning")
        return redirect(url_for("delivery_special.delivery_form"))
    try:
        track_custom_event("whatsapp_open")
    except Exception:
        pass

    return render_template(
        "support/open_whatsapp.html",
        wa_url=wa_url,
        support_scope="Livraison",
        support_title="Demande de livraison prete",
        support_copy="Votre message WhatsApp est pret pour la livraison speciale.",
        back_url=url_for("delivery_special.delivery_form"),
        back_label="Retour au formulaire",
    )


@bp.route("/delivery", methods=["GET"])
def delivery_form_get():
    """Affiche le formulaire de livraison spéciale."""
    cities = list_delivery_cities()
    return render_template("delivery.html", cities=cities)


@bp.route("/delivery", methods=["POST"])
@rate_limit(limit=8, window_seconds=3600)  # 8 requêtes par heure
def delivery_form_post():
    """Traite le formulaire de livraison spéciale et crée la commande."""
    cities = list_delivery_cities()
    
    # Récupération et nettoyage des champs
    city = _clean(request.form.get("city"))
    name = _clean(request.form.get("name"), max_length=100)  # Nom limité à 100
    phone = _clean(request.form.get("phone"))

    current_app.logger.info(
        "special_delivery_post_start city=%s has_name=%s has_phone=%s",
        city,
        bool(name),
        bool(phone),
    )

    # Validation des champs obligatoires
    if not city or not name or not phone:
        current_app.logger.warning("special_delivery_post_rejected reason=missing_fields city=%s", city)
        flash("Ville, nom et téléphone sont obligatoires.", "warning")
        return render_template("delivery.html", cities=cities)

    # Validation du téléphone
    if not _validate_phone(phone):
        current_app.logger.warning("special_delivery_post_rejected reason=invalid_phone city=%s", city)
        flash("Numéro de téléphone invalide (8-15 chiffres).", "warning")
        return render_template("delivery.html", cities=cities)

    try:
        settings = PlatformSettings.get()
    except Exception as e:
        current_app.logger.error(f"Failed to get platform settings: {e}")
        flash("Configuration livraison indisponible. Merci de réessayer.", "danger")
        return render_template("delivery.html", cities=cities)

    # Vérification du prix de livraison
    price_cents = get_delivery_price_cents(city, settings=settings)
    if price_cents <= 0:
        current_app.logger.warning("special_delivery_post_rejected reason=unsupported_city city=%s", city)
        flash("Ville non supportée pour la livraison spéciale.", "warning")
        return render_template("delivery.html", cities=cities)

    # Normalisation de la ville
    order_city = canonical_city_name(city, Order.CITIES)
    if not order_city:
        current_app.logger.warning("special_delivery_post_rejected reason=invalid_city city=%s", city)
        flash("Ville invalide pour la commande.", "warning")
        return render_template("delivery.html", cities=cities)

    # Champs optionnels avec limites
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

    # Préparation des données
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

    # Calcul des frais
    delivery_platform_fee_cents = get_delivery_platform_fee_cents(settings=settings)
    delivery_courier_net_cents = get_delivery_courier_net_cents(
        price_cents,
        settings=settings,
    )
    
    current_app.logger.info(
        "special_delivery_post_pricing city=%s delivery_price_cents=%s delivery_platform_fee_cents=%s",
        city,
        price_cents,
        delivery_platform_fee_cents,
    )

    # Création de la commande
    try:
        active_period, _created = get_or_create_open_order_period(created_by=None)
        
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
            period_id=active_period.id,
            delivery_source=DELIVERY_SOURCE_SPECIAL,
            delivery_city=city,
            delivery_address=dropoff_address,
            delivery_lat=dropoff_lat,
            delivery_lng=dropoff_lng,
            delivery_maps_url=dropoff_maps or None,
            delivery_price_cents=price_cents,
            delivery_platform_fee_cents=delivery_platform_fee_cents,
            delivery_courier_net_cents=delivery_courier_net_cents,
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
        
        # Tracking (non bloquant)
        try:
            track_order_created()
        except Exception as e:
            current_app.logger.warning(f"track_order_created failed: {e}")
            
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("delivery_special_order_create_failed - DB error")
        flash("Erreur base de données. Merci de réessayer.", "danger")
        return render_template("delivery.html", cities=cities)
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("delivery_special_order_create_failed - Unexpected error")
        flash("Création de commande impossible pour le moment.", "danger")
        return render_template("delivery.html", cities=cities)

    # Construction du message WhatsApp
    lines = [
        "Demande de livraison spéciale",
        f"Commande : #{order.id}",
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

    lines.extend(["", "Merci de me confirmer et me dire la suite."])
    message = "\n".join(lines)

    whatsapp_url = f"https://wa.me/{_support_whatsapp_number()}?text={quote(message)}"
    return redirect(url_for("delivery_special.delivery_whatsapp_redirect", wa=quote(whatsapp_url, safe="")))


# Route unique GET/POST pour compatibilité
@bp.route("/delivery", methods=["GET", "POST"])
def delivery_form():
    """Point d'entrée unique pour compatibilité."""
    if request.method == "GET":
        return delivery_form_get()
    return delivery_form_post()
