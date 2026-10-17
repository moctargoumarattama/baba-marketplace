import pytest
from flask import Flask

from dealnova.app.routes import auth


@pytest.mark.parametrize("token", ["legacy-token", "signed.token_value-123"])
def test_old_password_reset_link_redirects_to_current_recovery_without_database(token):
    app = Flask("legacy-password-reset-tests")
    app.config.update(TESTING=True, SECRET_KEY="legacy-reset-test")
    # The compatibility route must not need an initialized database or a user.
    app.register_blueprint(auth.bp)
    client = app.test_client()

    response = client.get(f"/reset-password/{token}")

    assert response.status_code == 302
    assert response.location == "/forgot-password"
    with client.session_transaction() as storage:
        category, message = storage["_flashes"][-1]
        assert category == "info"
        assert "WhatsApp" in message
        assert "_user_id" not in storage
