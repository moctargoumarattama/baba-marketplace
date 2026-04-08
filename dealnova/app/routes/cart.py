import secrets
import re
import time
from datetime import datetime, timedelta
from functools import lru_cache
from collections import OrderedDict
# app/routes/cart.py - LIGNE 15
from ..models.platform_settings import PlatformSettings
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app, jsonify, make_response, g
from flask_login import current_user
from urllib.parse import quote

from ..extensions import db
from sqlalchemy import and_, or_, update, exists
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import load_only, selectinload
from ..models.category import Category
from ..models.product import Product
from ..models.order import Order, OrderItem
from ..models.blocked import BlockedContact
from ..models.shop import Shop
from ..models.vendor_payout import VendorPayout
from ..services.pricing import (
    cents_to_money,
    final_price_cents,
    get_active_promos_for_products,
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

# =====================================================
# CACHE LRU (OPTIMISÉ - ÉVITE CROISSANCE MÉMOIRE)
# =====================================================
class LRUCache:
    """Cache LRU simple avec TTL"""
    def __init__(self, capacity=100, ttl=30):
        self.cache = OrderedDict()
        self.timestamps = {}
        self.capacity = capacity
        self.ttl = ttl
    
    def get(self, key):
        if key in self.cache:
            if time.time() - self.timestamps[key] < self.ttl:
                self.cache.move_to_end(key)
                return self.cache[key]
            else:
                del self.cache[key]
                del self.timestamps[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = time.time()
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

_cart_cache = LRUCache(capacity=100, ttl=30)


def _get_cached_cart_data(cart_dict, include_shop=False, include_category=False):
    """Récupère produits et promos avec cache LRU"""
    if not cart_dict:
        return {}, {}
    
    # Créer une clé de cache basée sur les IDs du panier
    product_ids = tuple(sorted(int(k) for k in cart_dict.keys() if str(k).isdigit()))
    if not product_ids:
        return {}, {}
    cache_key = (
        product_ids,
        bool(include_shop),
        bool(include_category),
    )
    
    # Vérifier le cache
    cached = _cart_cache.get(cache_key)
    if cached is not None:
        return cached
    
    # Charger les produits
    product_map = _cart_product_map(
        cart_dict,
        include_shop=include_shop,
        include_category=include_category,
    )
    promo_map = _active_promo_map(list(product_map.keys()))
    
    # Sauvegarder dans le cache
    _cart_cache.set(cache_key, (product_map, promo_map))
    
    return product_map, promo_map


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
    """Retourne un message si la boutique du produit est ferme/désactiver, sinon None."""
    shop = getattr(product, "shop", None)
    if not shop:
        return None

    if getattr(shop, "is_active", True) is False:
        return "Cette boutique est temporairement indisponible."

    now = datetime.utcnow()
    closed_until = getattr(shop, "closed_until", None)
    if closed_until and closed_until > now:
        return f"Boutique fermé jusqu'au {closed_until.strftime('%d/%m/%Y %H:%M')}."

    if getattr(shop, "is_open", True) is False:
        return "Cette boutique est actuellement fermé."

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
    """Construit le message WhatsApp d'une commande."""

    def section(title: str, rows: list[str]) -> str:
        return f"*-- {title} --*\n" + "\n".join(rows)

    def mad(cents: int) -> str:
        return f"{cents / 100:.2f} MAD"

    # ── Données de base ──────────────────────────────────────────────────────
    shipping_cents = order.shipping or 0
    subtotal_cents = max(0, (order.total or 0) - shipping_cents)
    site_name      = current_app.config.get("SITE_NAME", "Baba Market Place")
    track_url      = f"{request.host_url.rstrip('/')}/cart/track/{order.token}"

    # ── Groupement par boutique ───────────────────────────────────────────────
    shop_groups: dict = {}
    for it in order.items:
        shop = getattr(it.product, "shop", None)
        key  = f"shop:{shop.id}" if (shop and shop.id) else f"product:{it.product.id}"
        name = (shop.name if shop else None) or "Boutique inconnue"
        shop_groups.setdefault(key, {"name": name, "shop": shop, "items": []})["items"].append(it)

    # ── Section articles ──────────────────────────────────────────────────────
    article_rows = []
    for group in shop_groups.values():
        shop = group["shop"]
        article_rows.append(f"\n*{group['name']}*")
        if shop:
            if shop.contact_phone: article_rows.append(f"  Tel     : {shop.contact_phone}")
            if shop.address:       article_rows.append(f"  Adresse : {shop.address}")
        for it in group["items"]:
            article_rows.append(f"  - {it.quantity} x {it.product.name}  ({mad(it.price * it.quantity)})")

    # ── Section livraison ─────────────────────────────────────────────────────
    delivery_rows = [
        f"  Nom     : {order.full_name}",
        f"  Tel     : {order.phone}",
        f"  Ville   : {order.city}",
        f"  Adresse : {order.address}",
    ]
    gps = (map_link or "").strip() or (getattr(order, "delivery_maps_url", None) or "").strip()
    if gps:
        delivery_rows.append(f"  GPS     : {gps}")

    # ── Assemblage final ──────────────────────────────────────────────────────
    parts = [
        f"*{site_name} — Commande #{order.id}*",
        f"Suivi : {track_url}",
        "",
        section("Articles",  article_rows),
        "",
        section("Livraison", delivery_rows),
        "",
        section("Paiement", [
            f"  Sous-total : {mad(subtotal_cents)}",
            f"  Livraison  : {mad(shipping_cents)}",
            f"  *Total     : {mad(order.total)}*",
        ]),
    ]

    return "\n".join(parts)

# =====================================================
# PANIER GUEST / UTILISATEUR
# =====================================================
def _cart_key(create_guest=True):
    if current_user.is_authenticated:
        return f"cart_user_{current_user.id}"
    # Compat: reutiliser un panier guest existant si present
    if "cart_guest" in session:
        return "cart_guest"
    for key in session.keys():
        if key.startswith("cart_guest_"):
            return key
    if not create_guest:
        return None
    guest_id = GuestSessionManager.get_or_create_guest_token()
    return f"cart_guest_{guest_id}"


def _cart_product_map(cart_dict, include_shop=False, include_category=False):
    """Charge les produits du panier en une seule requete."""
    pids = []
    for pid_str in cart_dict.keys():
        try:
            pids.append(int(pid_str))
        except ValueError:
            continue
    
    # LIMITATION DE SÉCURITÉ
    if len(pids) > 200:
        current_app.logger.warning(f"Panier anormalement grand: {len(pids)} produits")
        pids = pids[:200]
    
    if not pids:
        return {}
    query = Product.query.filter(Product.id.in_(pids))
    if include_shop:
        query = query.options(
            selectinload(Product.shop).load_only(
                Shop.id,
                Shop.name,
                Shop.is_active,
                Shop.is_open,
                Shop.closed_until,
            )
        )
    if include_category:
        query = query.options(
            selectinload(Product.category).load_only(
                Category.id,
                Category.name,
            )
        )
    products = query.all()
    return {p.id: p for p in products}


def _active_promo_map(product_ids: list[int], now: datetime | None = None):
    _ = now
    return get_active_promos_for_products(product_ids)


def _remove_service_items_from_cart(cart_dict, product_map=None):
    """Retire les services du panier (ils doivent passer par la réservation)."""
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
    key = _cart_key(create_guest=False)
    cart = session.get(key) if key else None
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
    key = _cart_key(create_guest=True)
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


# =====================================================
# FONCTIONS UTILITAIRES (OPTIMISÉES)
# =====================================================
def _validate_quantity(qty, allow_zero=True, max_qty=999):
    """Valide une quantité (tolérante)"""
    try:
        qty = int(qty)
        if allow_zero:
            return 0 <= qty <= max_qty
        return 1 <= qty <= max_qty
    except (TypeError, ValueError):
        return False


def calculate_cart_total(cart_dict=None):
    """Calculer le total du panier"""
    if cart_dict is None:
        cart_dict = get_cart()
    
    total_cents = 0
    product_map, promo_map = _get_cached_cart_data(cart_dict)
    for pid_str, qty in cart_dict.items():
        try:
            pid = int(pid_str)
            product = product_map.get(pid)
            if product and not _is_service_product(product):
                total_cents += qty * final_price_cents(product, promo_map.get(pid))
        except (ValueError, AttributeError):
            continue
    return cents_to_money(total_cents)


def _safe_cart_quantity(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def get_cart_summary(cart=None):
    """Obtenir un rsum du panier pour API"""
    if cart is None:
        cart = get_cart()
    if not isinstance(cart, dict):
        cart = {}
    items = []
    total_cents = 0
    product_map, promo_map = _get_cached_cart_data(cart)
    
    for pid_str, raw_qty in cart.items():
        try:
            pid = int(pid_str)
            qty = _safe_cart_quantity(raw_qty)
            if qty <= 0:
                continue
            product = product_map.get(pid)
            if product and not _is_service_product(product):
                item_price_cents = final_price_cents(product, promo_map.get(pid))
                final_price = cents_to_money(item_price_cents)
                item_total_cents = qty * item_price_cents
                total_cents += item_total_cents
                items.append({
                    'id': product.id,
                    'name': product.name,
                    'quantity': qty,
                    'price': final_price,
                    'item_total': cents_to_money(item_total_cents),
                    'stock': getattr(product, 'stock', None)
                })
        except (ValueError, AttributeError):
            continue
    
    return {
        'items': items,
        'total': cents_to_money(total_cents),
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

    return db.session.query(
        exists().where(
            and_(
                or_(*lookup_filters),
                Order.created_at >= cutoff,
                or_(
                    Order.delivery_status.in_(active_delivery_statuses),
                    and_(
                        Order.delivery_status.is_(None),
                        Order.status.in_(active_order_statuses),
                    ),
                )
            )
        )
    ).scalar()


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
    product_map, promo_map = _get_cached_cart_data(cart, include_category=True)

    removed_services = _remove_service_items_from_cart(cart, product_map)
    if removed_services:
        set_cart(cart)
        flash("Les services se réservent. Ils ne vont pas dans le panier.", "info")

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

        # Produits uniquement
        price_cents = final_price_cents(product, promo_map.get(pid))

        subtotal = price_cents * qty
        total_cents += subtotal
        items.append((product, qty, cents_to_money(subtotal)))

    if missing:
        flash("Certains produits ont été retirés du panier.", "warning")

    return render_template(
        "cart/cart.html", 
        items=items, 
        total=total_cents / 100,
        prix_final=prix_final
    )


# =====================================================
# AJOUT / SUPPRESSION (Anciennes routes - compatibilit)
# =====================================================
@bp.route("/add/<int:pid>", methods=["POST"])
def add(pid):
    product = Product.query.get_or_404(pid)
    cart = get_cart()
    is_ajax = _is_ajax_request()
    post_add_redirect = (request.form.get("post_add_redirect") or request.args.get("post_add_redirect") or "").strip().lower()

    if _is_service_product(product):
        message = "Ce service se reserve. Merci de passer par la reservation."
        if is_ajax:
            return jsonify(
                {
                    "success": False,
                    "message": message,
                    "redirect_url": url_for("booking.book", pid=product.id),
                }
            ), 400
        flash(message, "info")
        return redirect(url_for("booking.book", pid=product.id))

    shop_msg = _shop_open_message(product)
    if shop_msg:
        if is_ajax:
            return jsonify({"success": False, "message": shop_msg}), 400
        flash(shop_msg, "info")
        return redirect(request.referrer or url_for("shop.product_detail", pid=product.id))

    qty = cart.get(str(pid), 0)
    if hasattr(product, 'stock') and product.stock <= qty:
        message = "Stock insuffisant."
        if is_ajax:
            return jsonify({"success": False, "message": message}), 400
        flash(message, "warning")
        return redirect(request.referrer or url_for("shop.home"))

    cart[str(pid)] = qty + 1
    set_cart(cart)
    redirect_url = (
        url_for("cart.view")
        if post_add_redirect in ("checkout", "cart", "review")
        else None
    )
    success_message = (
        "Produit ajoute. Verifiez vos articles avant de finaliser."
        if redirect_url
        else "Produit ajoute au panier."
    )

    cart_count = 0
    for value in cart.values():
        try:
            cart_count += max(0, int(value or 0))
        except (TypeError, ValueError):
            continue

    if not is_ajax:
        flash(success_message, "success")
        return redirect(redirect_url or request.referrer or url_for("shop.home"))

    if is_ajax:
        payload = {
            "success": True,
            "message": success_message,
            "cart_count": int(cart_count),
        }
        if redirect_url:
            payload["redirect_url"] = redirect_url
        return jsonify(payload)
        return jsonify(
            {
                "success": True,
                "message": "Produit ajouté au panier.",
                "cart_count": int(cart_count),
            }
        )

    flash("Produit ajouté au panier.", "success")
    return redirect(request.referrer or url_for("shop.home"))


@bp.route("/remove/<int:pid>", methods=["POST"])
def remove(pid):
    cart = get_cart()
    cart.pop(str(pid), None)
    set_cart(cart)

    flash("Produit retiré du panier.", "info")
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
            flash("Ce service se réserve. Il ne peut pas être ajouté au panier.", "info")
            return redirect(url_for("booking.book", pid=product.id))
        if product:
            shop_msg = _shop_open_message(product)
            if shop_msg:
                flash(shop_msg, "info")
                return redirect(request.referrer or url_for("shop.product_detail", pid=product.id))
        if product and hasattr(product, 'stock') and product.stock <= cart[pid_str]:
            flash("Stock insuffisant.", "warning")
        else:
            cart[pid_str] += 1
    else:
        product = Product.query.get(pid)
        if product and _is_service_product(product):
            flash("Ce service se réserve. Il ne peut pas être ajouté au panier.", "info")
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
            flash("Produit retiré du panier.", "info")

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
            flash("Ce service se réserve. Il ne peut pas être ajouté au panier.", "info")
            return redirect(url_for("booking.book", pid=product.id))
        if product:
            shop_msg = _shop_open_message(product)
            if shop_msg:
                flash(shop_msg, "info")
                return redirect(request.referrer or url_for("shop.product_detail", pid=product.id))
            if hasattr(product, "stock") and product.stock < new_qty:
                flash("Stock insuffisant.", "warning")
                return redirect(request.referrer or url_for("cart.view"))
        cart[str(pid)] = new_qty
        set_cart(cart)
        flash("Quantité mise à jour.", "success")
    else:
        flash("Quantité invalide.", "danger")

    return redirect(url_for("cart.view"))


# =====================================================
# NOUVELLES ROUTES AJAX (OPTIMISÉES)
# =====================================================

def log_performance(f):
    """Décorateur pour logger les requêtes lentes (>500ms)"""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = f(*args, **kwargs)
        duration = time.time() - start
        if duration > 0.5:
            current_app.logger.info(f"Slow operation {f.__name__}: {duration:.2f}s")
        return result
    wrapper.__name__ = f.__name__
    return wrapper


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
    
    summary = get_cart_summary(cart)
    
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
    
    summary = get_cart_summary(cart)
    
    return jsonify({
        'success': True,
        'message': 'Produit retir du panier',
        'cart_count': summary['count'],
        'total': summary['total'],
        'product_id': pid
    })


@bp.route("/api/update/<int:pid>", methods=["POST"])
def update_qty_ajax(pid):
    """Mettre à jour la quantité via AJAX (tolérant)"""
    data = request.get_json()
    new_qty = data.get('quantity', 1)
    
    # Validation tolérante : 0 autorisé (pour suppression)
    if not _validate_quantity(new_qty, allow_zero=True, max_qty=999):
        return jsonify({'success': False, 'message': 'Quantité invalide (0-999)'})
    
    product = Product.query.get(pid)
    if not product:
        return jsonify({'success': False, 'message': 'Produit non trouvé'})

    if _is_service_product(product):
        cart = get_cart()
        pid_str = str(pid)
        if pid_str in cart:
            del cart[pid_str]
            set_cart(cart)
        summary = get_cart_summary(cart)
        return jsonify({
            'success': True,
            'message': "Ce service se réserve et a été retiré du panier",
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
        # Mettre à jour la quantité
        cart[pid_str] = new_qty
    
    set_cart(cart)
    
    promo_map = _active_promo_map([pid]) if new_qty > 0 else {}
    product_total = cents_to_money(new_qty * final_price_cents(product, promo_map.get(pid))) if new_qty > 0 else 0
    summary = get_cart_summary(cart)
    
    return jsonify({
        'success': True,
        'message': 'Quantité mise à jour',
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
        'message': 'Panier vidé',
        'cart_count': 0,
        'total': 0
    })


@bp.route("/api/summary")
def cart_summary():
    """Obtenir le résumé du panier via AJAX"""
    summary = get_cart_summary()
    return jsonify(summary)


@bp.route("/api/nav-status")
def nav_status():
    try:
        summary = get_cart_summary()
    except Exception:
        current_app.logger.exception("nav_status_summary_error")
        summary = {"count": 0}
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
    if request.method == "POST":
        return whatsapp_checkout()

    cart = get_cart()
    product_map, promo_map = _get_cached_cart_data(cart, include_shop=True)

    removed_services = _remove_service_items_from_cart(cart, product_map)
    if removed_services:
        set_cart(cart)
        flash("Les services se réservent. Ils ont été retirés du panier.", "info")

    if not cart:
        if _is_ajax_request():
            recent_url = _recent_checkout_url()
            if recent_url:
                return jsonify({"success": True, "wa_url": recent_url, "reused": True})
            return jsonify({"success": False, "message": "Panier vide."}), 400
        recent_url = _recent_checkout_url()
        if recent_url:
            return redirect(recent_url)
        flash("Votre panier est vide.", "warning")
        return redirect(url_for("shop.home"))

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

        price_cents = final_price_cents(product, promo_map.get(pid))
        subtotal_cents += price_cents * qty

    shipping_preview = 0
    total_preview = subtotal_cents

    remembered_phone = (session.get("track_phone") or "").strip() or read_phone_cookie_digits()

    return render_template(
        "cart/checkout.html",
        subtotal=subtotal_cents / 100,
        shipping=shipping_preview / 100,
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
@log_performance
def whatsapp_checkout():
    """
    - crée commande en DB
    - mémorise le numéro
    - redirige vers WhatsApp
    """
    cart = get_cart()
    product_map, promo_map = _get_cached_cart_data(cart, include_shop=True)
    removed_services = _remove_service_items_from_cart(cart, product_map)
    if removed_services:
        set_cart(cart)
        flash("Les services se réservent. Ils ont été retirés du panier.", "info")

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

        price_cents = final_price_cents(product, promo_map.get(pid))
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

    commission_cents = 0
    vendor_net_cents = subtotal_cents
    total_cents = subtotal_cents + shipping_cents

    number = _delivery_whatsapp_number()
    if not number:
        return _ajax_error("Numero WhatsApp de livraison non configure.", status=500, flash_category="danger", redirect_endpoint="cart.checkout")

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
        except Exception as e:
            current_app.logger.warning(f"track_order_created failed (non bloquant): {e}")
    except ValueError:
        db.session.rollback()
        return _ajax_error("Stock insuffisant. Merci de verifier votre panier.", status=409, flash_category="danger", redirect_endpoint="cart.view")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Erreur checkout")
        return _ajax_error("Erreur serveur. Merci de reessayer.", status=500, flash_category="danger", redirect_endpoint="cart.checkout")

    if guest_token:
        GuestSessionManager.remember_order_token(guest_token)

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
    except Exception as e:
        current_app.logger.exception("Audit create_order failed", extra={"order_id": order.id})

    session["track_phone"] = phone
    session["track_phone_raw"] = phone

    message = build_whatsapp_order_message(order, map_link=map_link)
    wa_url = f"https://wa.me/{number}?text={quote(message)}"
    try:
        from ..services.traffic_stats import track_custom_event
        track_custom_event("whatsapp_open")
    except Exception as e:
        current_app.logger.warning(f"track_custom_event whatsapp_open failed (non bloquant): {e}")

    session["last_checkout_url"] = wa_url
    session["last_checkout_at"] = datetime.utcnow().isoformat()

    _clear_cart_storage()

    if _is_ajax_request():
        response = jsonify({"success": True, "wa_url": wa_url})
        return set_phone_cookie(response, phone_digits)

    response = redirect(wa_url)
    return set_phone_cookie(response, phone_digits)


# =====================================================
# SUIVI PAR TOKEN
# =====================================================
@bp.route("/track/<token>", methods=["GET", "POST"])
def track(token):
    order = Order.query.filter_by(token=token).first_or_404()

    from ..services.audit import log_view_order
    log_view_order(order.id, source="track_token")

    is_admin = bool(current_user.is_authenticated and current_user.role == "admin")
    matched_cookie = False
    matched_input = False

    if order.buyer_id and not is_admin:
        matched_cookie = cookie_matches_order_phone(order)
        if not matched_cookie and request.method == "POST":
            phone_input = (request.form.get("phone") or "").strip()
            matched_input = input_matches_order_phone(order, phone_input)
            if not matched_input:
                flash("Numéro incorrect. Entrez votre numéro ou les 4 derniers chiffres.", "danger")

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

    if current_delivery_status == "delivered" and order.delivered_at:
        if datetime.utcnow() > order.delivered_at + timedelta(hours=72):
            flash("Commande expirée.", "info")
            return redirect(url_for("shop.home"))

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
# SUIVI PAR TELEPHONE
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
            flash("Veuillez saisir votre numéro de téléphone.", "warning")
            return redirect(url_for("cart.track_by_phone"))
        normalized, digits, _ = _phone_candidates(phone_raw)
        if not digits or len(digits) < 6:
            flash("Numéro de téléphone invalide.", "danger")
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
# VIDER PANIER
# =====================================================
@bp.route("/clear", methods=["POST"])
def clear():
    _clear_cart_storage()
    flash("Votre panier est vide.", "info")
    return redirect(url_for("cart.view"))


