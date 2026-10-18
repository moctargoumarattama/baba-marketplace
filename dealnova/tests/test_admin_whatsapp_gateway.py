from pathlib import Path
from unittest.mock import patch
from dealnova.app import create_app
from dealnova.app.services.baba_whatsapp import (
    disconnect_whatsapp_gateway,
    get_whatsapp_gateway_status,
    reconnect_whatsapp_gateway,
)

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_whatsapp_gateway_template_contains_disconnect_and_reconnect_buttons():
    content = _read("app/templates/admin/whatsapp_gateway.html")

    assert "id=\"waDisconnectBtn\"" in content
    assert "id=\"waReconnectBtn\"" in content
    assert "id=\"waRefreshBtn\"" in content
    assert "id=\"waPhonePill\"" in content
    assert "id=\"waQrPollIndicator\"" in content
    assert "admin.whatsapp_gateway_disconnect" in content
    assert "admin.whatsapp_gateway_reconnect" in content
    assert "data-adm-page=\"whatsapp-gateway\"" in content


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


def test_admin_whatsapp_gateway_routes_registered():
    app = create_app()
    rules = [rule.rule for rule in app.url_map.iter_rules()]

    assert "/admin/whatsapp-gateway" in rules
    assert "/admin/whatsapp-gateway/disconnect" in rules
    assert "/admin/whatsapp-gateway/reconnect" in rules

