from __future__ import annotations

import importlib.util
import smtplib
from pathlib import Path

import pytest
from flask import Flask

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PACKAGE_ROOT / relative_path).read_text(encoding="utf-8-sig")


_EMAIL_SERVICE_SPEC = importlib.util.spec_from_file_location(
    "dealnova_test_email_service",
    PACKAGE_ROOT / "app" / "services" / "email_service.py",
)
email_service = importlib.util.module_from_spec(_EMAIL_SERVICE_SPEC)
assert _EMAIL_SERVICE_SPEC is not None and _EMAIL_SERVICE_SPEC.loader is not None
_EMAIL_SERVICE_SPEC.loader.exec_module(email_service)


@pytest.fixture()
def email_app():
    app = Flask("dealnova-email-tests")
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        PUBLIC_BASE_URL="https://www.babamarket.test",
        SITE_NAME="Baba Market",
        MAIL_SERVER="smtp.example.test",
        MAIL_PORT=587,
        MAIL_USERNAME="sender@example.test",
        MAIL_PASSWORD="smtp-pass",
        MAIL_DEFAULT_SENDER="Baba Market <sender@example.test>",
        MAIL_USE_TLS=True,
        MAIL_USE_SSL=False,
        MAIL_TIMEOUT=15,
    )

    @app.route("/login")
    def login():
        return "login"

    return app


def test_send_account_created_email_uses_smtp_and_contains_credentials(email_app, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout
            sent["tls_started"] = False
            sent["logged_in"] = None
            sent["message"] = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            sent["tls_started"] = context is not None

        def login(self, username, password):
            sent["logged_in"] = (username, password)

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    with email_app.app_context(), email_app.test_request_context("/register"):
        result = email_service.send_account_created_email(
            recipient_email="client@example.test",
            account_email="client@example.test",
            password_plaintext="Secret1234",
            login_url="https://www.babamarket.test/login",
        )

    assert result == {"sent": True, "reason": "sent"}
    assert sent["host"] == "smtp.example.test"
    assert sent["port"] == 587
    assert sent["timeout"] == 15
    assert sent["tls_started"] is True
    assert sent["logged_in"] == ("sender@example.test", "smtp-pass")
    assert sent["message"]["From"] == "Baba Market <sender@example.test>"
    assert sent["message"]["To"] == "client@example.test"
    body = sent["message"].get_content()
    assert "client@example.test" in body
    assert "Secret1234" in body
    assert "https://www.babamarket.test/login" in body


def test_send_account_created_email_returns_failure_when_smtp_crashes(email_app, monkeypatch):
    class BrokenSMTP:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPException("smtp down")

    monkeypatch.setattr(smtplib, "SMTP", BrokenSMTP)

    with email_app.app_context(), email_app.test_request_context("/register"):
        result = email_service.send_account_created_email(
            recipient_email="client@example.test",
            account_email="client@example.test",
            password_plaintext="Secret1234",
            login_url="https://www.babamarket.test/login",
        )

    assert result["sent"] is False
    assert result["reason"] == "smtp_error"


def test_send_account_created_email_uses_public_base_url_for_login_link(email_app):
    with email_app.app_context(), email_app.test_request_context("/register"):
        login_url = email_service.build_public_url("login")

    assert login_url == "https://www.babamarket.test/login"


def test_register_route_contract_uses_public_form_customer_role_and_email_after_commit():
    source = _read("app/routes/auth.py")
    start = source.index('def register():')
    next_route = source.find('\n\n@bp.route("/login"', start)
    body = source[start: next_route if next_route != -1 else len(source)]

    assert "RegisterForm()" in body
    assert 'role="customer"' in body
    assert "send_account_created_email(" in body
    assert 'return redirect(url_for("auth.login"))' in body
    assert body.index("db.session.commit()") < body.index("send_account_created_email(")


def test_register_form_contract_collects_expected_fields():
    source = _read("app/routes/forms.py")

    assert "class RegisterForm(FlaskForm):" in source
    assert 'full_name = StringField(' in source
    assert 'email = StringField("Email"' in source
    assert 'password = PasswordField(' in source
    assert 'password_confirm = PasswordField(' in source
    assert 'EqualTo("password"' in source


def test_user_model_contract_allows_customer_role():
    source = _read("app/models/user.py")

    assert 'ALLOWED_ROLES = ("admin", "manager", "vendor", "customer")' in source


def test_admin_create_user_contract_sends_account_email_after_commit():
    source = _read("app/routes/admin_users.py")
    start = source.index("def create_user():")
    next_section = source.find("# ==================== GESTION BOUTIQUES", start)
    body = source[start: next_section if next_section != -1 else len(source)]

    assert "send_account_created_email(" in body
    assert body.index("db.session.commit()") < body.index("send_account_created_email(")
