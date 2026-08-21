from pathlib import Path
from base64 import urlsafe_b64encode
import sys
import types

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ensure_namespace(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


_ensure_namespace("dealnova", ROOT)
_ensure_namespace("dealnova.app", ROOT / "app")
_ensure_namespace("dealnova.app.models", ROOT / "app" / "models")
_ensure_namespace("dealnova.app.services", ROOT / "app" / "services")


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _valid_vapid_public_key() -> str:
    return urlsafe_b64encode((bytes([4]) + (b"0" * 64))).decode("ascii").rstrip("=")


def test_vendor_push_subscription_model_and_routes_exist():
    model = _read("app/models/vendor_push_subscription.py")
    vendor_routes = _read("app/routes/vendor.py")

    assert "class VendorPushSubscription" in model
    assert "endpoint" in model
    assert "p256dh" in model
    assert "auth" in model
    assert '@bp.route("/notifications/push/config")' in vendor_routes
    assert '@bp.route("/notifications/push/subscribe", methods=["POST"])' in vendor_routes
    assert '@bp.route("/notifications/push/unsubscribe", methods=["POST"])' in vendor_routes
    assert '@bp.route("/notifications/push/test", methods=["POST"])' in vendor_routes
    assert '@bp.route("/notifications/push/status")' in vendor_routes
    push_service = _read("app/services/vendor_push.py")
    assert "vendor_push_public_key_is_valid" in push_service
    assert "urlsafe_b64decode" in push_service
    assert "ttl=86400" in push_service


def test_vendor_push_config_reads_vapid_environment():
    config_source = _read("app/config.py")

    assert "VENDOR_PUSH_VAPID_PUBLIC_KEY" in config_source
    assert "VENDOR_PUSH_VAPID_PRIVATE_KEY" in config_source
    assert "VENDOR_PUSH_VAPID_EMAIL" in config_source
    assert not (ROOT / "app" / "confprod.py").exists()


def test_vendor_push_configuration_status_reports_server_reason(monkeypatch):
    from dealnova.app.services import vendor_push

    app = Flask(__name__)
    app.config.update(
        VENDOR_PUSH_VAPID_PUBLIC_KEY="",
        VENDOR_PUSH_VAPID_PRIVATE_KEY="",
        VENDOR_PUSH_VAPID_EMAIL="admin@example.test",
    )

    monkeypatch.setattr(vendor_push, "webpush", object())
    with app.app_context():
        status = vendor_push.vendor_push_configuration_status()
    assert status["configured"] is False
    assert status["reason"] == "missing_public_key"

    app.config.update(
        VENDOR_PUSH_VAPID_PUBLIC_KEY=_valid_vapid_public_key(),
        VENDOR_PUSH_VAPID_PRIVATE_KEY="private-key",
    )
    with app.app_context():
        status = vendor_push.vendor_push_configuration_status()
    assert status["configured"] is True
    assert status["reason"] == "configured"


def test_vendor_dashboard_registers_push_notifications_with_service_worker():
    template = _read("app/templates/vendor/dashboard.html")
    script = _read("app/static/js/pages/vendor/dashboard_page.js")
    stylesheet = _read("app/static/css/vendor/vendor_dashboard.css")
    worker = _read("app/static/sw.js")

    assert "data-push-config-url" in template
    assert "data-push-subscribe-url" in template
    assert "initVendorPushNotifications" in script
    assert "Notification.requestPermission" in script
    assert "pushManager.subscribe" in script
    assert "vendor-push-status" in template
    assert "VENDOR_ORDER_ALERT_MS = 5000" in script
    assert "navigator.vibrate" in script
    assert "isIosDevice" in script
    assert "Installer l'app" in script
    assert "cfg.pushStatusUrl" in script
    assert "showSystemVendorNotification('Test alerte vendeur'" in script
    assert "isValidVapidPublicKey" in script
    assert "Clé push invalide" in script
    assert "showSoundActivationPrompt" in script
    assert "Réactiver le son" in script
    assert "vendor-sound-prompt" in stylesheet
    assert "self.addEventListener(\"push\"" in worker
    assert "registration.showNotification" in worker
    assert "self.addEventListener(\"notificationclick\"" in worker
    assert "vibrate:" in worker


def test_vendor_dashboard_live_counters_are_fresh_and_complete():
    template = _read("app/templates/vendor/dashboard.html")
    script = _read("app/static/js/pages/vendor/dashboard_page.js")
    vendor_routes = _read("app/routes/vendor.py")

    assert 'data-orders-poll-ms="5000"' in template
    assert 'id="todayLocationsCount"' in template
    assert "today_locations_count" in vendor_routes
    assert "allows_location" in vendor_routes
    assert "not allows_products and not allows_services and not type_flags[\"allows_location\"]" in vendor_routes
    assert 'Cache-Control"] = "private, no-store, max-age=0"' in vendor_routes
    assert "todayLocationsCount.textContent" in script
    assert "refreshOrdersLive({ force: true" in script


def test_product_whatsapp_contact_notifies_vendor_push_subscribers():
    cart_source = _read("app/routes/cart.py")
    push_service = _read("app/services/vendor_push.py")

    assert "notify_product_contact_leads" in cart_source
    assert "send_vendor_push_notification" in push_service
    assert "pywebpush" in push_service


def test_product_contact_push_uses_checkout_snapshot_before_orm_shop():
    push_service = _read("app/services/vendor_push.py")

    assert 'vendor_id = group.get("vendor_id")' in push_service
    assert 'shop_id = group.get("shop_id")' in push_service


def test_service_booking_notifies_vendor_push_subscribers():
    booking_source = _read("app/routes/booking.py")
    push_service = _read("app/services/vendor_push.py")

    assert "notify_service_booking" in booking_source
    assert "notify_service_booking" in push_service
    assert "vendor_service_booking" in push_service


def test_location_inquiry_notifies_vendor_push_subscribers():
    rentals_source = _read("app/routes/rentals.py")
    push_service = _read("app/services/vendor_push.py")

    assert "notify_location_inquiry" in rentals_source
    assert "notify_location_inquiry" in push_service
    assert "vendor_location_inquiry" in push_service


def test_vendor_change_request_notifies_admin_push_subscribers():
    vendor_routes = _read("app/routes/vendor.py")
    push_service = _read("app/services/vendor_push.py")
    admin_base = _read("app/templates/admin/base.html")

    assert "notify_admin_vendor_change_request" in vendor_routes
    assert "notify_admin_vendor_change_request" in push_service
    assert "vendor_change_request" in push_service
    assert "User.role.in_((\"admin\", \"manager\"))" in push_service
    assert "adminPushStatus" in admin_base
    assert "admin_push_notifications.js" in admin_base
    assert '{"vendor", "admin", "manager"}' in vendor_routes


def test_vendor_push_migration_and_runtime_table_guard_exist():
    migration = _read("migrations/versions/20260508_add_vendor_push_subscription.py")
    app_init = _read("app/__init__.py")
    maintenance = _read("app/services/migration.py")

    assert "vendor_push_subscription" in migration
    assert "ensure_vendor_push_subscription_table" in maintenance
    assert "ensure_vendor_push_subscription_table()" in app_init
