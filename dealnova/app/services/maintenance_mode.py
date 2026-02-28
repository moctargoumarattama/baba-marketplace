from __future__ import annotations

import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from ..extensions import db
from ..models.platform_settings import PlatformSettings

DEFAULT_MAINTENANCE_MESSAGE = "Maintenance technique en cours. Nous revenons bientot."
MAINTENANCE_CACHE_TTL_SECONDS = 5

_MAINTENANCE_CACHE_LOCK = Lock()
_MAINTENANCE_CACHE_VALUE: dict[str, Any] | None = None
_MAINTENANCE_CACHE_UNTIL = 0.0


def _safe_message(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    return cleaned[:2000]


def parse_maintenance_datetime(raw_value: str | None) -> datetime | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None

    candidates = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    # ISO fallback (handles timezone-aware values).
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise ValueError(f"Invalid datetime format: {value}") from exc


def format_maintenance_datetime(value: datetime | None) -> str:
    if not value:
        return "N/A"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _invalidate_maintenance_cache() -> None:
    global _MAINTENANCE_CACHE_VALUE, _MAINTENANCE_CACHE_UNTIL
    with _MAINTENANCE_CACHE_LOCK:
        _MAINTENANCE_CACHE_VALUE = None
        _MAINTENANCE_CACHE_UNTIL = 0.0


def _cache_get(now_ts: float) -> dict[str, Any] | None:
    with _MAINTENANCE_CACHE_LOCK:
        if _MAINTENANCE_CACHE_VALUE is None:
            return None
        if now_ts >= _MAINTENANCE_CACHE_UNTIL:
            return None
        return dict(_MAINTENANCE_CACHE_VALUE)


def _cache_set(value: dict[str, Any], now_ts: float) -> None:
    global _MAINTENANCE_CACHE_VALUE, _MAINTENANCE_CACHE_UNTIL
    with _MAINTENANCE_CACHE_LOCK:
        _MAINTENANCE_CACHE_VALUE = dict(value)
        _MAINTENANCE_CACHE_UNTIL = now_ts + MAINTENANCE_CACHE_TTL_SECONDS


def _state_from_settings(settings: PlatformSettings | None, now: datetime) -> dict[str, Any]:
    manual_enabled = bool(getattr(settings, "maintenance_enabled", False))
    starts_at = getattr(settings, "maintenance_starts_at", None) if settings else None
    ends_at = getattr(settings, "maintenance_ends_at", None) if settings else None
    message = getattr(settings, "maintenance_message", None) if settings else None
    enabled_at = getattr(settings, "maintenance_enabled_at", None) if settings else None

    scheduled_active = False
    if starts_at and ends_at:
        scheduled_active = starts_at <= now <= ends_at
    elif starts_at and not ends_at:
        scheduled_active = now >= starts_at
    elif ends_at and not starts_at:
        scheduled_active = now <= ends_at

    active = bool(manual_enabled or scheduled_active)
    return {
        "active": active,
        "manual_enabled": manual_enabled,
        "scheduled_active": scheduled_active,
        "message": message or DEFAULT_MAINTENANCE_MESSAGE,
        "enabled_at": enabled_at,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "available": True,
        "error": None,
    }


def get_maintenance_state(force_refresh: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now_dt = now or datetime.utcnow()
    now_ts = time.time()

    if not force_refresh:
        cached = _cache_get(now_ts)
        if cached is not None:
            return cached

    try:
        settings = PlatformSettings.query.order_by(PlatformSettings.id.asc()).first()
        state = _state_from_settings(settings, now_dt)
    except Exception as exc:
        state = {
            "active": False,
            "manual_enabled": False,
            "scheduled_active": False,
            "message": DEFAULT_MAINTENANCE_MESSAGE,
            "enabled_at": None,
            "starts_at": None,
            "ends_at": None,
            "available": False,
            "error": str(exc),
        }
        try:
            db.session.rollback()
        except Exception:
            pass

    _cache_set(state, now_ts)
    return dict(state)


def enable_maintenance_mode(message: str | None = None, at: datetime | None = None) -> dict[str, Any]:
    now = at or datetime.utcnow()
    settings = PlatformSettings.get()
    settings.maintenance_enabled = True
    settings.maintenance_enabled_at = now
    cleaned = _safe_message(message)
    if cleaned is not None:
        settings.maintenance_message = cleaned
    db.session.commit()
    _invalidate_maintenance_cache()
    return get_maintenance_state(force_refresh=True)


def disable_maintenance_mode() -> dict[str, Any]:
    settings = PlatformSettings.get()
    settings.maintenance_enabled = False
    db.session.commit()
    _invalidate_maintenance_cache()
    return get_maintenance_state(force_refresh=True)


def schedule_maintenance_mode(
    starts_at: datetime,
    ends_at: datetime,
    message: str | None = None,
) -> dict[str, Any]:
    if starts_at is None or ends_at is None:
        raise ValueError("Both starts_at and ends_at are required.")
    if ends_at <= starts_at:
        raise ValueError("End datetime must be after start datetime.")

    settings = PlatformSettings.get()
    settings.maintenance_starts_at = starts_at
    settings.maintenance_ends_at = ends_at
    cleaned = _safe_message(message)
    if cleaned is not None:
        settings.maintenance_message = cleaned
    db.session.commit()
    _invalidate_maintenance_cache()
    return get_maintenance_state(force_refresh=True)

