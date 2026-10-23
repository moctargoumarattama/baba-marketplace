import json
import pytest
from unittest.mock import MagicMock, patch

from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    with isolated_vendor_application(tmp_path_factory.mktemp("assistant-gemini")) as fixture:
        fixture.app.config.update(GEMINI_API_KEY="fake-test-key", GEMINI_MODEL="gemini-test")
        with fixture.app.app_context():
            from dealnova.app.models.product import Product

            fixture.db.session.add(Product(name="Robe de fête", description="Robe pour femme",
                                           kind="physical", price=100, stock=2, is_active=True,
                                           category_id=fixture.ids.physical, vendor_id=fixture.ids.vendor,
                                           shop_id=fixture.ids.shop))
            fixture.db.session.commit()
        yield fixture.app


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
        assert key == "fake-test-key"
        assert "gemini" in model.lower()


def test_gemini_refuses_off_topic_questions(app):
    from dealnova.app.assistant.engine import assistant_reply

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
    from dealnova.app.assistant.engine import _reply_with_gemini

    with app.test_request_context():
        fake_search = {
            "text": "Voici les robes disponibles sur Baba Market :",
            "search_query": "robe",
            "kind": "products",
            "is_off_topic": False,
            "action": None,
        }
        with patch("requests.Session.post", return_value=_mock_gemini_response(fake_search)):
            response = _reply_with_gemini("Avez-vous des robes pour femmes ?", {"flow": None, "context": {}})
            assert any(item["title"] == "Robe de fête" for item in response.get("items", []))
            assert len(response.get("quick_replies", [])) > 0


def test_gemini_handles_become_vendor_action(app):
    from dealnova.app.assistant.engine import _reply_with_gemini

    with app.test_request_context():
        fake_vendor = {
            "text": "Marhba bik! Pour devenir vendeur, voici le lien pour vous inscrire.",
            "search_query": "",
            "kind": None,
            "is_off_topic": False,
            "action": "become_vendor",
        }
        with patch("requests.Session.post", return_value=_mock_gemini_response(fake_vendor)):
            response = _reply_with_gemini("Kifech nwelli vendeur ?", {"flow": None, "context": {}})
            assert "vendeur" in response.get("text", "").lower()
            assert "vendor-access" in response.get("redirect_url", "")


def test_gemini_handles_handoff_action(app):
    from dealnova.app.assistant.engine import _reply_with_gemini

    with app.test_request_context():
        fake_handoff = {
            "text": "Je vous mets en relation directe avec notre conseiller WhatsApp.",
            "search_query": "",
            "kind": None,
            "is_off_topic": False,
            "action": "handoff",
        }
        with patch("requests.Session.post", return_value=_mock_gemini_response(fake_handoff)):
            response = _reply_with_gemini("Je veux parler à un humain", {"flow": None, "context": {}})
            assert "whatsapp" in response.get("text", "").lower() or "conseiller" in response.get("text", "").lower()
            assert "handoff" in response
            assert "url" in response["handoff"]


def test_gemini_graceful_fallback_when_offline(app):
    from dealnova.app.assistant.engine import _reply_with_gemini, assistant_reply

    with app.test_request_context():
        with patch("requests.Session.post", side_effect=Exception("Network timeout")):
            assert _reply_with_gemini("Comment fonctionne Baba Market pour les nouveaux visiteurs ?",
                                      {"flow": None, "context": {}}) is None
            resp = assistant_reply(message="Je cherche un produit")
            # Must fall back gracefully to deterministic flow without crash
            assert "text" in resp
            assert "produit" in resp["text"].lower()


def test_gemini_clarifies_vague_request_and_receives_recent_conversation(app):
    from dealnova.app.assistant.engine import assistant_reply

    clarification = {
        "intent": "clarify",
        "reset_search": False,
        "text": "Vous cherchez plutôt un repas, un article, un service ou un logement ?",
        "search_query": "",
        "kind": None,
        "is_off_topic": False,
        "action": None,
        "sort": "low",
    }
    repair = {
        "intent": "clarify",
        "reset_search": False,
        "text": "J'ai mal compris. Quel type de chose recherchez-vous ?",
        "search_query": "",
        "kind": None,
        "is_off_topic": False,
        "action": None,
    }
    with app.test_request_context():
        with patch("requests.Session.post", side_effect=[
                _mock_gemini_response(clarification), _mock_gemini_response(repair)]) as post:
            first = assistant_reply(message="je veux un truc simple avec un prix pas trop elever")
            second = assistant_reply(message="mais répond correctement")

    assert "repas" in first["text"].lower()
    assert "mal compris" in second["text"].lower()
    second_payload = post.call_args_list[1].kwargs["json"]
    contents = second_payload["contents"]
    assert contents[-1]["parts"][0]["text"] == "mais répond correctement"
    assert any(entry["role"] == "user" and "truc simple" in entry["parts"][0]["text"]
               for entry in contents[:-1])


def test_gemini_rate_limit_skips_remote_call_and_keeps_local_assistant_useful(app):
    from dealnova.app.assistant.engine import assistant_reply

    with app.test_request_context():
        with patch("dealnova.app.assistant.engine.consume_rate_limit_slot", return_value=(False, 42)):
            with patch("requests.Session.post", side_effect=AssertionError("Gemini must not be called")) as post:
                response = assistant_reply(message="je veux un truc simple avec un prix pas trop elever")

    assert post.call_count == 0
    assert "petit prix" in response["text"].lower()
    assert response.get("quick_replies")

