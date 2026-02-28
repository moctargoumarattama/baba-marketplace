import json
import urllib.request
from datetime import datetime
from flask import current_app


def send_security_alert(message, meta=None, level="warning"):
    """Optionally send security alerts to a webhook."""
    url = current_app.config.get("SECURITY_ALERT_WEBHOOK_URL") or ""
    if not url:
        return False
    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "message": message,
        "meta": meta or {},
        "app": current_app.config.get("SITE_NAME", "DealNova"),
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        try:
            current_app.logger.exception("Security alert webhook failed")
        except Exception:
            pass
    return False
