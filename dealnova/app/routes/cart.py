import json
import re
import time
import hashlib
from datetime import datetime
from collections import OrderedDict
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app, jsonify, make_response
from flask_login import current_user
from urllib.parse import quote

from ..extensions import db
from sqlalchemy.orm import selectinload
from ..models.category import Category
from ..models.product import Product
from ..models.blocked import BlockedContact
from ..models.shop import Shop
from ..models.product_contact_lead import ProductContactLead
from ..services.pricing import (
    cents_to_money,
    final_price_cents,
    get_active_promos_for_products,
    prix_final,
)
from ..services.guest_session import GuestSessionManager
from ..services.vendor_push import notify_product_contact_leads
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
    use_cache = not include_shop and not include_category
    if use_cache:
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
    if use_cache:
        _cart_cache.set(cache_key, (product_map, promo_map))
    
    return product_map, promo_map


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


def normalize_whatsapp_number(raw: str) -> str:
    """Normalise un numero boutique pour wa.me, aligne sur le flux service."""
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


def _format_money(cents: int | float | None) -> str:
    return f"{cents_to_money(int(cents or 0)):.2f} MAD"


def _cart_item_product(item):
    if isinstance(item, dict):
        return item.get("product")
    if isinstance(item, (tuple, list)) and item:
        return item[0]
    return getattr(item, "product", None)


def _cart_item_quantity(item) -> int:
    if isinstance(item, dict):
        value = item.get("quantity", item.get("qty", 0))
    elif isinstance(item, (tuple, list)) and len(item) > 1:
        value = item[1]
    else:
        value = getattr(item, "quantity", getattr(item, "qty", 0))
    return _safe_cart_quantity(value)


def _cart_item_unit_price_cents(item) -> int:
    if isinstance(item, dict):
        value = item.get("unit_price_cents", item.get("price_cents", item.get("price", 0)))
    elif isinstance(item, (tuple, list)) and len(item) > 2:
        value = item[2]
    else:
        value = getattr(item, "unit_price_cents", getattr(item, "price_cents", getattr(item, "price", 0)))
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _cart_item_line_total_cents(item) -> int:
    if isinstance(item, dict) and item.get("line_total_cents") is not None:
        try:
            return max(0, int(item.get("line_total_cents") or 0))
        except (TypeError, ValueError):
            return 0
    return _cart_item_unit_price_cents(item) * _cart_item_quantity(item)


def _shop_group_key(shop, product):
    shop_id = getattr(shop, "id", None)
    if shop_id is not None:
        return ("shop", shop_id)
    product_id = getattr(product, "id", id(product))
    return ("missing_shop", product_id)


def _shop_display_name(shop) -> str:
    return (getattr(shop, "name", None) or "Boutique indisponible").strip()


def _shop_phone_raw(shop) -> str:
    if not shop:
        return ""
    return (
        (getattr(shop, "contact_phone", None) or "").strip()
        or (getattr(shop, "phone", None) or "").strip()
    )


def group_cart_items_by_shop(cart_items):
    """Regroupe les articles physiques par boutique, en conservant l'ordre du panier."""
    groups_by_key = OrderedDict()
    for item in cart_items or []:
        product = _cart_item_product(item)
        if not product:
            continue
        shop = getattr(product, "shop", None)
        key = _shop_group_key(shop, product)
        if key not in groups_by_key:
            groups_by_key[key] = {
                "shop": shop,
                "items": [],
                "subtotal_cents": 0,
            }
        quantity = _cart_item_quantity(item)
        unit_price_cents = _cart_item_unit_price_cents(item)
        line_total_cents = _cart_item_line_total_cents(item)
        if isinstance(item, dict):
            normalized_item = item
            normalized_item.setdefault("product", product)
            normalized_item.setdefault("quantity", quantity)
            normalized_item.setdefault("unit_price_cents", unit_price_cents)
            normalized_item.setdefault("unit_price", cents_to_money(unit_price_cents))
            normalized_item.setdefault("unit_price_label", _format_money(unit_price_cents))
            normalized_item.setdefault("line_total_cents", line_total_cents)
            normalized_item.setdefault("line_total", cents_to_money(line_total_cents))
            normalized_item.setdefault("line_total_label", _format_money(line_total_cents))
        else:
            normalized_item = {
                "product": product,
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
                "unit_price": cents_to_money(unit_price_cents),
                "unit_price_label": _format_money(unit_price_cents),
                "line_total_cents": line_total_cents,
                "line_total": cents_to_money(line_total_cents),
                "line_total_label": _format_money(line_total_cents),
            }
        groups_by_key[key]["items"].append(normalized_item)
        groups_by_key[key]["subtotal_cents"] += line_total_cents

    groups = list(groups_by_key.values())
    for group in groups:
        group["subtotal"] = cents_to_money(group["subtotal_cents"])
        group["subtotal_label"] = _format_money(group["subtotal_cents"])
    return groups


def generate_shop_whatsapp_message(shop, items, client_data):
    """Construit le message WhatsApp d'une boutique, sans les produits des autres."""
    item_lines = []
    subtotal_cents = 0
    for item in items or []:
        product = _cart_item_product(item)
        if not product:
            continue
        quantity = _cart_item_quantity(item)
        line_total_cents = _cart_item_line_total_cents(item)
        subtotal_cents += line_total_cents
        product_name = (getattr(product, "name", None) or "Produit").strip()
        item_lines.append(f"- {product_name} x{quantity} - {_format_money(line_total_cents)}")

    client_name = (client_data or {}).get("name") or (client_data or {}).get("full_name") or ""
    client_phone = (client_data or {}).get("phone") or ""
    client_address = (client_data or {}).get("address") or ""

    lines = [
        "Bonjour, je souhaite commander les produits suivants :",
        "",
        f"🛍 Boutique : {_shop_display_name(shop)}",
        "",
        *(item_lines or ["- Aucun produit"]),
        "",
        f"💰 Total estimé : {_format_money(subtotal_cents)}",
    ]

    client_lines = []
    if client_name:
        client_lines.append(f"👤 Client : {client_name}")
    if client_phone:
        client_lines.append(f"📱 Téléphone : {client_phone}")
    if client_address:
        client_lines.append(f"📍 Adresse : {client_address}")
    if client_lines:
        lines.extend(["", *client_lines])

    lines.extend([
        "",
        "Merci de me confirmer la disponibilité, le paiement et la livraison.",
    ])
    return "\n".join(lines)


def build_whatsapp_link(phone, message):
    number = normalize_whatsapp_number(phone)
    if not number:
        return ""
    return f"https://wa.me/{number}?text={quote(message or '', safe='')}"


def prepare_vendor_whatsapp_checkout(cart_items, client_data):
    """Prepare les blocs WhatsApp vendeurs sans commande, livraison ni commission."""
    shop_groups = group_cart_items_by_shop(cart_items)
    total_cents = 0

    for group in shop_groups:
        subtotal_cents = int(group.get("subtotal_cents") or 0)
        total_cents += subtotal_cents
        shop = group.get("shop")
        shop_id = getattr(shop, "id", None)
        vendor_id = getattr(shop, "vendor_id", None)
        phone_raw = _shop_phone_raw(shop)
        phone = normalize_whatsapp_number(phone_raw)
        message = generate_shop_whatsapp_message(shop, group.get("items", []), client_data)
        group.update({
            "shop_id": shop_id,
            "vendor_id": vendor_id,
            "shop_name": _shop_display_name(shop),
            "phone_raw": phone_raw,
            "phone": phone,
            "phone_available": bool(phone),
            "whatsapp_message": message,
            "whatsapp_url": build_whatsapp_link(phone_raw, message),
            "items_count": sum(_cart_item_quantity(item) for item in group.get("items", [])),
        })

    return {
        "shop_groups": shop_groups,
        "client_data": client_data or {},
        "total_cents": total_cents,
        "total": cents_to_money(total_cents),
        "total_label": _format_money(total_cents),
        "multiple_shops": len(shop_groups) > 1,
    }


def record_product_contact_leads(checkout_data, client_data):
    """Trace les contacts WhatsApp produits, sans bloquer le checkout."""
    groups = (checkout_data or {}).get("shop_groups") or []
    if not groups:
        return 0

    created = 0
    try:
        for group in groups:
            shop = group.get("shop")
            summary = []
            for item in group.get("items", []):
                product = _cart_item_product(item)
                summary.append({
                    "product_id": getattr(product, "id", None),
                    "product_name": getattr(product, "name", None) or "Produit",
                    "quantity": _cart_item_quantity(item),
                    "unit_price_cents": _cart_item_unit_price_cents(item),
                    "line_total_cents": _cart_item_line_total_cents(item),
                })

            db.session.add(ProductContactLead(
                client_name=((client_data or {}).get("name") or "")[:100],
                client_phone=((client_data or {}).get("phone") or "")[:30],
                shop_id=group.get("shop_id") or getattr(shop, "id", None),
                product_summary_json=json.dumps(summary, ensure_ascii=False),
                estimated_total=int(group.get("subtotal_cents") or 0),
                whatsapp_phone=(group.get("phone") or group.get("phone_raw") or "")[:30],
                source="product_whatsapp",
            ))
            created += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("product_contact_lead_record_failed")
        return 0
    return created


def _checkout_contact_session_key(group) -> str:
    shop = (group or {}).get("shop")
    shop_id = (group or {}).get("shop_id") or getattr(shop, "id", None)
    summary = []
    for item in (group or {}).get("items", []):
        product = _cart_item_product(item)
        summary.append({
            "product_id": getattr(product, "id", None),
            "quantity": _cart_item_quantity(item),
            "line_total_cents": _cart_item_line_total_cents(item),
        })
    digest = hashlib.sha1(
        json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"product_whatsapp:{shop_id}:{digest}"


def _product_kind(product) -> str:
    return (getattr(product, "kind", None) or "physical").strip().lower()


def _is_service_product(product) -> bool:
    return _product_kind(product) == "service"


def _shop_open_message(product) -> str | None:
    """Retourne un message si la boutique du produit est fermée/désactivée, sinon None."""
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
                Shop.vendor_id,
                Shop.name,
                Shop.contact_phone,
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
        message = "Ce service se réserve. Merci de passer par la réservation."
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
        "Produit ajouté. Vérifiez vos articles avant de finaliser."
        if redirect_url
        else "Produit ajouté au panier."
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
        'message': 'Produit retiré du panier',
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
    response = jsonify({
        "cart_count": int(summary.get("count", 0) or 0),
        "track_active": False,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


# =====================================================
# CHECKOUT
# =====================================================
def _physical_cart_items_for_checkout(cart, product_map, promo_map):
    items = []
    subtotal_cents = 0

    for pid_str, raw_qty in cart.items():
        try:
            pid = int(pid_str)
        except ValueError:
            continue

        qty = _safe_cart_quantity(raw_qty)
        if qty <= 0:
            continue

        product = product_map.get(pid)
        if not product or _is_service_product(product):
            continue

        shop_msg = _shop_open_message(product)
        if shop_msg:
            return None, subtotal_cents, shop_msg

        if hasattr(product, "stock") and product.stock < qty:
            return None, subtotal_cents, f"Stock insuffisant pour {product.name}"

        price_cents = final_price_cents(product, promo_map.get(pid))
        line_total_cents = price_cents * qty
        subtotal_cents += line_total_cents
        items.append({
            "product": product,
            "quantity": qty,
            "unit_price_cents": price_cents,
            "unit_price": cents_to_money(price_cents),
            "unit_price_label": _format_money(price_cents),
            "line_total_cents": line_total_cents,
            "line_total": cents_to_money(line_total_cents),
            "line_total_label": _format_money(line_total_cents),
        })

    return items, subtotal_cents, None


@bp.route("/checkout", methods=["GET", "POST"])
@rate_limit(limit=20, window_seconds=300, key_prefix="checkout", methods=("POST",))
def checkout():
    if request.method == "GET":
        return _render_whatsapp_checkout_page()
    return whatsapp_checkout()


@bp.route("/whatsapp", methods=["POST"])
@rate_limit(limit=15, window_seconds=300, key_prefix="whatsapp", methods=("POST",))
@log_performance
def whatsapp_checkout():
    """Prepare les demandes WhatsApp par boutique pour les produits physiques."""
    return _render_whatsapp_checkout_page(log_contact_attempt=True)


def _render_whatsapp_checkout_page(*, log_contact_attempt=False):
    cart = get_cart()
    product_map, promo_map = _get_cached_cart_data(cart, include_shop=True)
    removed_services = _remove_service_items_from_cart(cart, product_map)
    if removed_services:
        set_cart(cart)
        flash("Les services se réservent. Ils ont été retirés du panier.", "info")

    if not cart:
        msg = "Panier vide"
        if removed_services:
            msg = "Votre panier contenait uniquement des services. Merci de les réserver."
        current_app.logger.warning(
            "checkout_post_rejected reason=empty_cart ajax=%s user_id=%s",
            _is_ajax_request(),
            current_user.id if current_user.is_authenticated else None,
        )
        return _ajax_error(msg, status=400, flash_category="warning", redirect_endpoint="shop.home")

    if log_contact_attempt:
        current_app.logger.info(
            "checkout_contact_start user_id=%s ajax=%s",
            current_user.id if current_user.is_authenticated else None,
            _is_ajax_request(),
        )

    client_ip = _client_ip()

    blocked_ip = None
    if client_ip:
        blocked_ip = BlockedContact.query.filter_by(kind="ip", value=client_ip, is_active=True).first()

    if blocked_ip:
        current_app.logger.warning(
            "checkout_post_rejected reason=blocked_contact user_id=%s",
            current_user.id if current_user.is_authenticated else None,
        )
        return _ajax_error("Demande bloquee. Contactez le support.", status=403, flash_category="danger", redirect_endpoint="cart.checkout")

    items, _subtotal_cents, cart_error = _physical_cart_items_for_checkout(cart, product_map, promo_map)
    if cart_error:
        return _ajax_error(cart_error, status=409, flash_category="danger", redirect_endpoint="cart.view")
    if not items:
        return _ajax_error("Panier vide", status=400, flash_category="warning", redirect_endpoint="shop.home")

    client_data = {}
    checkout_data = prepare_vendor_whatsapp_checkout(items, client_data)

    if _is_ajax_request():
        return jsonify({
            "success": True,
            "message": "Demandes WhatsApp boutique preparees.",
            "requires_full_page": True,
        })

    response = make_response(render_template(
        "cart/vendor_whatsapp_checkout.html",
        checkout_data=checkout_data,
        shop_groups=checkout_data["shop_groups"],
        client_data=client_data,
    ))
    return response


@bp.route("/whatsapp/contact/<int:shop_id>", methods=["POST"])
@rate_limit(limit=60, window_seconds=300, key_prefix="whatsapp_contact", methods=("POST",))
def record_whatsapp_contact(shop_id):
    """Trace un contact produit seulement quand le client ouvre WhatsApp."""
    cart = get_cart()
    product_map, promo_map = _get_cached_cart_data(cart, include_shop=True)
    if not cart:
        return jsonify({"success": False, "message": "Panier vide"}), 400

    items, _subtotal_cents, cart_error = _physical_cart_items_for_checkout(cart, product_map, promo_map)
    if cart_error:
        return jsonify({"success": False, "message": cart_error}), 409
    if not items:
        return jsonify({"success": False, "message": "Panier vide"}), 400

    client_data = {}
    checkout_data = prepare_vendor_whatsapp_checkout(items, client_data)
    selected_group = None
    for group in checkout_data.get("shop_groups", []):
        shop = group.get("shop")
        if getattr(shop, "id", None) == shop_id:
            selected_group = group
            break

    if not selected_group:
        return jsonify({"success": False, "message": "Boutique introuvable"}), 404
    if not selected_group.get("phone_available") or not selected_group.get("whatsapp_url"):
        return jsonify({"success": False, "message": "WhatsApp indisponible"}), 409

    contact_key = _checkout_contact_session_key(selected_group)
    contacted_keys = session.get("product_whatsapp_contact_keys")
    if not isinstance(contacted_keys, list):
        contacted_keys = []

    recorded = False
    if contact_key not in contacted_keys:
        created = record_product_contact_leads(
            {"shop_groups": [selected_group]},
            client_data,
        )
        if created:
            try:
                notify_product_contact_leads({"shop_groups": [selected_group]})
            except Exception:
                current_app.logger.exception(
                    "vendor_push.product_contact_notify_failed",
                    extra={"shop_id": shop_id},
                )
            contacted_keys.append(contact_key)
            session["product_whatsapp_contact_keys"] = contacted_keys[-100:]
            session.modified = True
            recorded = True

    return jsonify({
        "success": True,
        "recorded": recorded,
        "whatsapp_url": selected_group["whatsapp_url"],
    })


# VIDER PANIER
# =====================================================
@bp.route("/clear", methods=["POST"])
def clear():
    _clear_cart_storage()
    flash("Votre panier est vide.", "info")
    return redirect(url_for("cart.view"))


