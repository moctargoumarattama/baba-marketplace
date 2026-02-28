from __future__ import annotations

import hashlib
import time
from datetime import datetime
from threading import Lock
from typing import Any

from flask import current_app, request

from .cache import cache

REQUESTS_PREFIX = "stats:requests:"
ACTIVE_PREFIX = "stats:active:"
ORDERS_PREFIX = "stats:orders:"
ACTIVE_INDEX_KEY = "stats:active_index"

REQUESTS_TTL_SECONDS = 120
ACTIVE_TTL_SECONDS = 300
ACTIVE_INDEX_TTL_SECONDS = 600
ORDERS_TTL_SECONDS = 7200
MAX_ACTIVE_INDEX_ENTRIES = 5000

_ACTIVE_INDEX_LOCK = Lock()
_REDIS_CLIENT_LOCK = Lock()
_REDIS_CLIENT_CACHE: Any = "__unknown__"


def _minute_stamp(now: datetime | None = None) -> str:
    return (now or datetime.utcnow()).strftime("%Y%m%d-%H%M")


def _hour_stamp(now: datetime | None = None) -> str:
    return (now or datetime.utcnow()).strftime("%Y%m%d-%H")


def _requests_key(now: datetime | None = None) -> str:
    return f"{REQUESTS_PREFIX}{_minute_stamp(now)}"


def _orders_key(now: datetime | None = None) -> str:
    return f"{ORDERS_PREFIX}{_hour_stamp(now)}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_static_like(path: str, endpoint: str | None) -> bool:
    if endpoint and endpoint.endswith(".static"):
        return True
    if path.startswith("/static/"):
        return True
    return path in {"/health", "/favicon.ico", "/sw.js"}


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


def _resolve_redis_client() -> Any | None:
    backend = getattr(cache, "cache", None)
    if backend is None:
        return None

    for attr in ("_write_client", "_read_client", "_client", "client"):
        client = getattr(backend, attr, None)
        if client is None or callable(client):
            continue
        if hasattr(client, "incr") and hasattr(client, "setex"):
            return client

    if hasattr(backend, "incr") and hasattr(backend, "set"):
        return None
    return None


def _redis_client() -> Any | None:
    global _REDIS_CLIENT_CACHE
    with _REDIS_CLIENT_LOCK:
        if _REDIS_CLIENT_CACHE == "__unknown__":
            _REDIS_CLIENT_CACHE = _resolve_redis_client()
        return _REDIS_CLIENT_CACHE or None


def _cache_increment(key: str, ttl_seconds: int) -> int:
    redis_client = _redis_client()
    if redis_client is not None:
        try:
            value = redis_client.incr(key, 1)
            redis_client.expire(key, int(ttl_seconds))
            return _safe_int(value, default=0)
        except Exception:
            pass

    try:
        cache.add(key, 0, timeout=int(ttl_seconds))
    except Exception:
        pass

    try:
        value = cache.inc(key, 1)
        if value is not None:
            cache.set(key, _safe_int(value), timeout=int(ttl_seconds))
            return _safe_int(value)
    except Exception:
        pass

    current = _safe_int(cache.get(key), default=0) + 1
    cache.set(key, current, timeout=int(ttl_seconds))
    return current


def _cache_read_counter(key: str) -> int:
    redis_client = _redis_client()
    if redis_client is not None:
        try:
            value = redis_client.get(key)
            return _safe_int(value, default=0)
        except Exception:
            pass
    return _safe_int(cache.get(key), default=0)


def _touch_active_key(ip_hash: str) -> None:
    if not ip_hash:
        return

    redis_client = _redis_client()
    if redis_client is not None:
        redis_client.setex(f"{ACTIVE_PREFIX}{ip_hash}", ACTIVE_TTL_SECONDS, int(time.time()))
        return

    now_ts = int(time.time())
    cutoff = now_ts - ACTIVE_TTL_SECONDS

    with _ACTIVE_INDEX_LOCK:
        active_index = cache.get(ACTIVE_INDEX_KEY)
        if not isinstance(active_index, dict):
            active_index = {}

        cleaned_index = {}
        for key, ts in active_index.items():
            ts_value = _safe_int(ts, default=0)
            if ts_value >= cutoff:
                cleaned_index[str(key)] = ts_value

        cleaned_index[ip_hash] = now_ts

        if len(cleaned_index) > MAX_ACTIVE_INDEX_ENTRIES:
            keep = sorted(cleaned_index.items(), key=lambda item: item[1], reverse=True)[:MAX_ACTIVE_INDEX_ENTRIES]
            cleaned_index = {k: v for k, v in keep}

        cache.set(ACTIVE_INDEX_KEY, cleaned_index, timeout=ACTIVE_INDEX_TTL_SECONDS)


def _count_active_visitors() -> int:
    redis_client = _redis_client()
    if redis_client is not None:
        pattern = f"{ACTIVE_PREFIX}*"
        count = 0
        if hasattr(redis_client, "scan_iter"):
            for _ in redis_client.scan_iter(match=pattern, count=200):
                count += 1
            return count

        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=200)
            count += len(keys or [])
            if cursor in (0, "0", b"0"):
                break
        return count

    now_ts = int(time.time())
    cutoff = now_ts - ACTIVE_TTL_SECONDS

    with _ACTIVE_INDEX_LOCK:
        active_index = cache.get(ACTIVE_INDEX_KEY)
        if not isinstance(active_index, dict):
            return 0

        cleaned_index = {}
        for key, ts in active_index.items():
            ts_value = _safe_int(ts, default=0)
            if ts_value >= cutoff:
                cleaned_index[str(key)] = ts_value

        if cleaned_index != active_index:
            cache.set(ACTIVE_INDEX_KEY, cleaned_index, timeout=ACTIVE_INDEX_TTL_SECONDS)
        return len(cleaned_index)


def track_request_hit(path: str | None = None, endpoint: str | None = None) -> None:
    try:
        current_path = path or (request.path or "")
        current_endpoint = endpoint or request.endpoint
        if not current_path or _is_static_like(current_path, current_endpoint):
            return

        now = datetime.utcnow()
        _cache_increment(_requests_key(now), REQUESTS_TTL_SECONDS)
        _touch_active_key(_hash_ip(_extract_client_ip()))
    except Exception:
        # Best effort only.
        return


def track_order_created(now: datetime | None = None) -> None:
    try:
        _cache_increment(_orders_key(now), ORDERS_TTL_SECONDS)
    except Exception:
        return


def get_live_traffic_metrics(now: datetime | None = None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "available": True,
        "rpm": None,
        "active_visitors_5m": None,
        "orders_per_hour": None,
        "error": None,
    }
    current_dt = now or datetime.utcnow()

    try:
        snapshot["rpm"] = _cache_read_counter(_requests_key(current_dt))
    except Exception as exc:
        snapshot["error"] = str(exc)

    try:
        snapshot["active_visitors_5m"] = _count_active_visitors()
    except Exception as exc:
        snapshot["error"] = str(exc)

    try:
        snapshot["orders_per_hour"] = _cache_read_counter(_orders_key(current_dt))
    except Exception as exc:
        snapshot["error"] = str(exc)

    if (
        snapshot["rpm"] is None
        and snapshot["active_visitors_5m"] is None
        and snapshot["orders_per_hour"] is None
    ):
        snapshot["available"] = False

    return snapshot
