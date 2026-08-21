import json
from base64 import urlsafe_b64decode
from datetime import datetime

from flask import current_app, url_for

from ..extensions import db
from ..models.user import User
from ..models.vendor_push_subscription import VendorPushSubscription

try:
    from pywebpush import WebPushException, webpush
except Exception:  # pragma: no cover - optional dependency in local dev
    WebPushException = Exception
    webpush = None


def vendor_push_public_key() -> str:
    return (current_app.config.get("VENDOR_PUSH_VAPID_PUBLIC_KEY") or "").strip()


def vendor_push_public_key_is_valid(public_key: str | None = None) -> bool:
    key = (public_key if public_key is not None else vendor_push_public_key() or "").strip()
    if not key or "BEGIN" in key or "PRIVATE" in key or any(ch.isspace() for ch in key):
        return False
    try:
        padding = "=" * ((4 - len(key) % 4) % 4)
        decoded = urlsafe_b64decode((key + padding).encode("ascii"))
    except Exception:
        return False
    return len(decoded) == 65 and decoded[0] == 4


def vendor_push_is_configured() -> bool:
    return bool(vendor_push_configuration_status().get("configured"))


def vendor_push_configuration_status() -> dict:
    public_key = vendor_push_public_key()
    has_public_key = bool(public_key)
    valid_public_key = vendor_push_public_key_is_valid(public_key)
    has_private_key = bool((current_app.config.get("VENDOR_PUSH_VAPID_PRIVATE_KEY") or "").strip())
    dependency_available = bool(webpush)

    reason = "configured"
    if not dependency_available:
        reason = "missing_dependency"
    elif not has_public_key:
        reason = "missing_public_key"
    elif not valid_public_key:
        reason = "invalid_public_key"
    elif not has_private_key:
        reason = "missing_private_key"

    return {
        "configured": reason == "configured",
        "reason": reason,
        "dependencyAvailable": dependency_available,
        "hasPublicKey": has_public_key,
        "validPublicKey": valid_public_key,
        "hasPrivateKey": has_private_key,
    }


def upsert_vendor_push_subscription(vendor_id: int, payload: dict, user_agent: str = "") -> VendorPushSubscription:
    endpoint = str((payload or {}).get("endpoint") or "").strip()
    keys = (payload or {}).get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        raise ValueError("invalid_push_subscription")

    subscription = VendorPushSubscription.query.filter_by(endpoint=endpoint).first()
    now = datetime.utcnow()
    if subscription is None:
        subscription = VendorPushSubscription(endpoint=endpoint, vendor_id=vendor_id)
        db.session.add(subscription)

    subscription.vendor_id = vendor_id
    subscription.p256dh = p256dh
    subscription.auth = auth
    subscription.user_agent = (user_agent or "")[:255]
    subscription.is_active = True
    subscription.failure_count = 0
    subscription.last_seen_at = now
    subscription.updated_at = now
    db.session.commit()
    return subscription


def deactivate_vendor_push_subscription(endpoint: str, *, vendor_id: int | None = None) -> bool:
    endpoint = (endpoint or "").strip()
    if not endpoint:
        return False
    query = VendorPushSubscription.query.filter_by(endpoint=endpoint)
    if vendor_id is not None:
        query = query.filter_by(vendor_id=vendor_id)
    subscription = query.first()
    if not subscription:
        return False
    subscription.is_active = False
    subscription.updated_at = datetime.utcnow()
    db.session.commit()
    return True


def _subscription_info(subscription: VendorPushSubscription) -> dict:
    return {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        },
    }


def _mark_subscription_failed(subscription: VendorPushSubscription):
    subscription.failure_count = int(subscription.failure_count or 0) + 1
    if subscription.failure_count >= 3:
        subscription.is_active = False
    subscription.updated_at = datetime.utcnow()


def send_vendor_push_notification(vendor_id: int, payload: dict) -> int:
    if not vendor_push_is_configured():
        current_app.logger.info("vendor_push.skipped_not_configured vendor_id=%s", vendor_id)
        return 0

    subscriptions = (
        VendorPushSubscription.query
        .filter_by(vendor_id=vendor_id, is_active=True)
        .order_by(VendorPushSubscription.updated_at.desc())
        .all()
    )
    if not subscriptions:
        return 0

    vapid_private_key = (current_app.config.get("VENDOR_PUSH_VAPID_PRIVATE_KEY") or "").strip()
    vapid_email = (current_app.config.get("VENDOR_PUSH_VAPID_EMAIL") or "mailto:admin@babamarket.local").strip()
    if not vapid_email.startswith("mailto:"):
        vapid_email = "mailto:" + vapid_email

    sent = 0
    body = json.dumps(payload or {}, ensure_ascii=False)
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info=_subscription_info(subscription),
                data=body,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_email},
                ttl=86400,
            )
            subscription.failure_count = 0
            subscription.last_seen_at = datetime.utcnow()
            subscription.updated_at = datetime.utcnow()
            sent += 1
        except WebPushException as exc:
            current_app.logger.warning(
                "vendor_push.send_failed vendor_id=%s subscription_id=%s error=%s",
                vendor_id,
                subscription.id,
                exc,
            )
            _mark_subscription_failed(subscription)
        except Exception:
            current_app.logger.exception(
                "vendor_push.send_unexpected vendor_id=%s subscription_id=%s",
                vendor_id,
                subscription.id,
            )
            _mark_subscription_failed(subscription)
    db.session.commit()
    return sent


def notify_vendor_new_order(vendor_id: int, *, order_id: int, amount_cents: int = 0, items_count: int = 0) -> int:
    amount_mad = max(0, int(amount_cents or 0)) / 100
    return send_vendor_push_notification(
        vendor_id,
        {
            "type": "vendor_order",
            "title": "Nouvelle commande",
            "body": f"Commande #{order_id} - {items_count} article(s), {amount_mad:.2f} MAD",
            "url": url_for("vendor.dashboard", _external=False),
            "tag": f"vendor-order-{order_id}",
        },
    )


def notify_product_contact_leads(checkout_data: dict) -> int:
    sent = 0
    for group in (checkout_data or {}).get("shop_groups") or []:
        shop = group.get("shop")
        vendor_id = group.get("vendor_id")
        shop_id = group.get("shop_id")
        if vendor_id is None:
            try:
                vendor_id = getattr(shop, "vendor_id", None)
            except Exception:
                vendor_id = None
        if shop_id is None:
            try:
                shop_id = getattr(shop, "id", "shop")
            except Exception:
                shop_id = "shop"
        if not vendor_id:
            continue
        sent += send_vendor_push_notification(
            int(vendor_id),
            {
                "type": "vendor_whatsapp_contact",
                "title": "Nouvelle demande client",
                "body": f"Un client ouvre WhatsApp pour {int(group.get('items_count') or 0)} article(s).",
                "url": url_for("vendor.dashboard", _external=False),
                "tag": f"vendor-contact-{shop_id or 'shop'}",
            },
        )
    return sent


def notify_service_booking(booking) -> int:
    shop = getattr(booking, "shop", None)
    vendor_id = getattr(shop, "vendor_id", None)
    if not vendor_id:
        return 0

    product = getattr(booking, "product", None)
    service_name = (getattr(product, "name", "") or "service").strip()
    client_name = (getattr(booking, "full_name", "") or "Client").strip()
    return send_vendor_push_notification(
        int(vendor_id),
        {
            "type": "vendor_service_booking",
            "title": "Nouvelle reservation service",
            "body": f"{client_name} demande un rendez-vous pour {service_name}.",
            "url": url_for("vendor.dashboard", _external=False),
            "tag": f"vendor-booking-{getattr(booking, 'id', 'new')}",
        },
    )


def notify_location_inquiry(listing, inquiry: dict) -> int:
    vendor_id = getattr(listing, "owner_id", None)
    if not vendor_id:
        return 0

    client_name = ((inquiry or {}).get("name") or "Client").strip()
    title = (getattr(listing, "title", "") or "location").strip()
    return send_vendor_push_notification(
        int(vendor_id),
        {
            "type": "vendor_location_inquiry",
            "title": "Nouvelle demande location",
            "body": f"{client_name} demande une visite pour {title}.",
            "url": url_for("rentals.owner_locations", _external=False),
            "tag": f"vendor-location-{getattr(listing, 'id', 'new')}",
        },
    )


def notify_admin_vendor_change_request(change_request) -> int:
    vendor = getattr(change_request, "vendor", None)
    shop = getattr(change_request, "shop", None)
    shop_name = (getattr(shop, "name", "") or "Boutique").strip()
    vendor_label = (
        getattr(vendor, "username", None)
        or getattr(vendor, "email", None)
        or f"vendeur #{getattr(change_request, 'vendor_id', '')}"
    )
    request_type = getattr(change_request, "request_type", "") or ""
    type_label = "email" if request_type == "account_email" else "nom de boutique"

    admin_ids = [
        int(row.id)
        for row in (
            User.query
            .filter(User.role.in_(("admin", "manager")))
            .filter(User.is_active.is_(True))
            .all()
        )
        if getattr(row, "id", None) is not None
    ]
    sent = 0
    for admin_id in admin_ids:
        sent += send_vendor_push_notification(
            admin_id,
            {
                "type": "vendor_change_request",
                "title": "Demande vendeur à valider",
                "body": f"{vendor_label} demande un changement {type_label} pour {shop_name}.",
                "url": url_for("admin_users.vendor_change_requests", _external=False),
                "tag": f"vendor-change-request-{getattr(change_request, 'id', 'new')}",
            },
        )
    return sent
