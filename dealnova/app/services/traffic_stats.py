from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from flask import current_app, g, request
from flask_login import current_user

from .cache import cache
from .shared_state import get_json_state, mutate_json_states, set_json_state

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
        _increment_counter_bucket(
            ORDERS_BUCKETS_KEY,
            _orders_key(now),
            ORDERS_TTL_SECONDS,
            MAX_ORDER_COUNTER_BUCKETS,
        )
        track_custom_event("order_created", now=now)
    except Exception:
        return


def track_custom_event(event_name: str, now: datetime | None = None) -> None:
    safe_event = _safe_label(event_name, default="").lower()
    if safe_event not in ALLOWED_EVENTS:
        return

    current_dt = now or datetime.utcnow()
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
