import time
from functools import wraps
from threading import Lock

from flask import current_app, flash, jsonify, redirect, request, url_for

from ..services.cache import cache
from ..services.logging_service import logging_service
from ..services.shared_state import mutate_json_states


_FALLBACK_RATE_LIMIT_LOCK = Lock()


def _client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _window_label(window_seconds):
    if window_seconds == 60:
        return "minute"
    if window_seconds == 3600:
        return "heure"
    if window_seconds == 86400:
        return "jour"
    return f"{int(window_seconds)} secondes"


def _normalize_bucket(payload):
    if not isinstance(payload, dict):
        return {"count": 0, "reset": 0}
    try:
        count = max(0, int(payload.get("count", 0) or 0))
    except (TypeError, ValueError):
        count = 0
    try:
        reset = max(0, int(payload.get("reset", 0) or 0))
    except (TypeError, ValueError):
        reset = 0
    return {"count": count, "reset": reset}


def _consume_rate_slot_shared(key, limit, window_seconds, now):
    result = {"allowed": True, "retry_after": 0}

    def _mutate(payloads):
        bucket = _normalize_bucket(payloads.get(key))
        if bucket["reset"] < now:
            bucket = {"count": 0, "reset": now + int(window_seconds)}

        if bucket["count"] >= int(limit):
            result["allowed"] = False
            result["retry_after"] = max(0, int(bucket["reset"]) - int(now))
            payloads[key] = bucket
            return

        bucket["count"] += 1
        payloads[key] = bucket
        result["allowed"] = True
        result["retry_after"] = 0

    mutate_json_states({key: dict}, _mutate)
    return bool(result["allowed"]), int(result["retry_after"])


def _consume_rate_slot_cache(key, limit, window_seconds, now):
    with _FALLBACK_RATE_LIMIT_LOCK:
        bucket = _normalize_bucket(cache.get(key))
        if bucket["reset"] < now:
            bucket = {"count": 0, "reset": now + int(window_seconds)}

        if bucket["count"] >= int(limit):
            cache.set(key, bucket, timeout=max(1, int(window_seconds)))
            return False, max(0, int(bucket["reset"]) - int(now))

        bucket["count"] += 1
        cache.set(key, bucket, timeout=max(1, int(window_seconds)))
        return True, 0


def _consume_rate_slot(key, limit, window_seconds):
    now = int(time.time())
    try:
        return _consume_rate_slot_shared(key, limit, window_seconds, now)
    except Exception:
        return _consume_rate_slot_cache(key, limit, window_seconds, now)


def rate_limit(limit=10, window_seconds=60, key_prefix=None, key_func=None, methods=None):
    """Shared rate limiter backed by runtime_state with cache fallback."""

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if methods and request.method not in methods:
                return f(*args, **kwargs)

            if not current_app.config.get("SECURITY_RATE_LIMIT_ENABLED", True):
                return f(*args, **kwargs)

            identifier = None
            if key_func:
                try:
                    identifier = key_func()
                except Exception:
                    identifier = None
            if not identifier:
                identifier = _client_ip()

            endpoint = request.endpoint or f.__name__
            key = f"rate:{key_prefix or endpoint}:{identifier}"
            allowed, retry_after = _consume_rate_slot(key, limit, window_seconds)

            if not allowed:
                logging_service.log_activity(
                    "security",
                    "rate_limit_exceeded",
                    message=f"Rate limit exceeded on {endpoint} ({identifier})",
                    level="INFO",
                )

                window_label = _window_label(window_seconds)
                is_api_request = (request.path or "").startswith("/api/")
                if is_api_request or request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify(
                        {
                            "error": "rate_limited",
                            "message": f"Maximum {limit} requetes par {window_label}. Veuillez patienter.",
                            "retry_after": retry_after,
                        }
                    ), 429

                flash(f"Maximum {limit} actions par {window_label}. Merci de patienter.", "warning")
                return redirect(request.referrer or url_for("shop.home"))

            return f(*args, **kwargs)

        return wrapped

    return decorator
