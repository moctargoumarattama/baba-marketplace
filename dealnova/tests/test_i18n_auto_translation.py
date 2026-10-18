from unittest.mock import MagicMock, patch

import pytest
from dealnova.app import create_app
from dealnova.app.services.i18n_runtime import translate_text, _load_language_dict, auto_translate_ui_to_darija


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


def test_existing_darija_keys_are_served_instantly(app):
    with app.app_context():
        # Existing keys must be returned directly without API calls
        res = translate_text("Accueil", "ary")
        assert res == "alryysya"

        res_signup = translate_text("S'inscrire", "ary")
        assert res_signup.lower() == "tsajel"


def test_french_returns_original_text(app):
    with app.app_context():
        res = translate_text("Nom d'utilisateur", "fr")
        assert res == "Nom d'utilisateur"


def test_new_ui_text_auto_translates_via_gemini_without_touching_products(app):
    with app.app_context():
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Bouton jdida"}]
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_resp):
            res = translate_text("Nouveau Bouton Test Spécial", "ary")
            assert res == "Bouton jdida"

