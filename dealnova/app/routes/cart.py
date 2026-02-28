import secrets
import re
from datetime import datetime, timedelta
# app/routes/cart.py - LIGNE 15
from ..models.platform_settings import PlatformSettings  # CORRECTION: utilisez .. au lieu de app.
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app, jsonify, make_response, g
from flask_login import current_user
from urllib.parse import quote

from ..extensions import db
from sqlalchemy import and_, or_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from ..models.product import Product
from ..models.promo import Promo
from ..models.order import Order, OrderItem
from ..models.blocked import BlockedContact
from ..models.vendor_payout import VendorPayout
from ..services.pricing import (
    prix_final,
    get_delivery_courier_net_cents,
    get_delivery_platform_fee_cents,
    get_delivery_price_cents,
    compute_shipping_by_city as pricing_shipping_by_city,
)
from ..services.delivery_context import (
    DELIVERY_SOURCE_MARKETPLACE,
    canonical_city_name,
    make_maps_url,
)
from ..services.i18n_labels import (
    delivery_status_labels_for_lang,
    label_delivery_status,
    label_order_status,
    label_source,
    normalize_lang,
)
from ..services.guest_session import GuestSessionManager
from ..services.phone_remember import (
    read_phone_cookie_digits,
    set_phone_cookie,
    get_order_phone_digits,
    input_matches_order_phone,
    cookie_matches_order_phone,
)
from ..middleware.rate_limit import rate_limit




bp = Blueprint("cart", __name__, url_prefix="/cart")


def _delivery_whatsapp_number() -> str:
    """Numro WhatsApp du livreur/commande (format international sans '+')."""
    return (current_app.config.get("DELIVERY_WHATSAPP_NUMBER") or "").replace("+", "").replace(" ", "")


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or ""


def normalize_phone(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    raw = raw.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if raw.startswith("00"):
        raw = f"+{raw[2:]}"
    digits = _digits_only(raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return f"+{digits}"
    return digits


def _product_kind(product) -> str:
    return (getattr(product, "kind", None) or "physical").strip().lower()


def _is_service_product(product) -> bool:
    return _product_kind(product) == "service"


def _shop_open_message(product) -> str | None:
    """Retourne un message si la boutique du produit est ferme/dsactive, sinon None."""
    shop = getattr(product, "shop", None)
    if not shop:
        return None

    if getattr(shop, "is_active", True) is False:
        return "Cette boutique est temporairement indisponible."

    now = datetime.utcnow()
    closed_until = getattr(shop, "closed_until", None)
    if closed_until and closed_until > now:
        return f"Boutique ferme jusqu'au {closed_until.strftime('%d/%m/%Y %H:%M')}."

    if getattr(shop, "is_open", True) is False:
        return "Cette boutique est actuellement ferme."

    return None


def _phone_candidates(raw: str):
    normalized = normalize_phone(raw)
    digits = _digits_only(raw)
    candidates = set()
    if raw:
        candidates.add(raw)
    if normalized:
        candidates.add(normalized)
        if normalized.startswith("+"):
            candidates.add(normalized[1:])
        else:
            candidates.add(f"+{normalized}")
    if digits:
        candidates.add(digits)
    return normalized, digits, list(candidates)


def _safe_float(value: str):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _is_ajax_request():
    return (
        request.headers.get("X-Requested-With") in ("XMLHttpRequest", "fetch")
        or "application/json" in (request.headers.get("Accept") or "")
    )


def _ajax_error(message, status=400, flash_category="danger", redirect_endpoint="shop.home"):
    if _is_ajax_request():
        return jsonify({"success": False, "message": message}), status
    flash(message, flash_category)
    return redirect(url_for(redirect_endpoint))



def build_whatsapp_order_message(order: Order, map_link: str = "") -> str:
    """Message WhatsApp lisible + lien suivi."""
    shipping_cents = order.shipping or 0
    subtotal_cents = max(0, (order.total or 0) - shipping_cents)

    site_name = current_app.config.get("SITE_NAME", "Baba Market Place")

    lines = []
    lines.append("========== NOUVELLE COMMANDE ==========")
    lines.append(f"Site: {site_name}")
    lines.append(f"Commande: #{order.id}")
    lines.append(f"Suivi: {request.host_url.rstrip('/')}/cart/track/{order.token}")
    lines.append("--------------------------------------")
    lines.append("ARTICLES / BOUTIQUES")

    shop_groups = {}
    for it in order.items:
        product = it.product
        shop = getattr(product, "shop", None)
        if shop and shop.id is not None:
            key = f"shop:{shop.id}"
            shop_name = shop.name or "Boutique"
        else:
            key = f"unknown:{product.id}"
            shop_name = "Boutique inconnue"
        group = shop_groups.setdefault(key, {"name": shop_name, "shop": shop, "items": []})
        group["items"].append(it)

    for group in shop_groups.values():
        lines.append(f"* Boutique: {group['name']}")
        shop = group["shop"]
        if shop:
            if shop.contact_phone:
                lines.append(f"  Tel boutique: {shop.contact_phone}")
            if shop.address:
                lines.append(f"  Adresse boutique: {shop.address}")
        for it in group["items"]:
            line_total = (it.price * it.quantity) / 100
            lines.append(f"  - {it.quantity} x {it.product.name} - {line_total:.2f} MAD")

    lines.append("--------------------------------------")
    lines.append("LIVRAISON")
    lines.append(f"Nom: {order.full_name}")
    lines.append(f"Telephone: {order.phone}")
    lines.append(f"Ville: {order.city}")
    lines.append(f"Adresse: {order.address}")
    final_map_link = (map_link or "").strip() or (getattr(order, "delivery_maps_url", None) or "").strip()
    if final_map_link:
        lines.append(f"Localisation GPS: {final_map_link}")

    lines.append("--------------------------------------")
    lines.append("PAIEMENT")
    lines.append(f"Sous-total: {(subtotal_cents / 100):.2f} MAD")
    lines.append(f"Livraison: {(shipping_cents / 100):.2f} MAD")
    lines.append(f"Total a payer: {(order.total / 100):.2f} MAD")
    lines.append("======================================")
    return "\n".join(lines)


# =====================================================
# PANIER GUEST / UTILISATEUR
# =====================================================
def _cart_key():
    if current_user.is_authenticated:
        return f"cart_user_{current_user.id}"
    # Compat: reutiliser un panier guest existant si present
    if "cart_guest" in session:
        return "cart_guest"
    for key in session.keys():
        if key.startswith("cart_guest_"):
            return key
    guest_id = GuestSessionManager.get_or_create_guest_token()
    return f"cart_guest_{guest_id}"

def _cart_product_map(cart_dict):
    """Charge les produits du panier en une seule requete."""
    pids = []
    for pid_str in cart_dict.keys():
        try:
            pids.append(int(pid_str))
        except ValueError:
            continue
    if not pids:
        return {}
    products = (
        Product.query
        .options(selectinload(Product.shop))
        .filter(Product.id.in_(pids))
        .all()
    )
    return {p.id: p for p in products}


def _active_promo_map(product_ids: list[int], now: datetime | None = None) -> dict[int, Promo]:
    if not product_ids:
        return {}
    now_utc = now or datetime.utcnow()
    promos = (
        Promo.query
        .filter(
            Promo.product_id.in_(product_ids),
            Promo.end_date >= now_utc,
        )
        .order_by(Promo.product_id.asc(), Promo.end_date.asc())
        .all()
    )
    promo_map: dict[int, Promo] = {}
    for promo in promos:
        promo_map.setdefault(promo.product_id, promo)
    return promo_map


def _remove_service_items_from_cart(cart_dict, product_map=None):
    """Retire les services du panier (ils doivent passer par la rservation)."""
    if product_map is None:
        product_map = _cart_product_map(cart_dict)

    removed = []
    for pid_str in list(cart_dict.keys()):
        try:
            pid = int(pid_str)
        except ValueError:
            continue

        product = product_map.get(pid)
        if product and _is_service_product(product):
            removed.append(product)
            cart_dict.pop(pid_str, None)

    return removed


def _recent_checkout_url(max_age_seconds=120):
    """Retourne l\'URL WhatsApp recente si une commande vient d\'etre creee."""
    url = session.get("last_checkout_url")
    ts = session.get("last_checkout_at")
    if not url or not ts:
        return None
    try:
        last = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    if datetime.utcnow() - last <= timedelta(seconds=max_age_seconds):
        return url
    return None



def get_cart():
    key = _cart_key()
    cart = session.get(key)
    if cart:
        return cart
    if not current_user.is_authenticated:
        # Fallback: rcuprer un panier guest encore prsent en session
        for k, v in session.items():
            if k.startswith("cart_guest_") and isinstance(v, dict) and v:
                return v
        legacy = session.get("cart_guest")
        if isinstance(legacy, dict) and legacy:
            return legacy
    return cart or {}


def set_cart(cart):
    key = _cart_key()
    session[key] = cart
    # Stabiliser le panier guest (evite la perte si token change)
    if not current_user.is_authenticated:
        session["cart_guest"] = cart

def _clear_cart_storage():
    """Supprime toutes les variantes de paniers en session."""
    if current_user.is_authenticated:
        session.pop(_cart_key(), None)
        return
    for key in list(session.keys()):
        if key.startswith("cart_guest_") or key == "cart_guest":
            session.pop(key, None)

@bp.before_request
def setup_guest():
    """Initialise la session guest si non connect"""
    if not current_user.is_authenticated:
        GuestSessionManager.get_or_create_guest_token()


# =====================================================
# FONCTIONS UTILITAIRES
# =====================================================
def calculate_cart_total(cart_dict=None):
    """Calculer le total du panier"""
    if cart_dict is None:
        cart_dict = get_cart()
    
    total = 0
    product_map = _cart_product_map(cart_dict)
    promo_map = _active_promo_map(list(product_map.keys()))
    for pid_str, qty in cart_dict.items():
        try:
            pid = int(pid_str)
            product = product_map.get(pid)
            if product and not _is_service_product(product):
                total += qty * prix_final(product, promo_map.get(pid))
        except (ValueError, AttributeError):
            continue
    return total


def get_cart_summary():
    """Obtenir un rsum du panier pour API"""
    cart = get_cart()
    items = []
    total = 0
    product_map = _cart_product_map(cart)
    promo_map = _active_promo_map(list(product_map.keys()))
    
    for pid_str, qty in cart.items():
        try:
            pid = int(pid_str)
            product = product_map.get(pid)
            if product and not _is_service_product(product):
                final_price = prix_final(product, promo_map.get(pid))
                item_total = qty * final_price
                total += item_total
                items.append({
                    'id': product.id,
                    'name': product.name,
                    'quantity': qty,
                    'price': final_price,
                    'item_total': item_total,
                    'stock': getattr(product, 'stock', None)
                })
        except (ValueError, AttributeError):
            continue
    
    return {
        'items': items,
        'total': total,
        'count': sum(i.get("quantity", 0) for i in items)
    }


def _has_active_tracking() -> bool:
    lookup_filters = []

    if current_user.is_authenticated:
        lookup_filters.append(Order.buyer_id == current_user.id)

    cookie_digits = read_phone_cookie_digits()
    if cookie_digits:
        _normalized_cookie, _digits_cookie, cookie_candidates = _phone_candidates(cookie_digits)
        cookie_matchers = [Order.phone_digits == cookie_digits]
        if cookie_candidates:
            cookie_matchers.append(Order.phone.in_(cookie_candidates))
        lookup_filters.append(or_(*cookie_matchers))

    tracked_phone = (session.get("track_phone_raw") or session.get("track_phone") or "").strip()
    if tracked_phone:
        _normalized, digits, candidates = _phone_candidates(tracked_phone)
        phone_matchers = []
        if digits:
            phone_matchers.append(Order.phone_digits == digits)
        if candidates:
            phone_matchers.append(Order.phone.in_(candidates))
        if phone_matchers:
            lookup_filters.append(or_(*phone_matchers))

    if not lookup_filters:
        return False

    active_delivery_statuses = ("new", "assigned", "picked_up", "delivering")
    active_order_statuses = ("new", "pending", "confirmed", "paid", "processing", "shipping", "shipped")
    cutoff = datetime.utcnow() - timedelta(days=45)

    query = (
        Order.query
        .with_entities(Order.id)
        .filter(or_(*lookup_filters))
        .filter(Order.created_at >= cutoff)
        .filter(
            or_(
                Order.delivery_status.in_(active_delivery_statuses),
                and_(
                    Order.delivery_status.is_(None),
                    Order.status.in_(active_order_statuses),
                ),
            )
        )
        .order_by(Order.created_at.desc())
    )
    return query.first() is not None




def compute_shipping_by_city(city: str) -> int:
    return pricing_shipping_by_city(city)
# =====================================================
# VUE PANIER
# =====================================================
@bp.route("/")
def view():
    cart = get_cart()
    items, total_cents = [], 0
    missing = False
    product_map = _cart_product_map(cart)
    promo_map = _active_promo_map(list(product_map.keys()))

    removed_services = _remove_service_items_from_cart(cart, product_map)
    if removed_services:
        set_cart(cart)
        flash("Les services se rservent et ne peuvent pas tre ajouts au panier.", "info")

    for pid_str, qty in cart.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue

        product = product_map.get(pid)
        if not product:
            missing = True
            continue

        if _is_service_product(product):
            continue

        #  Produits uniquement
        price_cents = int(prix_final(product, promo_map.get(pid)) * 100)

        subtotal = price_cents * qty
        total_cents += subtotal
        items.append((product, qty, subtotal / 100))

    if missing:
        flash("Certains produits ont t retirs du panier.", "warning")

    return render_template(
        "cart/cart.html", 
        items=items, 
        total=total_cents / 100,
        prix_final=prix_final  #  AJOUT IMPORTANT !
    )


# =====================================================
# AJOUT / SUPPRESSION (Anciennes routes - compatibilit)
# =====================================================
@bp.route("/add/<int:pid>", methods=["POST"])
def add(pid):
    product = Product.query.get_or_404(pid)
    cart = get_cart()

    if _is_service_product(product):
        flash("Ce service se rserve. Merci de passer par la rservation.", "info")
        return redirect(url_for("booking.book", pid=product.id))

    shop_msg = _shop_open_message(product)
    if shop_msg:
        flash(shop_msg, "info")
        return redirect(request.referrer or url_for("shop.product_detail", pid=product.id))

    qty = cart.get(str(pid), 0)
    if hasattr(product, 'stock') and product.stock <= qty:
        flash("Stock insuffisant", "warning")
        return redirect(request.referrer or url_for("shop.home"))

    cart[str(pid)] = qty + 1
    set_cart(cart)

    flash("Produit ajout au panier", "success")
    return redirect(request.referrer or url_for("shop.home"))


@bp.route("/remove/<int:pid>", methods=["POST"])
def remove(pid):
    cart = get_cart()
    cart.pop(str(pid), None)
    set_cart(cart)

    flash("Produit retir du panier", "info")
    return redirect(url_for("cart.view"))


# =====================================================
# GESTION QUANTIT (Anciennes routes - compatibilit)
# =====================================================
@bp.route("/increase/<int:pid>", methods=["POST"])
def increase(pid):
    cart = get_cart()
    pid_str = str(pid)

    if pid_str in cart:
        product = Product.query.get(pid)
        if product and _is_service_product(product):
            cart.pop(pid_str, None)
            set_cart(cart)
            flash("Ce service se rserve et ne peut pas tre ajout au panier.", "info")
            return redirect(url_for("booking.book", pid=product.id))
        if product:
            shop_msg = _shop_open_message(product)
            if shop_msg:
                flash(shop_msg, "info")
                return redirect(request.referrer or url_for("shop.product_detail", pid=product.id))
        if product and hasattr(product, 'stock') and product.stock <= cart[pid_str]:
            flash("Stock insuffisant", "warning")
        else:
            cart[pid_str] += 1
    else:
        product = Product.query.get(pid)
        if product and _is_service_product(product):
            flash("Ce service se rserve et ne peut pas tre ajout au panier.", "info")
            return redirect(url_for("booking.book", pid=product.id))
        if product:
            shop_msg = _shop_open_message(product)
            if shop_msg:
                flash(shop_msg, "info")
                return redirect(request.referrer or url_for("shop.product_detail", pid=product.id))
        cart[pid_str] = 1

    set_cart(cart)
    return redirect(url_for("cart.view"))


@bp.route("/decrease/<int:pid>", methods=["POST"])
def decrease(pid):
    cart = get_cart()
    pid_str = str(pid)

    if pid_str in cart:
        if cart[pid_str] > 1:
            cart[pid_str] -= 1
        else:
            del cart[pid_str]
            flash("Produit retir du panier", "info")

    set_cart(cart)
    return redirect(url_for("cart.view"))


@bp.route("/update_qty/<int:pid>", methods=["POST"])
def update_qty(pid):
    new_qty = request.form.get("quantity", type=int)

    if new_qty and new_qty > 0:
        cart = get_cart()
        product = Product.query.get(pid)
        if product and _is_service_product(product):
            cart.pop(str(pid), None)
            set_cart(cart)
            flash("Ce service se rserve et ne peut pas tre ajout au panier.", "info")
            return redirect(url_for("booking.book", pid=product.id))
        if product:
            shop_msg = _shop_open_message(product)
            if shop_msg:
                flash(shop_msg, "info")
                return redirect(request.referrer or url_for("shop.product_detail", pid=product.id))
            if hasattr(product, "stock") and product.stock < new_qty:
                flash("Stock insuffisant", "warning")
                return redirect(request.referrer or url_for("cart.view"))
        cart[str(pid)] = new_qty
        set_cart(cart)
        flash("Quantit mise  jour", "success")
    else:
        flash("Quantit invalide", "danger")

    return redirect(url_for("cart.view"))


# =====================================================
# NOUVELLES ROUTES AJAX
# =====================================================

@bp.route("/api/add/<int:pid>", methods=["POST"])
def add_ajax(pid):
    """Ajouter un produit via AJAX"""
    product = Product.query.get_or_404(pid)
    cart = get_cart()
    pid_str = str(pid)

    if _is_service_product(product):
        return jsonify({
            'success': False,
            'message': 'Ce service se rserve. Merci de passer par la rservation.',
            'redirect_url': url_for('booking.book', pid=product.id)
        })

    shop_msg = _shop_open_message(product)
    if shop_msg:
        return jsonify({'success': False, 'message': shop_msg})
     
    qty = cart.get(pid_str, 0)
    if hasattr(product, 'stock') and product.stock <= qty:
        return jsonify({
            'success': False,
            'message': 'Stock insuffisant',
            'stock': product.stock
        })
    
    cart[pid_str] = qty + 1
    set_cart(cart)
    
    # Calculer le nouveau total
    summary = get_cart_summary()
    
    return jsonify({
        'success': True,
        'message': 'Produit ajout au panier',
        'cart_count': summary['count'],
        'product_qty': cart[pid_str],
        'total': summary['total']
    })


@bp.route("/api/remove/<int:pid>", methods=["POST"])
def remove_ajax(pid):
    """Supprimer un produit via AJAX"""
    cart = get_cart()
    pid_str = str(pid)
    
    if pid_str in cart:
        del cart[pid_str]
        set_cart(cart)
    
    summary = get_cart_summary()
    
    return jsonify({
        'success': True,
        'message': 'Produit retir du panier',
        'cart_count': summary['count'],
        'total': summary['total'],
        'product_id': pid
    })


@bp.route("/api/update/<int:pid>", methods=["POST"])
def update_qty_ajax(pid):
    """Mettre  jour la quantit via AJAX"""
    data = request.get_json()
    new_qty = data.get('quantity', 1)
    
    if not new_qty or new_qty < 0:
        return jsonify({'success': False, 'message': 'Quantit invalide'})
    
    product = Product.query.get(pid)
    if not product:
        return jsonify({'success': False, 'message': 'Produit non trouv'})

    if _is_service_product(product):
        cart = get_cart()
        pid_str = str(pid)
        if pid_str in cart:
            del cart[pid_str]
            set_cart(cart)
        summary = get_cart_summary()
        return jsonify({
            'success': True,
            'message': "Ce service se rserve et a t retir du panier",
            'product_qty': 0,
            'product_total': 0,
            'total': summary['total'],
            'cart_count': summary['count']
        })

    shop_msg = _shop_open_message(product)
    if shop_msg:
        return jsonify({'success': False, 'message': shop_msg})
     
    if hasattr(product, 'stock') and product.stock < new_qty:
        return jsonify({
            'success': False,
            'message': f'Stock insuffisant. Disponible: {product.stock}',
            'stock': product.stock
        })
    
    cart = get_cart()
    pid_str = str(pid)
    
    if new_qty == 0:
        # Supprimer le produit
        if pid_str in cart:
            del cart[pid_str]
    else:
        # Mettre  jour la quantit
        cart[pid_str] = new_qty
    
    set_cart(cart)
    
    # Recalculer
    product_total = new_qty * prix_final(product) if new_qty > 0 else 0
    summary = get_cart_summary()
    
    return jsonify({
        'success': True,
        'message': 'Quantit mise  jour',
        'product_qty': new_qty if new_qty > 0 else 0,
        'product_total': product_total,
        'total': summary['total'],
        'cart_count': summary['count']
    })


@bp.route("/api/clear", methods=["POST"])
def clear_ajax():
    """Vider le panier via AJAX"""
    _clear_cart_storage()
    
    return jsonify({
        'success': True,
        'message': 'Panier vid',
        'cart_count': 0,
        'total': 0
    })


@bp.route("/api/summary")
def cart_summary():
    """Obtenir le rsum du panier via AJAX"""
    summary = get_cart_summary()
    return jsonify(summary)


@bp.route("/api/nav-status")
def nav_status():
    summary = get_cart_summary()
    track_active = False
    try:
        track_active = _has_active_tracking()
    except Exception:
        current_app.logger.exception("nav_status_error")

    response = jsonify({
        "cart_count": int(summary.get("count", 0) or 0),
        "track_active": bool(track_active),
    })
    response.headers["Cache-Control"] = "no-store"
    return response


# =====================================================
# CHECKOUT
# =====================================================
@bp.route("/checkout", methods=["GET", "POST"])
@rate_limit(limit=20, window_seconds=300, key_prefix="checkout", methods=("POST",))
def checkout():
    cart = get_cart()
    product_map = _cart_product_map(cart)
    promo_map = _active_promo_map(list(product_map.keys()))

    removed_services = _remove_service_items_from_cart(cart, product_map)
    if removed_services:
        set_cart(cart)
        flash("Les services se rservent et ont t retirs du panier.", "info")

    if not cart:
        if _is_ajax_request():
            recent_url = _recent_checkout_url()
            if recent_url:
                return jsonify({"success": True, "wa_url": recent_url, "reused": True})
            return jsonify({"success": False, "message": "Panier vide"}), 400
        recent_url = _recent_checkout_url()
        if recent_url:
            return redirect(recent_url)
        flash("Panier vide", "warning")
        return redirect(url_for("shop.home"))

    items = []
    subtotal_cents = 0

    for pid_str, qty in cart.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue

        product = product_map.get(pid)
        if not product:
            return _ajax_error("Produit supprime", status=404, flash_category="danger", redirect_endpoint="cart.view")

        shop_msg = _shop_open_message(product)
        if shop_msg:
            return _ajax_error(shop_msg, status=409, flash_category="info", redirect_endpoint="cart.view")

        if hasattr(product, "stock") and product.stock < qty:
            return _ajax_error(f"Stock insuffisant pour {product.name}", status=409, flash_category="danger", redirect_endpoint="cart.view")

        price_cents = int(prix_final(product, promo_map.get(pid)) * 100)
        subtotal_cents += price_cents * qty
        items.append((product, qty, price_cents))

    #  IMPORTANT
    #  On NE calcule PLUS la livraison ici
    #  Pas de compute_shipping()
    shipping_preview = 0
    total_preview = subtotal_cents

    # POST => traiter directement (vite les pertes de session entre redirections)
    if request.method == "POST":
        return whatsapp_checkout()

    # Pr-remplir tlphone si dj mmoris
    remembered_phone = (session.get("track_phone") or "").strip() or read_phone_cookie_digits()

    return render_template(
        "cart/checkout.html",
        items=[(p, q, (pc * q) / 100) for p, q, pc in items],
        subtotal=subtotal_cents / 100,
        shipping=shipping_preview / 100,  # affich = 0.00 MAD
        total=total_preview / 100,
        cities=Order.CITIES,
        remembered_phone=remembered_phone,
        prix_final=prix_final
    )




@bp.route("/shipping/<city>")
def ajax_shipping(city):
    shipping_cents = pricing_shipping_by_city(city)

    return {
        "shipping": shipping_cents / 100
    }


@bp.route("/whatsapp", methods=["POST"])
@rate_limit(limit=15, window_seconds=300, key_prefix="whatsapp", methods=("POST",))
def whatsapp_checkout():
    """
    - cre commande en DB
    - mmorise le numro
    - redirige vers WhatsApp
    """
    cart = get_cart()
    product_map = _cart_product_map(cart)
    removed_services = _remove_service_items_from_cart(cart, product_map)
    if removed_services:
        set_cart(cart)
        flash("Les services se rservent : ils ont t retirs du panier.", "info")

    if not cart:
        recent_url = _recent_checkout_url()
        if recent_url:
            if _is_ajax_request():
                return jsonify({"success": True, "wa_url": recent_url, "reused": True})
            return redirect(recent_url)
        msg = "Panier vide"
        if removed_services:
            msg = "Votre panier contenait uniquement des services. Merci de les rserver."
        current_app.logger.warning(
            "checkout_post_rejected reason=empty_cart ajax=%s user_id=%s",
            _is_ajax_request(),
            current_user.id if current_user.is_authenticated else None,
        )
        return _ajax_error(msg, status=400, flash_category="warning", redirect_endpoint="shop.home")

    full_name = (request.form.get("full_name") or "").strip()
    phone_raw = (request.form.get("phone") or "").strip()
    city_input = (request.form.get("city") or "").strip()
    city = canonical_city_name(city_input, Order.CITIES) or city_input
    address = (request.form.get("address") or "").strip()
    location_link = (request.form.get("location_link") or "").strip()
    location_lat = (request.form.get("location_lat") or "").strip()
    location_lng = (request.form.get("location_lng") or "").strip()

    current_app.logger.info(
        "checkout_post_start user_id=%s ajax=%s city_input=%s has_location=%s",
        current_user.id if current_user.is_authenticated else None,
        _is_ajax_request(),
        city_input,
        bool(location_link or location_lat or location_lng),
    )

    phone = normalize_phone(phone_raw)
    if not full_name or not phone or not city or not address:
        current_app.logger.warning(
            "checkout_post_rejected reason=missing_fields user_id=%s city=%s",
            current_user.id if current_user.is_authenticated else None,
            city,
        )
        return _ajax_error("Veuillez remplir toutes les informations de livraison.", status=400, flash_category="danger", redirect_endpoint="cart.checkout")

    if len(_digits_only(phone)) < 6:
        current_app.logger.warning(
            "checkout_post_rejected reason=invalid_phone user_id=%s city=%s",
            current_user.id if current_user.is_authenticated else None,
            city,
        )
        return _ajax_error("Numero de telephone invalide.", status=400, flash_category="danger", redirect_endpoint="cart.checkout")

    if city not in Order.CITIES:
        current_app.logger.warning(
            "checkout_post_rejected reason=invalid_city user_id=%s city=%s",
            current_user.id if current_user.is_authenticated else None,
            city,
        )
        return _ajax_error("Ville invalide", status=400, flash_category="danger", redirect_endpoint="cart.checkout")

    phone_digits = _digits_only(phone)
    client_ip = _client_ip()

    blocked_phone = None
    blocked_ip = None
    if phone_digits:
        blocked_phone = BlockedContact.query.filter_by(kind="phone", value=phone_digits, is_active=True).first()
    if client_ip:
        blocked_ip = BlockedContact.query.filter_by(kind="ip", value=client_ip, is_active=True).first()

    if blocked_phone or blocked_ip:
        current_app.logger.warning(
            "checkout_post_rejected reason=blocked_contact user_id=%s city=%s",
            current_user.id if current_user.is_authenticated else None,
            city,
        )
        return _ajax_error("Commande bloquee. Contactez le support.", status=403, flash_category="danger", redirect_endpoint="cart.checkout")

    lat_val = _safe_float(location_lat)
    lng_val = _safe_float(location_lng)
    map_link = make_maps_url(lat=lat_val, lng=lng_val, address=address, city=city)
    if not map_link and location_link:
        map_link = location_link[:300]

    items = []
    subtotal_cents = 0
    product_map = _cart_product_map(cart)
    promo_map = _active_promo_map(list(product_map.keys()))

    for pid_str, qty in cart.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue

        product = product_map.get(pid)
        if not product:
            continue

        shop_msg = _shop_open_message(product)
        if shop_msg:
            return _ajax_error(shop_msg, status=409, flash_category="info", redirect_endpoint="cart.view")

        if hasattr(product, "stock") and product.stock < qty:
            return _ajax_error(f"Stock insuffisant pour {product.name}", status=409, flash_category="danger", redirect_endpoint="cart.view")

        price_cents = int(prix_final(product, promo_map.get(pid)) * 100)
        subtotal_cents += price_cents * qty
        items.append((product, qty, price_cents))

    vendor_totals = {}
    for product, qty, price_cents in items:
        if not product or not product.vendor_id:
            continue
        key = (product.vendor_id, product.shop_id)
        vendor_totals[key] = vendor_totals.get(key, 0) + (price_cents * qty)

    if not items:
        return _ajax_error("Panier vide", status=400, flash_category="warning", redirect_endpoint="shop.home")

    # Delivery economics (frozen at order creation).
    settings = PlatformSettings.get()
    delivery_price_cents = get_delivery_price_cents(city, settings=settings)
    delivery_platform_fee_cents = get_delivery_platform_fee_cents(settings=settings)
    delivery_courier_net_cents = get_delivery_courier_net_cents(
        delivery_price_cents,
        settings=settings,
    )
    shipping_cents = delivery_price_cents

    current_app.logger.info(
        "checkout_post_pricing user_id=%s city=%s delivery_price_cents=%s delivery_platform_fee_cents=%s",
        current_user.id if current_user.is_authenticated else None,
        city,
        delivery_price_cents,
        delivery_platform_fee_cents,
    )

    # Seller commission is fully disabled for product/service orders.
    commission_cents = 0
    vendor_net_cents = subtotal_cents

    #  TOTAL FINAL
    total_cents = subtotal_cents + shipping_cents

    #  crer commande
    # Num?ro WhatsApp de livraison requis
    number = _delivery_whatsapp_number()
    if not number:
        return _ajax_error("Numero WhatsApp de livraison non configure.", status=500, flash_category="danger", redirect_endpoint="cart.checkout")

    # ? cr?er commande (transaction)
    token = secrets.token_urlsafe(16)
    guest_token = None
    if not current_user.is_authenticated:
        guest_token = secrets.token_urlsafe(16)

    try:
        from ..services.order_periods import get_or_create_open_order_period

        active_period, _created = get_or_create_open_order_period(
            created_by=current_user.id if current_user.is_authenticated else None
        )
    except Exception:
        current_app.logger.exception("Echec affectation periode commande")
        return _ajax_error(
            "Creation commande impossible: aucune periode ouverte disponible.",
            status=503,
            flash_category="danger",
            redirect_endpoint="cart.checkout",
        )

    order = None
    try:
        # Commit metier autonome: la commande doit exister meme si l'audit echoue.
        order = Order(
            token=token,
            full_name=full_name,
            phone=phone,
            phone_digits=phone_digits,
            customer_name=full_name,
            customer_phone=phone,
            order_ip=client_ip,
            city=city,
            address=address,
            delivery_source=DELIVERY_SOURCE_MARKETPLACE,
            delivery_city=city,
            delivery_address=address,
            delivery_lat=lat_val,
            delivery_lng=lng_val,
            delivery_maps_url=map_link or None,
            total=total_cents,
            shipping=shipping_cents,
            delivery_price_cents=delivery_price_cents,
            delivery_platform_fee_cents=delivery_platform_fee_cents,
            delivery_courier_net_cents=delivery_courier_net_cents,
            commission=commission_cents,
            vendor_net=vendor_net_cents,
            status="pending",
            period_id=active_period.id,
            buyer_id=current_user.id if current_user.is_authenticated else None,
            guest_token=guest_token
        )

        db.session.add(order)
        db.session.flush()

        for product, qty, price_cents in items:
            db.session.add(OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                price=price_cents
            ))

            if hasattr(product, "stock") and product.stock is not None:
                result = db.session.execute(
                    update(Product)
                    .where(Product.id == product.id)
                    .where(Product.stock >= qty)
                    .values(stock=Product.stock - qty)
                )
                if result.rowcount == 0:
                    raise ValueError("stock_insufficient")

        for (vendor_id, shop_id), subtotal in vendor_totals.items():
            comm = 0
            amount = max(0, subtotal - comm)
            db.session.add(VendorPayout(
                order_id=order.id,
                vendor_id=vendor_id,
                shop_id=shop_id,
                subtotal_cents=subtotal,
                commission_cents=comm,
                amount_cents=amount,
                status="pending"
            ))

        db.session.commit()
        try:
            from ..services.traffic_stats import track_order_created

            track_order_created()
        except Exception:
            pass
    except ValueError:
        db.session.rollback()
        return _ajax_error("Stock insuffisant. Merci de verifier votre panier.", status=409, flash_category="danger", redirect_endpoint="cart.view")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Erreur checkout")
        return _ajax_error("Erreur serveur. Merci de reessayer.", status=500, flash_category="danger", redirect_endpoint="cart.checkout")


    if guest_token:
        GuestSessionManager.remember_order_token(guest_token)

    # Audit creation commande (best effort, sans impacter la commande deja commit).
    from ..services.audit import log_access
    try:
        log_access(
            "create_order",
            "order",
            order.id,
            success=True,
            changes={
                "total_cents": order.total,
                "city": order.city,
                "items_count": len(items)
            }
        )
    except Exception:
        current_app.logger.exception("Audit create_order failed", extra={"order_id": order.id})

    # mmoriser tlphone
    session["track_phone"] = phone
    session["track_phone_raw"] = phone


    message = build_whatsapp_order_message(order, map_link=map_link)
    wa_url = f"https://wa.me/{number}?text={quote(message)}"

    # garder un lien de secours (anti double-submit)
    session["last_checkout_url"] = wa_url
    session["last_checkout_at"] = datetime.utcnow().isoformat()

    # vider panier
    _clear_cart_storage()

    if _is_ajax_request():
        response = jsonify({"success": True, "wa_url": wa_url})
        return set_phone_cookie(response, phone_digits)

    # Redirection directe vers WhatsApp
    response = redirect(wa_url)
    return set_phone_cookie(response, phone_digits)



# =====================================================
# SUIVI PAR TOKEN (inchang)
# =====================================================
@bp.route("/track/<token>", methods=["GET", "POST"])
def track(token):
    order = Order.query.filter_by(token=token).first_or_404()

    # Audit consultation commande (token) avec anti-spam
    from ..services.audit import log_view_order
    log_view_order(order.id, source="track_token")

    is_admin = bool(current_user.is_authenticated and current_user.role == "admin")
    matched_cookie = False
    matched_input = False

    # Commande liee a un compte: verifier cookie signe ou saisie telephone (pas de login requis)
    if order.buyer_id and not is_admin:
        matched_cookie = cookie_matches_order_phone(order)
        if not matched_cookie and request.method == "POST":
            phone_input = (request.form.get("phone") or "").strip()
            matched_input = input_matches_order_phone(order, phone_input)
            if not matched_input:
                flash("Numero incorrect. Entrez votre numero ou les 4 derniers chiffres.", "danger")

        if not matched_cookie and not matched_input:
            return render_template("cart/track_verify_phone.html", order=order), 403

    current_delivery_status = (order.delivery_status or "").strip().lower()
    if not current_delivery_status:
        order_status = (order.status or "").strip().lower()
        if order_status == "delivered":
            current_delivery_status = "delivered"
        elif order_status in {"cancelled", "canceled"}:
            current_delivery_status = "canceled"
        elif order_status in {"shipping", "shipped"}:
            current_delivery_status = "delivering"
        else:
            current_delivery_status = "new"

    # Expiration apres livraison 72h
    if current_delivery_status == "delivered" and order.delivered_at:
        if datetime.utcnow() > order.delivered_at + timedelta(hours=72):
            flash("Commande expiree", "info")
            return redirect(url_for("shop.home"))

    # Calcul cote Python (remplace moment.utcnow() dans le template)
    elapsed_hours = None
    if order.delivered_at:
        elapsed_hours = (datetime.utcnow() - order.delivered_at).total_seconds() / 3600

    lang = normalize_lang(session.get("lang") or getattr(g, "lang", None))
    status_labels = delivery_status_labels_for_lang(lang)
    response = make_response(
        render_template(
            "shop/track_order.html",
            order=order,
            elapsed_hours=elapsed_hours,
            current_delivery_status=current_delivery_status,
            delivery_status_label=label_delivery_status(current_delivery_status, lang),
            order_status_label=label_order_status(order.status, lang),
            source_label=label_source(order.delivery_source, lang),
            status_labels=status_labels,
        )
    )
    if order.buyer_id and not is_admin and (matched_cookie or matched_input):
        order_digits = get_order_phone_digits(order)
        if order_digits:
            response = set_phone_cookie(response, order_digits)
            remembered_phone = (order.phone or order_digits).strip()
            session["track_phone"] = remembered_phone
            session["track_phone_raw"] = remembered_phone
    return response

@bp.route("/track/<token>/status")
def track_status(token):
    order = Order.query.filter_by(token=token).first_or_404()

    # meme securite que /track
    if order.buyer_id:
        is_admin = bool(current_user.is_authenticated and current_user.role == "admin")
        if not is_admin and not cookie_matches_order_phone(order):
            return jsonify({"error": "forbidden"}), 403
    else:
        if not GuestSessionManager.can_access_order(order):
            return jsonify({"error": "forbidden"}), 403

    lang = normalize_lang(session.get("lang") or getattr(g, "lang", None))
    delivery_status = (order.delivery_status or "").strip().lower()
    if not delivery_status:
        order_status = (order.status or "").strip().lower()
        if order_status == "delivered":
            delivery_status = "delivered"
        elif order_status in {"cancelled", "canceled"}:
            delivery_status = "canceled"
        elif order_status in {"shipping", "shipped"}:
            delivery_status = "delivering"
        else:
            delivery_status = "new"
    return jsonify({
        "id": order.id,
        "status": order.status,
        "status_label": label_order_status(order.status, lang),
        "delivery_status": delivery_status,
        "delivery_status_label": label_delivery_status(delivery_status, lang),
        "source_label": label_source(order.delivery_source, lang),
        "assigned_at": order.assigned_at.isoformat() if order.assigned_at else None,
        "picked_up_at": order.picked_up_at.isoformat() if order.picked_up_at else None,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "total": order.total,
        "commission": order.commission,
        "delivery_price_cents": order.delivery_price_cents or order.shipping or 0,
        "delivery_platform_fee_cents": order.delivery_platform_fee_cents or 0,
        "delivery_courier_net_cents": order.delivery_courier_net_cents or 0,
        "lang": lang,
    })


# =====================================================
# SUIVI PAR TLPHONE (inchang)
# =====================================================
@bp.route("/suivi", methods=["GET", "POST"])
@rate_limit(limit=15, window_seconds=600, key_prefix="track_phone", methods=("POST",))
def track_by_phone():
    if request.method == "POST":
        phone_raw = (request.form.get("phone") or "").strip()
        country_code = (request.form.get("country_code") or "").strip()
        phone_local = (request.form.get("phone_local") or "").strip()
        custom_code = (request.form.get("custom_country_code") or "").strip()

        if not phone_raw and phone_local:
            code_raw = custom_code if country_code == "custom" else country_code
            code_digits = _digits_only(code_raw)
            code = f"+{code_digits}" if code_digits else ""
            local_digits = _digits_only(phone_local)
            if code_digits and local_digits.startswith(f"00{code_digits}"):
                local_digits = local_digits[len(code_digits) + 2 :]
            elif code_digits and local_digits.startswith(code_digits) and len(local_digits) > (len(code_digits) + 4):
                local_digits = local_digits[len(code_digits) :]
            if code_digits and local_digits.startswith("0"):
                local_digits = local_digits.lstrip("0") or local_digits
            phone_raw = f"{code}{local_digits}" if code else phone_local

        if not phone_raw:
            flash("Veuillez saisir votre numro de tlphone", "warning")
            return redirect(url_for("cart.track_by_phone"))
        normalized, digits, _ = _phone_candidates(phone_raw)
        if not digits or len(digits) < 6:
            flash("Numero de telephone invalide", "danger")
            return redirect(url_for("cart.track_by_phone"))

        session["track_phone"] = normalized or digits or phone_raw
        session["track_phone_raw"] = phone_raw
        response = redirect(url_for("cart.my_orders"))
        return set_phone_cookie(response, digits)

    remembered = (session.get("track_phone_raw") or session.get("track_phone") or "").strip() or read_phone_cookie_digits()
    return render_template("cart/track_phone.html", remembered=remembered)


@bp.route("/mes-commandes")
def my_orders():
    cookie_digits = read_phone_cookie_digits()
    if cookie_digits:
        _, _, cookie_candidates = _phone_candidates(cookie_digits)
        cookie_filters = [Order.phone_digits == cookie_digits]
        if cookie_candidates:
            cookie_filters.append(Order.phone.in_(cookie_candidates))
        orders = (
            Order.query
            .filter(or_(*cookie_filters))
            .order_by(Order.created_at.desc())
            .all()
        )
        display_phone = f"***{cookie_digits[-4:]}" if len(cookie_digits) >= 4 else "***"
        response = make_response(render_template("cart/my_orders.html", orders=orders, phone=display_phone))
        return set_phone_cookie(response, cookie_digits)

    phone_raw = (session.get("track_phone_raw") or session.get("track_phone") or "").strip()
    if not phone_raw:
        return redirect(url_for("cart.track_by_phone"))

    _, digits, candidates = _phone_candidates(phone_raw)
    query = Order.query

    filters = []
    if digits:
        filters.append(Order.phone_digits == digits)
    if candidates:
        filters.append(Order.phone.in_(candidates))

    if filters:
        query = query.filter(or_(*filters))
    else:
        query = query.filter_by(phone=phone_raw)

    orders = query.order_by(Order.created_at.desc()).all()
    display_phone = phone_raw
    response = make_response(render_template("cart/my_orders.html", orders=orders, phone=display_phone))
    if digits and len(digits) >= 6:
        response = set_phone_cookie(response, digits)
    return response


# =====================================================
# VIDER PANIER (inchang)
# =====================================================
@bp.route("/clear", methods=["POST"])
def clear():
    _clear_cart_storage()
    flash("Panier vid", "info")
    return redirect(url_for("cart.view"))
