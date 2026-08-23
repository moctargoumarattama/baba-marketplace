from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import time
from datetime import datetime
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from flask import current_app, g, has_app_context, request
from flask_login import current_user

from .cache import cache
from .shared_state import get_json_state, mutate_json_states, set_json_state

try:
    import redis as redis_lib
except Exception:  # pragma: no cover - optional dependency fallback
    redis_lib = None

REQUESTS_PREFIX = "stats:requests:"
ORDERS_PREFIX = "stats:orders:"
REQUESTS_BUCKETS_KEY = "stats:request_buckets"
ORDERS_BUCKETS_KEY = "stats:order_buckets"

REQUESTS_TTL_SECONDS = 120
ORDERS_TTL_SECONDS = 7200
LIVE_METRICS_CACHE_TTL_SECONDS = 10
ACTIVE_TTL_SECONDS = 300
DAILY_STATS_TTL_SECONDS = 60 * 60 * 24 * 8
VISITOR_HISTORY_TTL_SECONDS = 60 * 60 * 24 * 180
LIFETIME_STATS_TTL_SECONDS = 60 * 60 * 24 * 365 * 10
MAX_ACTIVE_VISITORS = 5000
MAX_VISITOR_HISTORY_ENTRIES = 50000
MAX_DAILY_SEEN_ENTRIES = 25000
MAX_BUCKET_ENTRIES = 120
MAX_ACTIVE_AUTH_USERS = 8
MAX_REQUEST_COUNTER_BUCKETS = 180
MAX_ORDER_COUNTER_BUCKETS = 96

DAILY_STATS_PREFIX = "stats:daily:"
DAILY_SEEN_PREFIX = "stats:daily_seen:"
ACTIVE_VISITORS_KEY = "stats:active_visitors_map"
VISITOR_HISTORY_KEY = "stats:visitor_history"
LIFETIME_EVENTS_KEY = "stats:lifetime_events"

ALLOWED_EVENTS = {
    "page_view",
    "add_to_cart",
    "order_created",
    "whatsapp_open",
    "pwa_installed",
    "login_success",
}
INTERNAL_ROLES = {"admin", "manager", "vendor"}

_DIGITS_SEGMENT_RE = re.compile(r"/\d+(?=/|$)")
_TOKEN_SEGMENT_RE = re.compile(r"/[A-Za-z0-9_-]{20,}(?=/|$)")
_LIVE_METRICS_CACHE_LOCK = Lock()
_ANALYTICS_LOCK = Lock()
_LIVE_METRICS_CACHE_VALUE: dict[str, Any] | None = None
_LIVE_METRICS_CACHE_UNTIL = 0.0
_REDIS_CLIENT_CACHE: dict[str, Any] = {}
_REDIS_CLIENT_CACHE_LOCK = Lock()
_ANALYTICS_FLUSH_LOCK_KEY = "stats:analytics_flush_lock"
_ANALYTICS_LAST_FLUSH_KEY = "stats:analytics_last_flush_ts"
_REDIS_REQUESTS_BUCKETS_KEY = "stats:requests:buckets"
_REDIS_ORDERS_BUCKETS_KEY = "stats:orders:buckets"
_REDIS_DAILY_PREFIX = "stats:analytics:daily:"
_REDIS_ACTIVE_INDEX_KEY = "stats:active_visitors:index"
_REDIS_ACTIVE_META_PREFIX = "stats:active_visitors:data:"
_REDIS_VISITOR_HISTORY_KEY = "stats:visitor_history:index"
_REDIS_LIFETIME_EVENTS_KEY = "stats:lifetime_events"


def _minute_stamp(now: datetime | None = None) -> str:
    return (now or datetime.utcnow()).strftime("%Y%m%d-%H%M")


def _hour_stamp(now: datetime | None = None) -> str:
    return (now or datetime.utcnow()).strftime("%Y%m%d-%H")


def _day_stamp(now: datetime | None = None) -> str:
    return (now or datetime.utcnow()).strftime("%Y%m%d")


def _requests_key(now: datetime | None = None) -> str:
    return f"{REQUESTS_PREFIX}{_minute_stamp(now)}"


def _orders_key(now: datetime | None = None) -> str:
    return f"{ORDERS_PREFIX}{_hour_stamp(now)}"


def _daily_stats_key(now: datetime | None = None) -> str:
    return f"{DAILY_STATS_PREFIX}{_day_stamp(now)}"


def _daily_seen_key(now: datetime | None = None) -> str:
    return f"{DAILY_SEEN_PREFIX}{_day_stamp(now)}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_label(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text[:80]


def _analytics_redis_url() -> str | None:
    keys = ("CACHE_REDIS_URL", "REDIS_URL")
    for key in keys:
        try:
            if has_app_context():
                raw_value = current_app.config.get(key)
            else:
                raw_value = os.getenv(key)
        except Exception:
            raw_value = os.getenv(key)
        value = str(raw_value or "").strip()
        if value:
            return value
    return "redis://127.0.0.1:6379/0"


def _redis_client():
    if redis_lib is None:
        return None

    redis_url = _analytics_redis_url()
    if not redis_url:
        return None

    with _REDIS_CLIENT_CACHE_LOCK:
        cached = _REDIS_CLIENT_CACHE.get(redis_url)
        if cached is not None:
            return cached

        try:
            client = redis_lib.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
                health_check_interval=30,
            )
            client.ping()
        except Exception:
            return None

        _REDIS_CLIENT_CACHE[redis_url] = client
        return client


def _redis_hash_snapshot(client, key: str) -> dict[str, int]:
    try:
        raw = client.hgetall(key) or {}
    except Exception:
        return {}
    return {
        str(field): _safe_int(value, default=0)
        for field, value in raw.items()
    }


def _redis_sorted_set_snapshot(client, key: str, limit: int | None = None) -> dict[str, int]:
    try:
        if limit is None or limit <= 0:
            raw_items = client.zrange(key, 0, -1, withscores=True) or []
        else:
            raw_items = client.zrevrange(key, 0, limit - 1, withscores=True) or []
    except Exception:
        return {}
    snapshot: dict[str, int] = {}
    for member, score in raw_items:
        snapshot[str(member)] = _safe_int(score, default=0)
    return snapshot


def _redis_json_load(value: str | None, default_factory) -> dict[str, Any]:
    default_value = _default_dict(default_factory)
    if not value:
        return default_value
    try:
        payload = json.loads(value)
    except Exception:
        return default_value
    return payload if isinstance(payload, dict) else default_value


def _redis_json_dump(value: dict[str, Any]) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _redis_incr_bucket(client, key: str, field: str, ttl_seconds: int, max_entries: int | None = None) -> int:
    try:
        new_value = _safe_int(client.hincrby(key, field, 1), default=0)
        if ttl_seconds > 0:
            client.expire(key, int(ttl_seconds))
        if max_entries and max_entries > 0 and _safe_int(client.hlen(key), default=0) > max_entries:
            snapshot = _redis_hash_snapshot(client, key)
            if len(snapshot) > max_entries:
                overflow = len(snapshot) - max_entries
                to_remove = sorted(snapshot.items(), key=lambda item: (item[1], item[0]))[:overflow]
                if to_remove:
                    client.hdel(key, *[field_name for field_name, _ in to_remove])
        return new_value
    except Exception:
        return 0


def _redis_track_active_visitor(
    client,
    visitor_id: str,
    active_entry: dict[str, Any],
    now_ts: int,
) -> int:
    try:
        client.zadd(_REDIS_ACTIVE_INDEX_KEY, {visitor_id: now_ts})
        if ACTIVE_TTL_SECONDS > 0:
            client.expire(_REDIS_ACTIVE_INDEX_KEY, ACTIVE_TTL_SECONDS * 2)
            client.set(
                f"{_REDIS_ACTIVE_META_PREFIX}{visitor_id}",
                _redis_json_dump(active_entry),
                ex=ACTIVE_TTL_SECONDS * 2,
            )
        cutoff = now_ts - ACTIVE_TTL_SECONDS
        if cutoff > 0:
            client.zremrangebyscore(_REDIS_ACTIVE_INDEX_KEY, 0, cutoff)
        return _safe_int(client.zcard(_REDIS_ACTIVE_INDEX_KEY), default=0)
    except Exception:
        return 0


def _redis_track_visitor_history(client, visitor_id: str, now_ts: int) -> bool:
    try:
        existed = client.zscore(_REDIS_VISITOR_HISTORY_KEY, visitor_id) is not None
        client.zadd(_REDIS_VISITOR_HISTORY_KEY, {visitor_id: now_ts})
        if VISITOR_HISTORY_TTL_SECONDS > 0:
            client.expire(_REDIS_VISITOR_HISTORY_KEY, VISITOR_HISTORY_TTL_SECONDS)
        total = _safe_int(client.zcard(_REDIS_VISITOR_HISTORY_KEY), default=0)
        if total > MAX_VISITOR_HISTORY_ENTRIES:
            client.zremrangebyrank(
                _REDIS_VISITOR_HISTORY_KEY,
                0,
                total - MAX_VISITOR_HISTORY_ENTRIES - 1,
            )
        return not existed
    except Exception:
        return False


def _redis_daily_key(now: datetime | None = None) -> str:
    return f"{_REDIS_DAILY_PREFIX}{_day_stamp(now)}"


def _redis_daily_bucket_key(now: datetime | None, bucket_name: str) -> str:
    return f"{_redis_daily_key(now)}:{bucket_name}"


def _redis_snapshot_active_visitors(client) -> dict[str, Any]:
    try:
        now_ts = int(time.time())
        cutoff = now_ts - ACTIVE_TTL_SECONDS
        if cutoff > 0:
            client.zremrangebyscore(_REDIS_ACTIVE_INDEX_KEY, 0, cutoff)
        visitor_ids = client.zrevrange(_REDIS_ACTIVE_INDEX_KEY, 0, MAX_ACTIVE_VISITORS - 1) or []
        if not visitor_ids:
            return {
                "active_total": 0,
                "active_authenticated": 0,
                "active_guests": 0,
                "active_internal": 0,
                "active_clients": 0,
                "active_by_role": {},
                "active_authenticated_users": [],
            }
        pipe = client.pipeline()
        for visitor_id in visitor_ids:
            pipe.get(f"{_REDIS_ACTIVE_META_PREFIX}{visitor_id}")
        raw_entries = pipe.execute() or []
    except Exception:
        return {
            "active_total": 0,
            "active_authenticated": 0,
            "active_guests": 0,
            "active_internal": 0,
            "active_clients": 0,
            "active_by_role": {},
            "active_authenticated_users": [],
        }

    active_authenticated = 0
    active_guests = 0
    active_internal = 0
    active_clients = 0
    active_by_role: dict[str, int] = {}
    auth_users: list[dict[str, Any]] = []
    active_total = 0

    for raw_entry in raw_entries:
        payload = _redis_json_load(raw_entry, dict)
        if not payload:
            continue
        active_total += 1
        authenticated = bool(payload.get("authenticated"))
        role = _safe_label(payload.get("role"), default="guest") or "guest"
        active_by_role[role] = _safe_int(active_by_role.get(role), default=0) + 1
        if _is_internal_role(role):
            active_internal += 1
        else:
            active_clients += 1
        if authenticated:
            active_authenticated += 1
            auth_users.append(
                {
                    "label": _safe_label(payload.get("label"), default="Compte"),
                    "role": role,
                    "audience_scope": "interne" if _is_internal_role(role) else "client",
                    "last_seen_seconds_ago": max(0, now_ts - _safe_int(payload.get("last_seen_ts"), default=now_ts)),
                    "path": _safe_label(payload.get("path"), default="/"),
                    "city": _safe_label(payload.get("city"), default=""),
                    "device": _safe_label(payload.get("device"), default=""),
                }
            )
        else:
            active_guests += 1

    auth_users.sort(key=lambda item: item["last_seen_seconds_ago"])
    return {
        "active_total": active_total,
        "active_authenticated": active_authenticated,
        "active_guests": active_guests,
        "active_internal": active_internal,
        "active_clients": active_clients,
        "active_by_role": active_by_role,
        "active_authenticated_users": auth_users[:MAX_ACTIVE_AUTH_USERS],
    }


def _redis_active_visitors_map(client) -> dict[str, Any]:
    try:
        now_ts = int(time.time())
        cutoff = now_ts - ACTIVE_TTL_SECONDS
        if cutoff > 0:
            client.zremrangebyscore(_REDIS_ACTIVE_INDEX_KEY, 0, cutoff)
        visitor_ids = client.zrevrange(_REDIS_ACTIVE_INDEX_KEY, 0, MAX_ACTIVE_VISITORS - 1) or []
        if not visitor_ids:
            return {}
        pipe = client.pipeline()
        for visitor_id in visitor_ids:
            pipe.get(f"{_REDIS_ACTIVE_META_PREFIX}{visitor_id}")
        raw_entries = pipe.execute() or []
    except Exception:
        return {}

    payloads: dict[str, Any] = {}
    for visitor_id, raw_entry in zip(visitor_ids, raw_entries):
        payload = _redis_json_load(raw_entry, dict)
        if payload:
            payloads[str(visitor_id)] = payload
    return payloads


def _redis_snapshot_daily_stats(client, now: datetime | None = None) -> dict[str, Any]:
    current_dt = now or datetime.utcnow()
    stats_key = _redis_daily_key(current_dt)
    seen_key = _daily_seen_key(current_dt)
    try:
        raw_stats = client.hgetall(stats_key) or {}
        top_pages = _redis_hash_snapshot(client, f"{stats_key}:top_pages")
        top_sources = _redis_hash_snapshot(client, f"{stats_key}:top_sources")
        devices = _redis_hash_snapshot(client, f"{stats_key}:devices")
        cities = _redis_hash_snapshot(client, f"{stats_key}:cities")
        roles = _redis_hash_snapshot(client, f"{stats_key}:roles")
        hourly_requests = _redis_hash_snapshot(client, f"{stats_key}:hourly_requests")
        events = _redis_hash_snapshot(client, f"{stats_key}:events")
        visitor_history = _redis_sorted_set_snapshot(client, _REDIS_VISITOR_HISTORY_KEY)
        lifetime_events = _redis_hash_snapshot(client, _REDIS_LIFETIME_EVENTS_KEY)
        active_snapshot = _redis_snapshot_active_visitors(client)
        page_views_total = _safe_int(raw_stats.get("page_views_total"), default=0)
        unique_visitors_today = _safe_int(raw_stats.get("unique_visitors_today"), default=0)
        new_visitors_today = _safe_int(raw_stats.get("new_visitors_today"), default=0)
        returning_visitors_today = _safe_int(raw_stats.get("returning_visitors_today"), default=0)
        peak_active_today = max(
            _safe_int(raw_stats.get("peak_active_today"), default=0),
            _safe_int(active_snapshot.get("active_total"), default=0),
        )
        snapshot = {
            "page_views_total": page_views_total,
            "unique_visitors_today": unique_visitors_today,
            "new_visitors_today": new_visitors_today,
            "returning_visitors_today": returning_visitors_today,
            "peak_active_today": peak_active_today,
            "top_pages": top_pages,
            "top_sources": top_sources,
            "devices": devices,
            "cities": cities,
            "hourly_requests": hourly_requests or {f"{hour:02d}": 0 for hour in range(24)},
            "roles": roles,
            "events": events,
            "active_snapshot": active_snapshot,
            "visitor_history": visitor_history,
            "daily_seen_size": _safe_int(client.scard(seen_key), default=0),
            "lifetime_events": lifetime_events,
        }
    except Exception:
        snapshot = {
            "page_views_total": 0,
            "unique_visitors_today": 0,
            "new_visitors_today": 0,
            "returning_visitors_today": 0,
            "peak_active_today": 0,
            "top_pages": {},
            "top_sources": {},
            "devices": {},
            "cities": {},
            "hourly_requests": {f"{hour:02d}": 0 for hour in range(24)},
            "roles": {},
            "events": {},
            "active_snapshot": {
                "active_total": 0,
                "active_authenticated": 0,
                "active_guests": 0,
                "active_internal": 0,
                "active_clients": 0,
                "active_by_role": {},
                "active_authenticated_users": [],
            },
            "visitor_history": {},
            "daily_seen_size": 0,
            "lifetime_events": {},
        }
    return snapshot


def _redis_record_page_view(now: datetime | None = None) -> bool:
    client = _redis_client()
    if client is None:
        return False

    visitor_id = _visitor_id()
    if not visitor_id:
        return False

    current_dt = now or datetime.utcnow()
    now_ts = _now_ts(current_dt)
    current_path = _normalize_path(request.path or "/")
    source = _extract_referrer_source(request.referrer)
    device = _detect_device()
    city = _extract_city()
    role = _role_bucket()
    hour_key = current_dt.strftime("%H")
    daily_key = _redis_daily_key(current_dt)

    try:
        _redis_incr_bucket(client, _REDIS_REQUESTS_BUCKETS_KEY, _minute_stamp(current_dt), REQUESTS_TTL_SECONDS, MAX_REQUEST_COUNTER_BUCKETS)
        first_seen_today = bool(client.sadd(_daily_seen_key(current_dt), visitor_id))
        if DAILY_STATS_TTL_SECONDS > 0:
            client.expire(_daily_seen_key(current_dt), DAILY_STATS_TTL_SECONDS)
        is_new_visitor = _redis_track_visitor_history(client, visitor_id, now_ts)
        active_entry = {
            "last_seen_ts": now_ts,
            "authenticated": bool(current_user.is_authenticated),
            "role": role,
            "label": _visitor_display_label(),
            "user_id": getattr(current_user, "id", None) if current_user.is_authenticated else None,
            "device": device,
            "city": city,
            "path": current_path,
        }
        active_total = _redis_track_active_visitor(client, visitor_id, active_entry, now_ts)
        if first_seen_today:
            _redis_incr_bucket(client, daily_key, "unique_visitors_today", DAILY_STATS_TTL_SECONDS)
            if is_new_visitor:
                _redis_incr_bucket(client, daily_key, "new_visitors_today", DAILY_STATS_TTL_SECONDS)
            else:
                _redis_incr_bucket(client, daily_key, "returning_visitors_today", DAILY_STATS_TTL_SECONDS)
        _redis_incr_bucket(client, daily_key, "page_views_total", DAILY_STATS_TTL_SECONDS)
        _redis_incr_bucket(client, f"{daily_key}:top_pages", current_path, DAILY_STATS_TTL_SECONDS, MAX_BUCKET_ENTRIES)
        _redis_incr_bucket(client, f"{daily_key}:top_sources", source, DAILY_STATS_TTL_SECONDS, MAX_BUCKET_ENTRIES)
        _redis_incr_bucket(client, f"{daily_key}:devices", device, DAILY_STATS_TTL_SECONDS, MAX_BUCKET_ENTRIES)
        _redis_incr_bucket(client, f"{daily_key}:roles", role, DAILY_STATS_TTL_SECONDS, MAX_BUCKET_ENTRIES)
        if city:
            _redis_incr_bucket(client, f"{daily_key}:cities", city, DAILY_STATS_TTL_SECONDS, MAX_BUCKET_ENTRIES)
        _redis_incr_bucket(client, f"{daily_key}:hourly_requests", hour_key, DAILY_STATS_TTL_SECONDS, 24)
        _redis_incr_bucket(client, f"{daily_key}:events", "page_view", DAILY_STATS_TTL_SECONDS, len(ALLOWED_EVENTS))
        peak_key = "peak_active_today"
        try:
            current_peak = _safe_int(client.hget(daily_key, peak_key), default=0)
            if active_total > current_peak:
                client.hset(daily_key, peak_key, active_total)
            client.expire(daily_key, DAILY_STATS_TTL_SECONDS)
        except Exception:
            pass
        _redis_incr_bucket(client, _REDIS_LIFETIME_EVENTS_KEY, "page_view", LIFETIME_STATS_TTL_SECONDS, len(ALLOWED_EVENTS))
        return True
    except Exception:
        return False


def _redis_record_custom_event(event_name: str, now: datetime | None = None) -> bool:
    safe_event = _safe_label(event_name, default="").lower()
    if safe_event not in ALLOWED_EVENTS:
        return False

    client = _redis_client()
    if client is None:
        return False

    current_dt = now or datetime.utcnow()
    daily_key = _redis_daily_key(current_dt)
    try:
        _redis_incr_bucket(client, f"{daily_key}:events", safe_event, DAILY_STATS_TTL_SECONDS, len(ALLOWED_EVENTS))
        client.expire(daily_key, DAILY_STATS_TTL_SECONDS)
        if safe_event == "pwa_installed":
            _redis_incr_bucket(client, _REDIS_LIFETIME_EVENTS_KEY, "pwa_installed", LIFETIME_STATS_TTL_SECONDS, len(ALLOWED_EVENTS))
        return True
    except Exception:
        return False


def _redis_record_delivery_request_created(now: datetime | None = None) -> bool:
    client = _redis_client()
    if client is None:
        return False

    current_dt = now or datetime.utcnow()
    try:
        _redis_incr_bucket(client, _REDIS_ORDERS_BUCKETS_KEY, _hour_stamp(current_dt), ORDERS_TTL_SECONDS, MAX_ORDER_COUNTER_BUCKETS)
        _redis_record_custom_event("order_created", now=current_dt)
        return True
    except Exception:
        return False


def _redis_collect_sql_documents(now: datetime | None = None) -> dict[str, dict[str, Any]]:
    client = _redis_client()
    if client is None:
        return {}

    current_dt = now or datetime.utcnow()
    stats_key = _daily_stats_key(current_dt)
    return {
        REQUESTS_BUCKETS_KEY: _redis_hash_snapshot(client, _REDIS_REQUESTS_BUCKETS_KEY),
        ORDERS_BUCKETS_KEY: _redis_hash_snapshot(client, _REDIS_ORDERS_BUCKETS_KEY),
        ACTIVE_VISITORS_KEY: _redis_active_visitors_map(client),
        VISITOR_HISTORY_KEY: _redis_sorted_set_snapshot(client, _REDIS_VISITOR_HISTORY_KEY),
        LIFETIME_EVENTS_KEY: _redis_hash_snapshot(client, _REDIS_LIFETIME_EVENTS_KEY),
        stats_key: _redis_snapshot_daily_stats(client, current_dt),
    }


def _redis_live_metrics_snapshot(client, now: datetime | None = None) -> dict[str, Any]:
    current_dt = now or datetime.utcnow()
    daily_snapshot = _redis_snapshot_daily_stats(client, current_dt)
    request_bucket = _safe_int(
        client.hget(_REDIS_REQUESTS_BUCKETS_KEY, _minute_stamp(current_dt)),
        default=0,
    )
    orders_bucket = _safe_int(
        client.hget(_REDIS_ORDERS_BUCKETS_KEY, _hour_stamp(current_dt)),
        default=0,
    )
    active_snapshot = daily_snapshot.get("active_snapshot", {})
    unique_visitors_today = _safe_int(daily_snapshot.get("unique_visitors_today"), default=0)
    add_to_cart = _safe_int((daily_snapshot.get("events") or {}).get("add_to_cart"), default=0)
    orders = _safe_int((daily_snapshot.get("events") or {}).get("order_created"), default=0)
    whatsapp = _safe_int((daily_snapshot.get("events") or {}).get("whatsapp_open"), default=0)
    visitors = unique_visitors_today

    snapshot: dict[str, Any] = {
        "available": True,
        "rpm": request_bucket,
        "active_visitors_5m": _safe_int(active_snapshot.get("active_total"), default=0),
        "orders_per_hour": orders_bucket,
        "error": None,
        "active_authenticated_5m": _safe_int(active_snapshot.get("active_authenticated"), default=0),
        "active_guests_5m": _safe_int(active_snapshot.get("active_guests"), default=0),
        "active_by_role": active_snapshot.get("active_by_role", {}),
        "active_internal_5m": _safe_int(active_snapshot.get("active_internal"), default=0),
        "active_clients_5m": _safe_int(active_snapshot.get("active_clients"), default=0),
        "login_rate_active_pct": 0.0,
        "peak_active_today": _safe_int(daily_snapshot.get("peak_active_today"), default=0),
        "page_views_today": _safe_int(daily_snapshot.get("page_views_total"), default=0),
        "unique_visitors_today": unique_visitors_today,
        "new_visitors_today": _safe_int(daily_snapshot.get("new_visitors_today"), default=0),
        "returning_visitors_today": _safe_int(daily_snapshot.get("returning_visitors_today"), default=0),
        "top_pages": _sorted_bucket(daily_snapshot.get("top_pages", {}), limit=6),
        "top_sources": _sorted_bucket(daily_snapshot.get("top_sources", {}), limit=6),
        "hourly_heatmap": [
            {
                "hour": f"{hour:02d}h",
                "count": _safe_int((daily_snapshot.get("hourly_requests") or {}).get(f"{hour:02d}"), default=0),
            }
            for hour in range(24)
        ],
        "device_breakdown": _sorted_bucket(daily_snapshot.get("devices", {}), limit=4),
        "city_breakdown": _sorted_bucket(daily_snapshot.get("cities", {}), limit=6),
        "city_available": bool(daily_snapshot.get("cities")),
        "geo_debug_headers": _geo_debug_headers(),
        "detected_city_header": _extract_city(),
        "sessions_by_role": _sorted_bucket(daily_snapshot.get("roles", {}), limit=6),
        "sessions_internal_today": sum(
            _safe_int(value, default=0)
            for key, value in (daily_snapshot.get("roles", {}) or {}).items()
            if _is_internal_role(str(key))
        ),
        "sessions_clients_today": sum(
            _safe_int(value, default=0)
            for key, value in (daily_snapshot.get("roles", {}) or {}).items()
            if not _is_internal_role(str(key))
        ),
        "hourly_visits_24h": [
            {
                "hour": f"{hour:02d}h",
                "count": _safe_int((daily_snapshot.get("hourly_requests") or {}).get(f"{hour:02d}"), default=0),
                "label": f"De {hour:02d}h a {(hour + 1) % 24:02d}h",
            }
            for hour in range(24)
        ],
        "conversions": {
            "visitors": visitors,
            "add_to_cart": add_to_cart,
            "orders": orders,
            "whatsapp": whatsapp,
            "add_to_cart_rate_pct": round((add_to_cart / visitors) * 100, 1) if visitors else 0.0,
            "order_rate_pct": round((orders / visitors) * 100, 1) if visitors else 0.0,
            "whatsapp_rate_pct": round((whatsapp / visitors) * 100, 1) if visitors else 0.0,
        },
        "pwa_installs_today": _safe_int((daily_snapshot.get("events") or {}).get("pwa_installed"), default=0),
        "pwa_installs_total": _safe_int(
            (daily_snapshot.get("lifetime_events") or {}).get("pwa_installed"),
            default=0,
        ),
        "active_authenticated_users": active_snapshot.get("active_authenticated_users", []),
    }

    active_total = _safe_int(snapshot.get("active_visitors_5m"), default=0)
    active_authenticated = _safe_int(snapshot.get("active_authenticated_5m"), default=0)
    snapshot["login_rate_active_pct"] = round((active_authenticated / active_total) * 100, 1) if active_total else 0.0
    return snapshot


def _is_static_like(path: str, endpoint: str | None) -> bool:
    if endpoint and endpoint.endswith(".static"):
        return True
    if path.startswith("/static/"):
        return True
    return path in {"/health", "/favicon.ico", "/sw.js"}


def _is_background_request() -> bool:
    requested_with = (request.headers.get("X-Requested-With") or "").strip()
    accept = request.headers.get("Accept") or ""
    if requested_with in ("fetch", "XMLHttpRequest"):
        return True
    if request.is_json or "application/json" in accept:
        return True
    return False


def _extract_client_ip() -> str:
    x_forwarded_for = request.headers.get("X-Forwarded-For", "")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.remote_addr or ""


def _hash_ip(raw_ip: str) -> str:
    ip = (raw_ip or "").strip()
    if not ip:
        return ""
    secret = str(current_app.config.get("SECRET_KEY") or "dealnova")
    payload = f"{secret}|{ip}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:40]


def _hash_value(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    secret = str(current_app.config.get("SECRET_KEY") or "dealnova")
    payload = f"{secret}|{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:40]


def _trim_counter_buckets(bucket: dict[str, Any], max_entries: int) -> dict[str, int]:
    normalized = {
        str(key): _safe_int(value, default=0)
        for key, value in (bucket or {}).items()
    }
    if len(normalized) <= max_entries:
        return normalized
    ordered = sorted(normalized.items(), key=lambda item: item[0], reverse=True)[:max_entries]
    return {key: value for key, value in ordered}


def _increment_counter_bucket(
    state_key: str,
    bucket_key: str,
    ttl_seconds: int,
    max_entries: int,
) -> int:
    result = {"count": 0}

    def _mutate(payloads: dict[str, dict[str, Any]]) -> None:
        payload = _trim_counter_buckets(payloads.get(state_key, {}), max_entries)
        payload[bucket_key] = _safe_int(payload.get(bucket_key), default=0) + 1
        payloads[state_key] = _trim_counter_buckets(payload, max_entries)
        result["count"] = _safe_int(payloads[state_key].get(bucket_key), default=0)

    _mutate_durable_dicts(
        {state_key: dict},
        {state_key: max(ttl_seconds * 4, LIVE_METRICS_CACHE_TTL_SECONDS * 6)},
        _mutate,
    )
    return _safe_int(result.get("count"), default=0)


def _read_counter_bucket(state_key: str, bucket_key: str) -> int:
    payload = _load_durable_dict(state_key, dict)
    return _safe_int(payload.get(bucket_key), default=0)


def _default_dict(factory_or_value) -> dict[str, Any]:
    if callable(factory_or_value):
        value = factory_or_value()
    else:
        value = factory_or_value
    return value if isinstance(value, dict) else {}


def _load_cache_dict(key: str, default_factory) -> dict[str, Any]:
    payload = cache.get(key)
    if isinstance(payload, dict):
        return payload
    return _default_dict(default_factory)


def _load_durable_dict(key: str, default_factory) -> dict[str, Any]:
    try:
        payload = get_json_state(key, default_factory)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return _load_cache_dict(key, default_factory)


def _store_durable_dict(key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    try:
        set_json_state(key, value)
        return
    except Exception:
        pass
    cache.set(key, value, timeout=int(ttl_seconds))


def _mutate_durable_dicts(
    specs: dict[str, Any],
    ttl_seconds_by_key: dict[str, int],
    mutator,
) -> dict[str, dict[str, Any]]:
    try:
        return mutate_json_states(specs, mutator)
    except Exception:
        with _ANALYTICS_LOCK:
            payloads = {
                key: _load_cache_dict(key, default_factory)
                for key, default_factory in (specs or {}).items()
            }
            mutator(payloads)
            for key, value in payloads.items():
                cache.set(
                    key,
                    value,
                    timeout=int(ttl_seconds_by_key.get(key, DAILY_STATS_TTL_SECONDS)),
                )
            return payloads


def _now_ts(now: datetime | None = None) -> int:
    if now is None:
        return int(time.time())
    return int(now.timestamp())


def _normalize_path(path: str) -> str:
    cleaned = _safe_label(path or "/", default="/") or "/"
    cleaned = _DIGITS_SEGMENT_RE.sub("/:id", cleaned)
    cleaned = _TOKEN_SEGMENT_RE.sub("/:token", cleaned)
    return cleaned[:120]


def _extract_referrer_source(referrer: str | None) -> str:
    raw = (referrer or "").strip()
    if not raw:
        return "Direct"
    try:
        parsed = urlparse(raw)
    except Exception:
        return "Inconnue"
    host = (parsed.netloc or "").split(":", 1)[0].strip().lower()
    current_host = (request.host or "").split(":", 1)[0].strip().lower()
    if not host:
        return "Direct"
    if host == current_host:
        return "Interne"
    if host.startswith("www."):
        host = host[4:]
    return host[:80]


def _detect_device() -> str:
    ua = (request.headers.get("User-Agent") or "").lower()
    if not ua:
        return "inconnu"
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if any(token in ua for token in ("mobile", "android", "iphone", "ipod")):
        return "mobile"
    return "desktop"


def _extract_city() -> str:
    configured_headers = current_app.config.get("ANALYTICS_CITY_HEADERS") or (
        "CF-IPCity",
        "X-AppEngine-City",
        "X-City",
        "CloudFront-Viewer-City",
        "X-Geo-City",
    )
    for header in configured_headers:
        value = _safe_label(request.headers.get(header), default="")
        if value:
            return value.title()
    return ""


def _geo_debug_headers() -> list[dict[str, Any]]:
    configured_headers = current_app.config.get("ANALYTICS_CITY_HEADERS") or ()
    headers_to_check = list(configured_headers) + [
        "CF-Connecting-IP",
        "True-Client-IP",
        "X-Forwarded-For",
        "X-Real-IP",
        "CF-IPCountry",
        "CF-Ray",
    ]
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for header in headers_to_check:
        label = _safe_label(header, default="")
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        rows.append(
            {
                "label": label,
                "value": _safe_label(request.headers.get(label), default=""),
                "present": bool(request.headers.get(label)),
            }
        )
    return rows


def _role_bucket() -> str:
    if current_user.is_authenticated:
        role = _safe_label(getattr(current_user, "role", ""), default="client").lower()
        return role or "client"
    return "guest"


def _is_internal_role(role: str) -> bool:
    return _safe_label(role, default="guest").lower() in INTERNAL_ROLES


def _visitor_id() -> str:
    candidate = _safe_label(getattr(g, "analytics_visitor_id", ""), default="")
    if candidate:
        return candidate
    cookie_value = _safe_label(request.cookies.get("bm_vid"), default="")
    if cookie_value:
        return cookie_value
    ip_hash = _hash_ip(_extract_client_ip())
    return f"ip:{ip_hash}" if ip_hash else ""


def _visitor_display_label() -> str:
    if current_user.is_authenticated:
        for attr in ("username", "email"):
            value = _safe_label(getattr(current_user, attr, ""), default="")
            if value:
                return value
        return f"User #{getattr(current_user, 'id', '?')}"
    return "Invite"


def _fresh_daily_stats() -> dict[str, Any]:
    return {
        "page_views_total": 0,
        "unique_visitors_today": 0,
        "new_visitors_today": 0,
        "returning_visitors_today": 0,
        "peak_active_today": 0,
        "top_pages": {},
        "top_sources": {},
        "devices": {},
        "cities": {},
        "hourly_requests": {f"{hour:02d}": 0 for hour in range(24)},
        "roles": {},
        "events": {event_name: 0 for event_name in ALLOWED_EVENTS},
    }


def _bucket_inc(bucket: dict[str, int], key: str, amount: int = 1) -> None:
    label = _safe_label(key, default="")
    if not label:
        return
    if label not in bucket and len(bucket) >= MAX_BUCKET_ENTRIES:
        return
    bucket[label] = _safe_int(bucket.get(label), default=0) + int(amount)


def _sorted_bucket(bucket: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    items: list[tuple[str, int]] = []
    for key, value in (bucket or {}).items():
        count = _safe_int(value, default=0)
        if count <= 0:
            continue
        items.append((str(key), count))
    items.sort(key=lambda item: (-item[1], item[0]))
    return [{"label": label, "count": count} for label, count in items[:limit]]


def _cleanup_active_visitors(active_visitors: dict[str, Any], now_ts: int) -> dict[str, Any]:
    cutoff = now_ts - ACTIVE_TTL_SECONDS
    cleaned: dict[str, Any] = {}
    for key, payload in (active_visitors or {}).items():
        if not isinstance(payload, dict):
            continue
        last_seen_ts = _safe_int(payload.get("last_seen_ts"), default=0)
        if last_seen_ts < cutoff:
            continue
        cleaned[str(key)] = payload
    if len(cleaned) > MAX_ACTIVE_VISITORS:
        ordered = sorted(
            cleaned.items(),
            key=lambda item: _safe_int((item[1] or {}).get("last_seen_ts"), default=0),
            reverse=True,
        )[:MAX_ACTIVE_VISITORS]
        cleaned = {key: value for key, value in ordered}
    return cleaned


def _touch_active_visitor(now: datetime | None = None) -> int:
    visitor_id = _visitor_id()
    if not visitor_id:
        return 0

    now_ts = _now_ts(now)
    role = _role_bucket()
    active_entry = {
        "last_seen_ts": now_ts,
        "authenticated": bool(current_user.is_authenticated),
        "role": role,
        "label": _visitor_display_label(),
        "user_id": getattr(current_user, "id", None) if current_user.is_authenticated else None,
        "device": _detect_device(),
        "city": _extract_city(),
        "path": _normalize_path(request.path or "/"),
    }

    result = {"count": 0}

    def _mutate(payloads: dict[str, dict[str, Any]]) -> None:
        active_visitors = _cleanup_active_visitors(
            payloads.get(ACTIVE_VISITORS_KEY, {}),
            now_ts,
        )
        active_visitors[visitor_id] = active_entry
        payloads[ACTIVE_VISITORS_KEY] = active_visitors
        result["count"] = len(active_visitors)

    _mutate_durable_dicts(
        {ACTIVE_VISITORS_KEY: dict},
        {ACTIVE_VISITORS_KEY: ACTIVE_TTL_SECONDS * 2},
        _mutate,
    )
    return _safe_int(result.get("count"), default=0)


def _active_snapshot(now: datetime | None = None) -> dict[str, Any]:
    now_ts = _now_ts(now)
    active_visitors = _load_durable_dict(ACTIVE_VISITORS_KEY, dict)
    cleaned = _cleanup_active_visitors(active_visitors, now_ts)
    if cleaned != active_visitors:
        _store_durable_dict(ACTIVE_VISITORS_KEY, cleaned, ACTIVE_TTL_SECONDS * 2)

    active_total = len(cleaned)
    active_authenticated = 0
    active_guests = 0
    active_internal = 0
    active_clients = 0
    active_by_role: dict[str, int] = {}
    auth_users: list[dict[str, Any]] = []

    for payload in cleaned.values():
        authenticated = bool(payload.get("authenticated"))
        role = _safe_label(payload.get("role"), default="guest") or "guest"
        active_by_role[role] = _safe_int(active_by_role.get(role), default=0) + 1
        if _is_internal_role(role):
            active_internal += 1
        else:
            active_clients += 1
        if authenticated:
            active_authenticated += 1
            auth_users.append(
                {
                    "label": _safe_label(payload.get("label"), default="Compte"),
                    "role": role,
                    "audience_scope": "interne" if _is_internal_role(role) else "client",
                    "last_seen_seconds_ago": max(0, now_ts - _safe_int(payload.get("last_seen_ts"), default=now_ts)),
                    "path": _safe_label(payload.get("path"), default="/"),
                    "city": _safe_label(payload.get("city"), default=""),
                    "device": _safe_label(payload.get("device"), default=""),
                }
            )
        else:
            active_guests += 1

    auth_users.sort(key=lambda item: item["last_seen_seconds_ago"])
    return {
        "active_total": active_total,
        "active_authenticated": active_authenticated,
        "active_guests": active_guests,
        "active_internal": active_internal,
        "active_clients": active_clients,
        "active_by_role": active_by_role,
        "active_authenticated_users": auth_users[:MAX_ACTIVE_AUTH_USERS],
    }


def _record_daily_page_view(now: datetime | None = None, active_total: int | None = None) -> None:
    visitor_id = _visitor_id()
    if not visitor_id:
        return

    current_dt = now or datetime.utcnow()
    now_ts = _now_ts(current_dt)
    day_key = _day_stamp(current_dt)
    stats_key = _daily_stats_key(current_dt)
    seen_key = _daily_seen_key(current_dt)
    current_path = _normalize_path(request.path or "/")
    source = _extract_referrer_source(request.referrer)
    device = _detect_device()
    city = _extract_city()
    role = _role_bucket()
    hour_key = current_dt.strftime("%H")

    def _mutate(payloads: dict[str, dict[str, Any]]) -> None:
        stats = payloads.get(stats_key, _fresh_daily_stats())
        seen_today = payloads.get(seen_key, {})
        visitor_history = payloads.get(VISITOR_HISTORY_KEY, {})

        first_seen_today = visitor_id not in seen_today
        is_new_visitor = visitor_id not in visitor_history

        if first_seen_today:
            stats["unique_visitors_today"] = _safe_int(stats.get("unique_visitors_today"), default=0) + 1
            if is_new_visitor:
                stats["new_visitors_today"] = _safe_int(stats.get("new_visitors_today"), default=0) + 1
            else:
                stats["returning_visitors_today"] = _safe_int(stats.get("returning_visitors_today"), default=0) + 1
            seen_today[visitor_id] = now_ts

        visitor_history[visitor_id] = now_ts
        if len(visitor_history) > MAX_VISITOR_HISTORY_ENTRIES:
            ordered_history = sorted(visitor_history.items(), key=lambda item: _safe_int(item[1]), reverse=True)
            visitor_history = dict(ordered_history[:MAX_VISITOR_HISTORY_ENTRIES])

        if len(seen_today) > MAX_DAILY_SEEN_ENTRIES:
            ordered_seen = sorted(seen_today.items(), key=lambda item: _safe_int(item[1]), reverse=True)
            seen_today = dict(ordered_seen[:MAX_DAILY_SEEN_ENTRIES])

        stats["page_views_total"] = _safe_int(stats.get("page_views_total"), default=0) + 1
        _bucket_inc(stats.setdefault("top_pages", {}), current_path)
        _bucket_inc(stats.setdefault("top_sources", {}), source)
        _bucket_inc(stats.setdefault("devices", {}), device)
        _bucket_inc(stats.setdefault("roles", {}), role)
        if city:
            _bucket_inc(stats.setdefault("cities", {}), city)
        hourly_requests = stats.setdefault("hourly_requests", {f"{hour:02d}": 0 for hour in range(24)})
        hourly_requests[hour_key] = _safe_int(hourly_requests.get(hour_key), default=0) + 1
        events = stats.setdefault("events", {event_name: 0 for event_name in ALLOWED_EVENTS})
        events["page_view"] = _safe_int(events.get("page_view"), default=0) + 1
        if active_total is not None:
            stats["peak_active_today"] = max(
                _safe_int(stats.get("peak_active_today"), default=0),
                _safe_int(active_total, default=0),
            )
        payloads[stats_key] = stats
        payloads[seen_key] = seen_today
        payloads[VISITOR_HISTORY_KEY] = visitor_history

    _mutate_durable_dicts(
        {
            stats_key: _fresh_daily_stats,
            seen_key: dict,
            VISITOR_HISTORY_KEY: dict,
        },
        {
            stats_key: DAILY_STATS_TTL_SECONDS,
            seen_key: DAILY_STATS_TTL_SECONDS,
            VISITOR_HISTORY_KEY: VISITOR_HISTORY_TTL_SECONDS,
        },
        _mutate,
    )
    _live_metrics_cache_set(None, time.time())
    _live_metrics_cache_invalidate()


def _live_metrics_cache_get(now_ts: float) -> dict[str, Any] | None:
    with _LIVE_METRICS_CACHE_LOCK:
        if _LIVE_METRICS_CACHE_VALUE is None:
            return None
        if now_ts >= _LIVE_METRICS_CACHE_UNTIL:
            return None
        return dict(_LIVE_METRICS_CACHE_VALUE)


def _live_metrics_cache_set(value: dict[str, Any] | None, now_ts: float) -> None:
    global _LIVE_METRICS_CACHE_VALUE, _LIVE_METRICS_CACHE_UNTIL
    with _LIVE_METRICS_CACHE_LOCK:
        if value is None:
            _LIVE_METRICS_CACHE_VALUE = None
            _LIVE_METRICS_CACHE_UNTIL = 0.0
            return
        _LIVE_METRICS_CACHE_VALUE = dict(value)
        _LIVE_METRICS_CACHE_UNTIL = now_ts + LIVE_METRICS_CACHE_TTL_SECONDS


def _live_metrics_cache_invalidate() -> None:
    _live_metrics_cache_set(None, time.time())


def _update_lifetime_event(event_name: str, amount: int = 1) -> None:
    def _mutate(payloads: dict[str, dict[str, Any]]) -> None:
        payload = payloads.get(LIFETIME_EVENTS_KEY, {})
        payload[event_name] = _safe_int(payload.get(event_name), default=0) + int(amount)
        payloads[LIFETIME_EVENTS_KEY] = payload

    _mutate_durable_dicts(
        {LIFETIME_EVENTS_KEY: dict},
        {LIFETIME_EVENTS_KEY: LIFETIME_STATS_TTL_SECONDS},
        _mutate,
    )


def track_request_hit(path: str | None = None, endpoint: str | None = None) -> None:
    try:
        current_path = path or (request.path or "")
        current_endpoint = endpoint or request.endpoint
        if (
            not current_path
            or _is_static_like(current_path, current_endpoint)
            or _is_background_request()
        ):
            return

        now = datetime.utcnow()
        client = _redis_client()
        if client is not None:
            if _redis_record_page_view(now):
                _live_metrics_cache_invalidate()
            return

        if _redis_record_page_view(now):
            _live_metrics_cache_invalidate()
            return
        _increment_counter_bucket(
            REQUESTS_BUCKETS_KEY,
            _requests_key(now),
            REQUESTS_TTL_SECONDS,
            MAX_REQUEST_COUNTER_BUCKETS,
        )
        active_total = _touch_active_visitor(now)
        _record_daily_page_view(now, active_total=active_total)
    except Exception:
        return


def track_delivery_request_created(now: datetime | None = None) -> None:
    try:
        current_dt = now or datetime.utcnow()
        client = _redis_client()
        if client is not None:
            if _redis_record_delivery_request_created(current_dt):
                _live_metrics_cache_invalidate()
            return

        if _redis_record_delivery_request_created(current_dt):
            _live_metrics_cache_invalidate()
            return
        _increment_counter_bucket(
            ORDERS_BUCKETS_KEY,
            _orders_key(current_dt),
            ORDERS_TTL_SECONDS,
            MAX_ORDER_COUNTER_BUCKETS,
        )
        track_custom_event("order_created", now=current_dt)
    except Exception:
        return


def track_custom_event(event_name: str, now: datetime | None = None) -> None:
    safe_event = _safe_label(event_name, default="").lower()
    if safe_event not in ALLOWED_EVENTS:
        return

    current_dt = now or datetime.utcnow()
    client = _redis_client()
    if client is not None:
        if _redis_record_custom_event(safe_event, current_dt):
            _live_metrics_cache_invalidate()
        return

    if _redis_record_custom_event(safe_event, current_dt):
        _live_metrics_cache_invalidate()
        return
    stats_key = _daily_stats_key(current_dt)

    def _mutate(payloads: dict[str, dict[str, Any]]) -> None:
        stats = payloads.get(stats_key, _fresh_daily_stats())
        events = stats.setdefault("events", {name: 0 for name in ALLOWED_EVENTS})
        events[safe_event] = _safe_int(events.get(safe_event), default=0) + 1
        payloads[stats_key] = stats

    _mutate_durable_dicts(
        {stats_key: _fresh_daily_stats},
        {stats_key: DAILY_STATS_TTL_SECONDS},
        _mutate,
    )

    if safe_event == "pwa_installed":
        _update_lifetime_event("pwa_installed", amount=1)

    _live_metrics_cache_invalidate()


def _load_daily_stats(now: datetime) -> dict[str, Any]:
    return _load_durable_dict(_daily_stats_key(now), _fresh_daily_stats)


def get_live_traffic_metrics(now: datetime | None = None) -> dict[str, Any]:
    if now is None:
        cached = _live_metrics_cache_get(time.time())
        if cached is not None:
            return cached

    current_dt = now or datetime.utcnow()
    redis_client = _redis_client()
    if redis_client is not None:
        try:
            snapshot = _redis_live_metrics_snapshot(redis_client, current_dt)
            if now is None:
                _live_metrics_cache_set(snapshot, time.time())
            return snapshot
        except Exception:
            pass

    snapshot: dict[str, Any] = {
        "available": True,
        "rpm": None,
        "active_visitors_5m": None,
        "orders_per_hour": None,
        "error": None,
        "active_authenticated_5m": 0,
        "active_guests_5m": 0,
        "active_by_role": {},
        "active_internal_5m": 0,
        "active_clients_5m": 0,
        "login_rate_active_pct": 0.0,
        "peak_active_today": 0,
        "page_views_today": 0,
        "unique_visitors_today": 0,
        "new_visitors_today": 0,
        "returning_visitors_today": 0,
        "top_pages": [],
        "top_sources": [],
        "hourly_heatmap": [],
        "device_breakdown": [],
        "city_breakdown": [],
        "city_available": False,
        "geo_debug_headers": [],
        "detected_city_header": "",
        "sessions_by_role": [],
        "sessions_internal_today": 0,
        "sessions_clients_today": 0,
        "hourly_visits_24h": [],
        "conversions": {
            "visitors": 0,
            "add_to_cart": 0,
            "orders": 0,
            "whatsapp": 0,
            "add_to_cart_rate_pct": 0.0,
            "order_rate_pct": 0.0,
            "whatsapp_rate_pct": 0.0,
        },
        "pwa_installs_today": 0,
        "pwa_installs_total": 0,
        "active_authenticated_users": [],
    }

    try:
        snapshot["rpm"] = _read_counter_bucket(REQUESTS_BUCKETS_KEY, _requests_key(current_dt))
    except Exception as exc:
        snapshot["error"] = str(exc)

    try:
        active_snapshot = _active_snapshot(current_dt)
        snapshot["active_visitors_5m"] = active_snapshot["active_total"]
        snapshot["active_authenticated_5m"] = active_snapshot["active_authenticated"]
        snapshot["active_guests_5m"] = active_snapshot["active_guests"]
        snapshot["active_by_role"] = active_snapshot["active_by_role"]
        snapshot["active_internal_5m"] = active_snapshot["active_internal"]
        snapshot["active_clients_5m"] = active_snapshot["active_clients"]
        snapshot["active_authenticated_users"] = active_snapshot["active_authenticated_users"]
    except Exception as exc:
        snapshot["error"] = str(exc)

    try:
        snapshot["orders_per_hour"] = _read_counter_bucket(ORDERS_BUCKETS_KEY, _orders_key(current_dt))
    except Exception as exc:
        snapshot["error"] = str(exc)

    try:
        stats = _load_daily_stats(current_dt)
        visitors = _safe_int(stats.get("unique_visitors_today"), default=0)
        add_to_cart = _safe_int((stats.get("events") or {}).get("add_to_cart"), default=0)
        orders = _safe_int((stats.get("events") or {}).get("order_created"), default=0)
        whatsapp = _safe_int((stats.get("events") or {}).get("whatsapp_open"), default=0)
        snapshot["peak_active_today"] = _safe_int(stats.get("peak_active_today"), default=0)
        snapshot["page_views_today"] = _safe_int(stats.get("page_views_total"), default=0)
        snapshot["unique_visitors_today"] = visitors
        snapshot["new_visitors_today"] = _safe_int(stats.get("new_visitors_today"), default=0)
        snapshot["returning_visitors_today"] = _safe_int(stats.get("returning_visitors_today"), default=0)
        snapshot["top_pages"] = _sorted_bucket(stats.get("top_pages", {}), limit=6)
        snapshot["top_sources"] = _sorted_bucket(stats.get("top_sources", {}), limit=6)
        snapshot["device_breakdown"] = _sorted_bucket(stats.get("devices", {}), limit=4)
        snapshot["city_breakdown"] = _sorted_bucket(stats.get("cities", {}), limit=6)
        snapshot["city_available"] = len(snapshot["city_breakdown"]) > 0
        snapshot["geo_debug_headers"] = _geo_debug_headers()
        snapshot["detected_city_header"] = _extract_city()
        snapshot["sessions_by_role"] = _sorted_bucket(stats.get("roles", {}), limit=6)
        snapshot["sessions_internal_today"] = sum(
            _safe_int(value, default=0)
            for key, value in (stats.get("roles", {}) or {}).items()
            if _is_internal_role(str(key))
        )
        snapshot["sessions_clients_today"] = sum(
            _safe_int(value, default=0)
            for key, value in (stats.get("roles", {}) or {}).items()
            if not _is_internal_role(str(key))
        )
        snapshot["pwa_installs_today"] = _safe_int((stats.get("events") or {}).get("pwa_installed"), default=0)
        snapshot["hourly_heatmap"] = [
            {
                "hour": f"{hour:02d}h",
                "count": _safe_int((stats.get("hourly_requests") or {}).get(f"{hour:02d}"), default=0),
            }
            for hour in range(24)
        ]
        snapshot["hourly_visits_24h"] = [
            {
                "hour": f"{hour:02d}h",
                "count": _safe_int((stats.get("hourly_requests") or {}).get(f"{hour:02d}"), default=0),
                "label": f"De {hour:02d}h à {(hour + 1) % 24:02d}h",
            }
            for hour in range(24)
        ]
        snapshot["conversions"] = {
            "visitors": visitors,
            "add_to_cart": add_to_cart,
            "orders": orders,
            "whatsapp": whatsapp,
            "add_to_cart_rate_pct": round((add_to_cart / visitors) * 100, 1) if visitors else 0.0,
            "order_rate_pct": round((orders / visitors) * 100, 1) if visitors else 0.0,
            "whatsapp_rate_pct": round((whatsapp / visitors) * 100, 1) if visitors else 0.0,
        }
    except Exception as exc:
        snapshot["error"] = str(exc)

    try:
        lifetime_events = _load_durable_dict(LIFETIME_EVENTS_KEY, dict)
        snapshot["pwa_installs_total"] = _safe_int(
            lifetime_events.get("pwa_installed"),
            default=0,
        )
    except Exception as exc:
        snapshot["error"] = str(exc)

    active_total = _safe_int(snapshot.get("active_visitors_5m"), default=0)
    active_authenticated = _safe_int(snapshot.get("active_authenticated_5m"), default=0)
    snapshot["login_rate_active_pct"] = round((active_authenticated / active_total) * 100, 1) if active_total else 0.0

    if (
        snapshot["rpm"] is None
        and snapshot["active_visitors_5m"] is None
        and snapshot["orders_per_hour"] is None
    ):
        snapshot["available"] = False

    if now is None:
        _live_metrics_cache_set(snapshot, time.time())

    return snapshot


def _redis_release_lock(client, lock_key: str, token: str) -> None:
    try:
        client.eval(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0",
            1,
            lock_key,
            token,
        )
    except Exception:
        pass


def flush_traffic_analytics_to_sql(force: bool = False, now: datetime | None = None) -> dict[str, Any]:
    client = _redis_client()
    if client is None:
        return {"flushed": False, "reason": "redis_unavailable"}

    if not force and not bool(current_app.config.get("ANALYTICS_FLUSH_ENABLED", True)):
        return {"flushed": False, "reason": "disabled"}

    current_dt = now or datetime.utcnow()
    now_ts = _now_ts(current_dt)
    min_interval = max(5, _safe_int(current_app.config.get("ANALYTICS_FLUSH_MIN_INTERVAL_SECONDS", 60), default=60))
    lock_seconds = max(min_interval, _safe_int(current_app.config.get("ANALYTICS_FLUSH_LOCK_SECONDS", 20), default=20))

    try:
        last_flush_ts = _safe_int(client.get(_ANALYTICS_LAST_FLUSH_KEY), default=0)
        if not force and last_flush_ts and (now_ts - last_flush_ts) < min_interval:
            return {"flushed": False, "reason": "not_due", "last_flush_ts": last_flush_ts}
    except Exception:
        last_flush_ts = 0

    token = secrets.token_urlsafe(16)
    lock_acquired = False
    try:
        lock_acquired = bool(client.set(_ANALYTICS_FLUSH_LOCK_KEY, token, nx=True, ex=lock_seconds))
        if not lock_acquired:
            return {"flushed": False, "reason": "locked"}

        docs = _redis_collect_sql_documents(current_dt)
        if not docs:
            return {"flushed": False, "reason": "empty"}

        stats_key = _daily_stats_key(current_dt)
        specs: dict[str, Any] = {
            REQUESTS_BUCKETS_KEY: dict,
            ORDERS_BUCKETS_KEY: dict,
            ACTIVE_VISITORS_KEY: dict,
            VISITOR_HISTORY_KEY: dict,
            LIFETIME_EVENTS_KEY: dict,
            stats_key: _fresh_daily_stats,
        }
        ttl_seconds_by_key = {
            REQUESTS_BUCKETS_KEY: REQUESTS_TTL_SECONDS,
            ORDERS_BUCKETS_KEY: ORDERS_TTL_SECONDS,
            ACTIVE_VISITORS_KEY: ACTIVE_TTL_SECONDS * 2,
            VISITOR_HISTORY_KEY: VISITOR_HISTORY_TTL_SECONDS,
            LIFETIME_EVENTS_KEY: LIFETIME_STATS_TTL_SECONDS,
            stats_key: DAILY_STATS_TTL_SECONDS,
        }

        def _mutate(payloads: dict[str, Any]) -> None:
            for key, value in docs.items():
                payloads[key] = value

        _mutate_durable_dicts(specs, ttl_seconds_by_key, _mutate)
        client.set(_ANALYTICS_LAST_FLUSH_KEY, str(now_ts), ex=max(min_interval * 2, lock_seconds * 2))
        _live_metrics_cache_invalidate()
        return {"flushed": True, "keys": sorted(docs.keys())}
    except Exception as exc:
        return {"flushed": False, "reason": "error", "error": str(exc)}
    finally:
        if lock_acquired:
            _redis_release_lock(client, _ANALYTICS_FLUSH_LOCK_KEY, token)
