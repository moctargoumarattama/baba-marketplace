from __future__ import annotations

import re
from typing import Any

from flask import current_app, request
from itsdangerous import BadData, URLSafeTimedSerializer


DEFAULT_COOKIE_NAME = "phone_remember"
DEFAULT_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 jours
DEFAULT_COOKIE_SALT = "phone-remember-v1"


def digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def get_order_phone_digits(order: Any) -> str:
    return digits_only(getattr(order, "phone_digits", None) or getattr(order, "phone", None))


def _cookie_name() -> str:
    return current_app.config.get("PHONE_REMEMBER_COOKIE_NAME", DEFAULT_COOKIE_NAME)


def _cookie_max_age() -> int:
    raw = current_app.config.get("PHONE_REMEMBER_MAX_AGE", DEFAULT_COOKIE_MAX_AGE)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_COOKIE_MAX_AGE
    return max(60, value)


def _serializer() -> URLSafeTimedSerializer:
    secret_key = current_app.config.get("SECRET_KEY") or "dev"
    salt = current_app.config.get("PHONE_REMEMBER_COOKIE_SALT", DEFAULT_COOKIE_SALT)
    return URLSafeTimedSerializer(secret_key=secret_key, salt=salt)


def read_phone_cookie_digits() -> str:
    raw_cookie = request.cookies.get(_cookie_name()) or ""
    if not raw_cookie:
        return ""

    try:
        payload = _serializer().loads(raw_cookie, max_age=_cookie_max_age())
    except BadData:
        return ""

    if isinstance(payload, dict):
        digits = digits_only(payload.get("phone_digits"))
    else:
        digits = digits_only(payload)

    return digits if len(digits) >= 6 else ""


def set_phone_cookie(response, phone_digits: str):
    digits = digits_only(phone_digits)
    if len(digits) < 6:
        return response

    token = _serializer().dumps({"phone_digits": digits})
    response.set_cookie(
        _cookie_name(),
        token,
        max_age=_cookie_max_age(),
        httponly=True,
        samesite=current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
        secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
    )
    return response


def input_matches_order_phone(order: Any, phone_input: str) -> bool:
    order_digits = get_order_phone_digits(order)
    entered_digits = digits_only(phone_input)

    if not order_digits or not entered_digits:
        return False

    if len(entered_digits) == 4:
        return order_digits.endswith(entered_digits)

    if len(entered_digits) < 6:
        return False

    return (
        entered_digits == order_digits
        or order_digits.endswith(entered_digits)
        or entered_digits.endswith(order_digits)
    )


def cookie_matches_order_phone(order: Any) -> bool:
    order_digits = get_order_phone_digits(order)
    cookie_digits = read_phone_cookie_digits()
    return bool(order_digits and cookie_digits and order_digits == cookie_digits)
