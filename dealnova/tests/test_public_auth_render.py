from html.parser import HTMLParser
from pathlib import Path

import pytest
from flask import Flask, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from dealnova.app.routes.forms import LoginForm


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def find(self, tag, **attrs):
        return [value for name, value in self.tags if name == tag and all(value.get(key) == expected for key, expected in attrs.items())]


@pytest.fixture()
def auth_app():
    root = Path(__file__).resolve().parents[1]
    app = Flask("public-auth-render-tests")
    app.config.update(SECRET_KEY="test-auth-render-only", WTF_CSRF_ENABLED=True, SITE_NAME="BabaMarket")
    app.jinja_loader = ChoiceLoader([
        DictLoader({"base.html": "{% block head %}{% endblock %}{% block content %}{% endblock %}"}),
        FileSystemLoader(root / "app/templates"),
    ])
    app.jinja_env.globals.update(csrf_token=lambda: "recovery-csrf", app_static_version="test")
    for endpoint, path in {
        "auth.login": "/login", "auth.register": "/register", "auth.forgot_password": "/forgot-password",
        "auth.vendor_access": "/vendor-access", "auth.vendor_login": "/vendeur/login", "shop.home": "/shop/", "landing": "/",
    }.items():
        app.add_url_rule(path, endpoint, lambda: "")
    return app


@pytest.mark.parametrize("template,form_class,field_names", [
    ("login", LoginForm, ["email", "password"]),
])
def test_public_auth_forms_keep_post_csrf_labels_and_autocomplete(auth_app, template, form_class, field_names):
    with auth_app.test_request_context("/" + template):
        source = render_template(f"auth/{template}.html", form=form_class())
    elements = Elements(source)
    assert elements.find("form", method="POST") or elements.find("form", method="post")
    assert elements.find("input", name="csrf_token")
    for name in field_names:
        field = elements.find("input", name=name)[0]
        assert field["autocomplete"]
        assert elements.find("label", **{"for": field["id"]})
    assert elements.find("a", href="/vendor-access")


@pytest.mark.parametrize("template,form_class", [("login", LoginForm)])
def test_validation_errors_are_visible_and_associated_with_fields(auth_app, template, form_class):
    with auth_app.test_request_context("/" + template, method="POST", data={"email": "invalid"}):
        form = form_class()
        assert form.validate() is False
        source = render_template(f"auth/{template}.html", form=form)
    elements = Elements(source)
    email = elements.find("input", name="email")[0]
    assert email["aria-invalid"] == "true"
    error_id = email["aria-describedby"]
    assert elements.find("ul", id=error_id, role="alert")
    assert elements.find("input", name="password")[0]["type"] == "password"


def test_recovery_preserves_and_escapes_submitted_data_without_sending_anything(auth_app):
    with auth_app.test_request_context("/forgot-password", method="POST", data={
        "email": "client@example.test", "full_name": '<script>bad</script>', "note": '</textarea><script>bad</script>',
    }):
        source = render_template("auth/forgot_password.html", whatsapp_url=None, auto_open_whatsapp=False)
    elements = Elements(source)
    assert not elements.find("script")
    assert elements.find("input", name="csrf_token")
    assert elements.find("input", name="email")[0]["value"] == "client@example.test"
    assert elements.find("input", name="full_name")[0]["value"] == '<script>bad</script>'
    for tag, attrs in elements.tags:
        if tag in ("input", "textarea") and attrs.get("name") != "csrf_token":
            assert elements.find("label", **{"for": attrs["id"]})
