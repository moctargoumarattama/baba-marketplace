from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, session
from flask_login import LoginManager, current_user

from dealnova.app.extensions import db
from dealnova.app.models.user import User
from dealnova.app.routes import auth
from dealnova.app.services.auth_access import load_account_user


@pytest.fixture()
def guest_app(monkeypatch):
    app = Flask("guest-only-customers")
    app.config.update(TESTING=True, SECRET_KEY="guest-only-test", WTF_CSRF_ENABLED=False,
                      SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECURITY_RATE_LIMIT_ENABLED=False)
    db.init_app(app)
    manager = LoginManager(app)

    @manager.user_loader
    def load_user(uid):
        return load_account_user(db.session.get(User, int(uid)))

    app.register_blueprint(auth.bp)
    app.add_url_rule("/", "landing", lambda: "guest home")

    @app.route("/who")
    def who():
        from dealnova.app.routes.cart import get_cart
        return jsonify(authenticated=current_user.is_authenticated, cart=get_cart())

    monkeypatch.setattr(auth, "render_template", lambda template, **kwargs: jsonify(template=template))
    monkeypatch.setattr(auth.logging_service, "log_activity", lambda *a, **kw: None)
    monkeypatch.setattr(auth, "log_access", lambda *a, **kw: None)
    monkeypatch.setattr(auth, "track_custom_event", lambda *a, **kw: None)
    monkeypatch.setattr(auth, "send_account_created_email", lambda **kw: pytest.fail("Unexpected email"))
    with app.app_context():
        assert db.engine.url.database == ":memory:"
        db.create_all()
        users = {}
        for role in ("customer", "vendor", "admin", "manager"):
            user = User(username=role, email=role + "@example.com", role=role)
            user.set_password("GuestOnlyTest123")
            db.session.add(user)
            db.session.flush()
            users[role] = user.id
        db.session.commit()
        yield SimpleNamespace(app=app, client=app.test_client(), users=users)
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.mark.parametrize("method", ["get", "post"])
def test_old_registration_url_returns_home_without_creating_an_account(guest_app, method):
    count = User.query.count()
    with guest_app.client.session_transaction() as storage:
        storage["cart_guest"] = {"7": 2}
    response = getattr(guest_app.client, method)("/register", data={
        "full_name": "Visitor", "email": "new@example.com", "password": "GuestOnlyTest123",
        "password_confirm": "GuestOnlyTest123", "role": "vendor",
    })
    assert response.status_code == 303
    assert response.location == "/"
    assert User.query.count() == count
    with guest_app.client.session_transaction() as storage:
        assert storage["cart_guest"] == {"7": 2}


def test_old_customer_credentials_cannot_login_even_with_next_parameter(guest_app):
    user = db.session.get(User, guest_app.users["customer"])
    response = guest_app.client.post("/login?next=/staff", data={
        "email": user.email, "password": "GuestOnlyTest123",
    })
    assert response.status_code == 302
    assert response.location == "/"
    assert user.last_login is None
    with guest_app.client.session_transaction() as storage:
        assert "_user_id" not in storage


@pytest.mark.parametrize("role", ["vendor", "admin", "manager"])
def test_vendor_and_staff_login_still_work(guest_app, role):
    response = guest_app.client.post("/login?next=/staff", data={
        "email": role + "@example.com", "password": "GuestOnlyTest123",
    })
    assert response.status_code == 302
    assert response.location == "/staff"
    with guest_app.client.session_transaction() as storage:
        assert storage["_user_id"] == str(guest_app.users[role])


def test_existing_customer_session_becomes_guest_and_keeps_its_cart(guest_app):
    uid = guest_app.users["customer"]
    with guest_app.client.session_transaction() as storage:
        storage["_user_id"] = str(uid)
        storage["_fresh"] = True
        storage[f"cart_user_{uid}"] = {"7": 3, "8": 1}
        storage["cart_guest"] = {"7": 2, "9": 4}
    response = guest_app.client.get("/who")
    assert response.json == {"authenticated": False, "cart": {"7": 3, "8": 1, "9": 4}}
    with guest_app.client.session_transaction() as storage:
        assert "_user_id" not in storage
        assert f"cart_user_{uid}" not in storage
    assert db.session.get(User, uid) is not None


def test_remembered_customer_session_requests_cookie_removal(guest_app):
    with guest_app.app.test_request_context("/"):
        session["_user_id"] = str(guest_app.users["customer"])
        session["_remember"] = "set"
        assert load_account_user(db.session.get(User, guest_app.users["customer"])) is None
        assert session["_remember"] == "clear"
        assert "_user_id" not in session
