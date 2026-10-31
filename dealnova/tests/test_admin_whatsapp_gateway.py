from pathlib import Path
from unittest.mock import patch
from dealnova.app import create_app
from dealnova.app.extensions import db
from dealnova.app.models.user import User
from dealnova.app.services.baba_whatsapp import (
    disconnect_whatsapp_gateway,
    get_whatsapp_gateway_status,
    reconnect_whatsapp_gateway,
    test_whatsapp_tunnel_and_reception as diagnose_whatsapp_tunnel,
)

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_whatsapp_gateway_template_contains_disconnect_and_reconnect_buttons():
    content = _read("app/templates/admin/whatsapp_gateway.html")

    assert 'id="waDisconnectBtn"' in content
    assert 'id="waReconnectBtn"' in content
    assert 'id="waRefreshBtn"' in content
    assert 'id="waStatusBanner"' in content
    assert 'id="waQrImage"' in content
    assert "admin.whatsapp_gateway_disconnect" in content
    assert "admin.whatsapp_gateway_reconnect" in content


def test_only_single_tunnel_and_reception_test_button_in_template():
    content = _read("app/templates/admin/whatsapp_gateway.html")

    # Tous les boutons qui envoyaient de vraies offres promo en test doivent être supprimés
    assert "whatsapp_promo_send_test" not in content
    assert "formSendTest" not in content
    assert "Test WhatsApp" not in content
    assert "</i>Tester" not in content

    # Un seul bouton dédié au diagnostic du tunnel et de l'état de réception
    assert content.count('id="waTestTunnelBtn"') == 1
    assert "admin.whatsapp_gateway_test_tunnel" in content
    assert "Tester tunnel &amp; réception" in content
    assert 'id="waTunnelProgress"' in content
    assert 'id="waTunnelLiveMsg"' in content
    assert 'aria-live="polite"' in content


def test_disconnect_whatsapp_gateway_graceful_on_network_error():
    with patch("requests.post", side_effect=Exception("Connection refused")):
        res = disconnect_whatsapp_gateway(logout_url="http://127.0.0.1:3002/api/logout")
        assert res["success"] is False
        assert "Impossible de contacter l'endpoint" in res["message"]


def test_reconnect_whatsapp_gateway_graceful_on_network_error():
    with patch("requests.post", side_effect=Exception("Connection refused")):
        res = reconnect_whatsapp_gateway(reconnect_url="http://127.0.0.1:3002/api/reconnect")
        assert res["success"] is False
        assert "Échec de la demande" in res["message"]


def test_get_whatsapp_gateway_status_parses_connected_phone():
    class MockResp:
        status_code = 200
        content = b'{"status": "connected", "phone": "212612345678@s.whatsapp.net"}'

        def json(self):
            return {"status": "connected", "phone": "212612345678@s.whatsapp.net"}

    with patch("requests.get", return_value=MockResp()):
        res = get_whatsapp_gateway_status()
        assert res["status"] == "connected"
        assert res["phone"] == "212612345678"
        assert res["reachable"] is True


def test_tunnel_and_reception_diagnostic_states():
    # 1. Tunnel local injoignable
    with patch("requests.get", side_effect=Exception("Connection refused")), patch("requests.post") as mock_post:
        res_down = diagnose_whatsapp_tunnel()
        assert res_down["success"] is False
        assert res_down["tunnel_ok"] is False
        assert res_down["reception_ok"] is False
        assert res_down["tunnel_latency_ms"] >= 1
        assert "Tunnel injoignable" in res_down["message"]
        mock_post.assert_not_called()

    # 2. Tunnel actif mais session en attente de scan QR
    class QrResp:
        status_code = 200
        content = b'{"status": "qr_ready"}'

        def json(self):
            return {"status": "qr_ready"}

    with patch("requests.get", return_value=QrResp()), patch("requests.post") as mock_post:
        res_qr = diagnose_whatsapp_tunnel()
        assert res_qr["success"] is False
        assert res_qr["tunnel_ok"] is True
        assert res_qr["reception_ok"] is False
        assert res_qr["status"] == "qr_ready"
        assert "Tunnel actif" in res_qr["message"]
        mock_post.assert_not_called()

    # 3. Tunnel actif + WhatsApp connecté + réception confirmée
    class ConnectedResp:
        status_code = 200
        content = b'{"status": "connected", "phone": "212771822779@s.whatsapp.net"}'

        def json(self):
            return {"status": "connected", "phone": "212771822779@s.whatsapp.net"}

    class SendOkResp:
        status_code = 200
        text = '{"sent": true}'

    with patch("requests.get", return_value=ConnectedResp()), patch("requests.post", return_value=SendOkResp()) as mock_post:
        res_ok = diagnose_whatsapp_tunnel()
        assert res_ok["success"] is True
        assert res_ok["tunnel_ok"] is True
        assert res_ok["reception_ok"] is True
        assert res_ok["phone"] == "212771822779"
        assert res_ok["tunnel_latency_ms"] >= 1
        assert res_ok["delivery_latency_ms"] >= 1
        assert "Réception WhatsApp confirmée" in res_ok["message"]
        assert mock_post.call_count == 1
        sent_json = mock_post.call_args.kwargs["json"]
        assert sent_json["phone"] == "212771822779"
        assert "Diagnostic Baba Market" in sent_json["message"]


def test_admin_whatsapp_gateway_routes_registered_and_test_tunnel_endpoint():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    rules = [rule.rule for rule in app.url_map.iter_rules()]

    assert "/admin/whatsapp-gateway" in rules
    assert "/admin/whatsapp-gateway/disconnect" in rules
    assert "/admin/whatsapp-gateway/reconnect" in rules
    assert "/admin/whatsapp-gateway/test-tunnel" in rules

    with app.app_context():
        mgr = User.query.filter_by(username="mgr_tunnel_check").first()
        if not mgr:
            mgr = User(username="mgr_tunnel_check", email="mgr_tunnel_check@babamarket.ma", role="manager", is_active=True)
            mgr.set_password("ManagerPass123!")
            db.session.add(mgr)
        vnd = User.query.filter_by(username="vnd_tunnel_check").first()
        if not vnd:
            vnd = User(username="vnd_tunnel_check", email="vnd_tunnel_check@babamarket.ma", role="vendor", is_active=True)
            vnd.set_password("VendorPass123!")
            db.session.add(vnd)
        db.session.commit()
        mgr_id, vnd_id = mgr.id, vnd.id

    vnd_client = app.test_client()
    with vnd_client.session_transaction() as sess:
        sess["_user_id"] = str(vnd_id)
        sess["_fresh"] = True
    assert vnd_client.post("/admin/whatsapp-gateway/test-tunnel", json={}).status_code in (302, 403)

    mgr_client = app.test_client()
    with mgr_client.session_transaction() as sess:
        sess["_user_id"] = str(mgr_id)
        sess["_fresh"] = True

    with patch("dealnova.app.routes.admin.test_whatsapp_tunnel_and_reception") as mock_diag:
        mock_diag.return_value = {
            "success": True,
            "tunnel_ok": True,
            "reception_ok": True,
            "phone": "212771822779",
            "tunnel_latency_ms": 4,
            "delivery_latency_ms": 112,
            "checked_at": "21:20:00",
            "message": "Tunnel actif (4 ms) • Réception WhatsApp confirmée sur +212771822779 (112 ms).",
        }
        resp = mgr_client.post("/admin/whatsapp-gateway/test-tunnel", json={"action": "test_tunnel"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["tunnel_ok"] is True
        assert data["reception_ok"] is True


def test_whatsapp_gateway_bento_responsive_design():
    content = _read("app/templates/admin/whatsapp_gateway.html")

    assert "offers-bento-grid" in content
    assert "container: offer-card / inline-size" in content
    assert 'html[data-admin-theme="noc"] .wa-app-container' in content
    assert "color-scheme: only light;" in content
    assert 'id="step3Settings"' in content
    assert "Clics sur liens" in content
    assert "CLICS RÉELS (/P/..)" not in content.upper()
