from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask, jsonify, render_template
from flask_login import LoginManager
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

from dealnova.app.routes import auth


@pytest.fixture()
def help_app(monkeypatch):
    app = Flask("public-help-tests")
    app.config.update(TESTING=True, SECRET_KEY="help-test", SUPPORT_WHATSAPP_NUMBER="+212 600 000 001")
    manager = LoginManager(app)
    manager.user_loader(lambda _uid: None)
    app.register_blueprint(auth.bp)
    app.add_url_rule("/", "landing", lambda: "home")
    app.add_url_rule("/shop/", "shop.home", lambda: "catalogue")
    monkeypatch.setattr(auth, "render_template", lambda template, **context: jsonify(template=template, **context))
    return app


@pytest.mark.parametrize("role", [None, "customer", "vendor", "admin", "manager"])
def test_public_help_is_accessible_without_role_redirect(help_app, monkeypatch, role):
    monkeypatch.setattr(auth, "current_user", SimpleNamespace(is_authenticated=role is not None, role=role))

    response = help_app.test_client().get("/support/help")

    assert response.status_code == 200
    assert "Location" not in response.headers
    data = response.get_json()
    link = urlparse(data["wa_url"])
    assert link.scheme == "https"
    assert link.netloc == "wa.me"
    assert link.path == "/212600000001"
    assert "contacter le support BabaMarket" in parse_qs(link.query)["text"][0]
    assert data["support_title"] == "Support"
    assert data["auto_open_whatsapp"] is False
    assert data["back_url"] == "/"


@pytest.mark.parametrize("role", ["vendor", "admin", "manager"])
def test_client_issue_reporting_keeps_its_existing_role_restriction(help_app, monkeypatch, role):
    monkeypatch.setattr(auth, "current_user", SimpleNamespace(is_authenticated=True, role=role))

    response = help_app.test_client().get("/support/whatsapp")

    assert response.status_code == 302
    assert response.location == "/shop/"


@pytest.mark.parametrize("auto_open", [False, True, None])
def test_support_template_only_auto_opens_when_requested(auto_open):
    app = Flask("help-template-test")
    app.config["SITE_NAME"] = "BabaMarket"
    app.jinja_loader = ChoiceLoader([
        DictLoader({"base.html": "{% block head %}{% endblock %}{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).resolve().parents[1] / "app/templates"),
    ])
    context = {"wa_url": "https://wa.me/212600000001?text=Bonjour"}
    if auto_open is not None:
        context["auto_open_whatsapp"] = auto_open
    with app.test_request_context("/support/help"):
        source = render_template("support/open_whatsapp.html", **context)

    assert 'id="supportWaLink"' in source
    assert 'target="_blank"' in source
    assert ("window.location.href = link.href" in source) is (auto_open is not False)
