import time
from functools import wraps
from flask import request, jsonify, flash, redirect, url_for, current_app

from ..services.cache import cache
from ..services.logging_service import logging_service
from ..services.alerts import send_security_alert


def _client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit(limit=10, window_seconds=60, key_prefix=None, key_func=None, methods=None):
    """Simple in-memory rate limiter backed by Flask-Caching."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # Si la méthode n'est pas dans la liste, on laisse passer
            if methods and request.method not in methods:
                return f(*args, **kwargs)
            
            # Si le rate limiting est désactivé globalement, on laisse passer
            if not current_app.config.get("SECURITY_RATE_LIMIT_ENABLED", True):
                return f(*args, **kwargs)

            # Identifier
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
            now = int(time.time())
            data = cache.get(key)

            if not data or not isinstance(data, dict) or data.get("reset", 0) < now:
                # Première requête ou cache expiré
                data = {"count": 0, "reset": now + window_seconds}

            # ✅ VERSION ÉQUILIBRÉE
            if data["count"] >= limit:
                # 1. On logue (pour toi)
                logging_service.log_activity(
                    "security",
                    "rate_limit_exceeded",
                    message=f"Rate limit exceeded on {endpoint} ({identifier})",
                    level="INFO",
                )
                
                # 2. Message clair
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({
                        "error": "rate_limited",
                        "message": f"Maximum {limit} requêtes par minute. Veuillez patienter.",
                        "retry_after": data["reset"] - now
                    }), 429
                
                flash(f"Maximum {limit} actions par minute. Merci de patienter.", "warning")
                return redirect(request.referrer or url_for("shop.home"))

            # ✅ Incrémentation normale
            data["count"] += 1
            cache.set(key, data, timeout=window_seconds)
            
            return f(*args, **kwargs)
        return wrapped
    return decorator