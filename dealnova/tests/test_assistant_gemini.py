import json
import pytest
from unittest.mock import MagicMock, patch

from dealnova.app import create_app
from dealnova.app.assistant.engine import assistant_bootstrap, assistant_reply, _reply_with_gemini


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


def _mock_gemini_response(payload_dict, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(payload_dict)}]
                }
            }
        ]
    }
    return mock


def test_gemini_config_is_loaded(app):
    with app.app_context():
        key = app.config.get("GEMINI_API_KEY", "")
        model = app.config.get("GEMINI_MODEL", "")
        assert key.startswith("AQ.")
        assert "gemini" in model.lower()


def test_gemini_refuses_off_topic_questions(app):
    with app.test_request_context():
        fake_refusal = {
            "text": "Je suis l'assistant dédié exclusivement à Baba Market au Maroc. Que recherchez-vous sur Baba Market ?",
            "search_query": "",
            "kind": None,
            "is_off_topic": True,
            "action": None,
        }
        with patch("requests.Session.post", return_value=_mock_gemini_response(fake_refusal)):
            response = assistant_reply(message="Qui a gagne la coupe du monde 1998 ?")
            text = response.get("text", "").lower()
            assert "baba market" in text
            assert "items" not in response
            assert len(response.get("quick_replies", [])) > 0


def test_gemini_handles_product_search_and_items(app):
    with app.test_request_context():
        fake_search = {
            "text": "Voici les robes disponibles sur Baba Market :",
            "search_query": "robe",
            "kind": "products",
            "is_off_topic": False,
            "action": None,
        }
        with patch("requests.Session.post", return_value=_mock_gemini_response(fake_search)):
            response = assistant_reply(message="Avez-vous des robes pour femmes ?")
            assert "robes" in response.get("text", "").lower()
            assert len(response.get("quick_replies", [])) > 0


def test_gemini_handles_become_vendor_action(app):
    with app.test_request_context():
        fake_vendor = {
            "text": "Marhba bik! Pour devenir vendeur, voici le lien pour vous inscrire.",
            "search_query": "",
            "kind": None,
            "is_off_topic": False,
            "action": "become_vendor",
        }
        with patch("requests.Session.post", return_value=_mock_gemini_response(fake_vendor)):
            response = assistant_reply(message="Kifech nwelli vendeur ?")
            assert "vendeur" in response.get("text", "").lower()
            assert "vendor-access" in response.get("redirect_url", "")


def test_gemini_handles_handoff_action(app):
    with app.test_request_context():
        fake_handoff = {
            "text": "Je vous mets en relation directe avec notre conseiller WhatsApp.",
            "search_query": "",
            "kind": None,
            "is_off_topic": False,
            "action": "handoff",
        }
        with patch("requests.Session.post", return_value=_mock_gemini_response(fake_handoff)):
            response = assistant_reply(message="Je veux parler à un humain")
            assert "whatsapp" in response.get("text", "").lower() or "conseiller" in response.get("text", "").lower()
            assert "handoff" in response
            assert "url" in response["handoff"]


def test_gemini_graceful_fallback_when_offline(app):
    with app.test_request_context():
        with patch("requests.Session.post", side_effect=Exception("Network timeout")):
            resp = assistant_reply(message="Je cherche un produit")
            # Must fall back gracefully to deterministic flow without crash
            assert "text" in resp
            assert "produit" in resp["text"].lower()

