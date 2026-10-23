from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..middleware.rate_limit import rate_limit
from .engine import assistant_bootstrap, assistant_reply, assistant_welcome

bp = Blueprint("assistant_api", __name__, url_prefix="/api/assistant")


@bp.app_context_processor
def inject_assistant_welcome():
    return {"assistant_welcome": assistant_welcome}


@bp.after_request
def prevent_conversation_caching(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.route("/bootstrap", methods=["GET"])
@rate_limit(limit=120, window_seconds=3600, key_prefix="assistant_bootstrap_hour", methods=("GET",))
@rate_limit(limit=30, window_seconds=60, key_prefix="assistant_bootstrap_minute", methods=("GET",))
def bootstrap():
    return jsonify({"ok": True, "response": assistant_bootstrap()})


@bp.route("/message", methods=["GET", "POST"])
@rate_limit(limit=300, window_seconds=3600, key_prefix="assistant_message_hour", methods=("GET", "POST"))
@rate_limit(limit=60, window_seconds=60, key_prefix="assistant_message_minute", methods=("GET", "POST"))
def message():
    payload = request.get_json(silent=True) if request.method == "POST" else {}
    payload = payload or {}

    message_text = (
        payload.get("message")
        if request.method == "POST"
        else request.args.get("message", "")
    )
    action = payload.get("action") if request.method == "POST" else request.args.get("action")
    value = payload.get("value") if request.method == "POST" else request.args.get("value")
    fresh = payload.get("fresh") if request.method == "POST" else request.args.get("fresh")

    response = assistant_reply(
        message=str(message_text or "")[:300],
        action=str(action or "")[:40] or None,
        value=str(value or "")[:80] or None,
        fresh=str(fresh or "").lower() in {"1", "true"},
    )
    return jsonify({"ok": True, "response": response})
