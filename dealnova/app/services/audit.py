from __future__ import annotations

from datetime import datetime
import hashlib
import ipaddress
import re
from typing import Any

from flask import current_app, request
from flask_login import current_user
from sqlalchemy.orm import sessionmaker

from ..extensions import db
from ..models.audit import AuditLog
from .cache import cache

_PHONE_RE = re.compile(r"\d")
_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
_SENSITIVE_KEY_RE = re.compile(
    r"(phone|mobile|tel|address|lat|lng|lon|coord|token|secret|password|email|ip|user[_-]?agent)",
    re.IGNORECASE,
)
_COORD_KEY_RE = re.compile(r"(lat|lng|lon|coord)", re.IGNORECASE)


def _hash_value(value: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY") or "dealnova")
    payload = f"{secret}|{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _mask_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return "***"
    suffix = digits[-4:]
    return f"***{suffix}"


def _mask_email(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or "@" not in raw:
        return "***"
    name, domain = raw.split("@", 1)
    keep = name[:1] if name else "*"
    return f"{keep}***@{domain}"


def _anonymize_ip(raw_ip: str | None) -> str:
    value = (raw_ip or "").strip()
    if not value:
        return "unknown"
    try:
        ip_obj = ipaddress.ip_address(value)
        if isinstance(ip_obj, ipaddress.IPv4Address):
            parts = value.split(".")
            return ".".join(parts[:3] + ["0"])
        exploded = ip_obj.exploded.split(":")
        return ":".join(exploded[:4]) + ":0000:0000:0000:0000"
    except ValueError:
        return f"h:{_hash_value(value)}"


def _anonymize_user_agent(user_agent: str | None) -> str | None:
    ua = (user_agent or "").strip()
    if not ua:
        return None
    # Keep a tiny fingerprint only, avoid storing full UA payload.
    return f"ua:{_hash_value(ua)}"


def _sanitize_change_value(key: str, value: Any) -> Any:
    key_name = str(key or "")
    if value is None:
        return None

    if isinstance(value, dict):
        return _sanitize_changes(value)
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_change_value(key_name, item) for item in value]

    string_value = str(value)

    if _COORD_KEY_RE.search(key_name):
        return f"coord:{_hash_value(string_value)}"
    if _SENSITIVE_KEY_RE.search(key_name):
        if "email" in key_name.lower() and _EMAIL_RE.match(string_value):
            return _mask_email(string_value)
        if _PHONE_RE.search(string_value):
            return _mask_phone(string_value)
        return f"h:{_hash_value(string_value)}"

    # Opportunistic masking on likely PII values even if key is generic.
    if _EMAIL_RE.match(string_value):
        return _mask_email(string_value)
    if len(string_value) >= 9 and len(_PHONE_RE.findall(string_value)) >= 8:
        return _mask_phone(string_value)

    return value


def _sanitize_changes(changes: dict[str, Any] | None) -> dict[str, Any]:
    if not changes:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in changes.items():
        sanitized[str(key)] = _sanitize_change_value(str(key), value)
    return sanitized


def _audit_payload(success: bool, changes: dict[str, Any] | None) -> dict[str, Any]:
    payload = {
        "ip": _anonymize_ip(request.remote_addr),
        "user_agent": _anonymize_user_agent(request.user_agent.string if request.user_agent else None),
        "success": bool(success),
        "timestamp": datetime.utcnow().isoformat(),
    }
    payload.update(_sanitize_changes(changes))
    return payload


def log_access(action, entity_type, entity_id, success=True, changes=None):
    """Best-effort audit logger isolated from main transaction."""
    payload = _audit_payload(success=success, changes=changes)

    log = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=payload,
    )

    audit_session = None
    try:
        bind = db.session.get_bind()
        audit_session = sessionmaker(bind=bind)()
        audit_session.add(log)
        audit_session.commit()
    except Exception:
        if audit_session is not None:
            try:
                audit_session.rollback()
            except Exception:
                pass
        try:
            current_app.logger.exception(
                "Audit log failed",
                extra={"action": action, "entity_type": entity_type, "entity_id": entity_id},
            )
        except Exception:
            pass
    finally:
        if audit_session is not None:
            try:
                audit_session.close()
            except Exception:
                pass


def log_view_order(order_id, source="admin", throttle_minutes=10):
    """Audit order views with throttle for public tracking flows."""
    actor = "guest"
    if current_user.is_authenticated:
        actor = getattr(current_user, "role", "user")

    if source in ("track_token", "guest"):
        try:
            ip_hash = _hash_value(request.remote_addr or "unknown")
            key = f"audit:view_order:{source}:{order_id}:{ip_hash}"
            if cache.get(key):
                return
            cache.set(key, True, timeout=throttle_minutes * 60)
        except Exception:
            pass

    log_access(
        "view_order",
        "order",
        order_id,
        success=True,
        changes={"actor": actor, "source": source},
    )
