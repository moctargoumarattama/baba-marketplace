# app/services/cache.py
from flask import current_app, has_app_context
from flask_caching import Cache

from ..models.category import Category
from .shared_state import get_int_state, increment_int_state, set_int_state

cache = Cache()

CATALOG_VERSION_KEY = "catalog:version"


def _catalog_version_timeout() -> int:
    if not has_app_context():
        return 30
    try:
        return max(1, int(current_app.config.get("CATALOG_VERSION_CACHE_TIMEOUT", 30)))
    except Exception:
        return 30


def _get_catalog_version() -> int:
    try:
        cached_value = cache.get(CATALOG_VERSION_KEY)
        cached_int = int(cached_value)
        if cached_int > 0:
            return cached_int
    except Exception:
        pass

    try:
        shared_value = get_int_state(CATALOG_VERSION_KEY, default=1)
        if shared_value > 0:
            cache.set(CATALOG_VERSION_KEY, shared_value, timeout=_catalog_version_timeout())
            return shared_value
    except Exception:
        pass

    try:
        set_int_state(CATALOG_VERSION_KEY, 1)
    except Exception:
        pass
    cache.set(CATALOG_VERSION_KEY, 1, timeout=_catalog_version_timeout())
    return 1

def bump_catalog_version() -> int:
    try:
        new_val = increment_int_state(CATALOG_VERSION_KEY, delta=1, default=1)
        if new_val <= 1:
            new_val = set_int_state(CATALOG_VERSION_KEY, 2)
    except Exception:
        current = _get_catalog_version()
        new_val = current + 1
    cache.set(CATALOG_VERSION_KEY, new_val, timeout=_catalog_version_timeout())
    return new_val


def invalidate_category_cache() -> int:
    cache.delete("all_categories")
    return bump_catalog_version()

def get_catalog_cache(key: str, builder, timeout: int = 60):
    version = _get_catalog_version()
    cache_key = f"catalog:v{version}:{key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    data = builder()
    cache.set(cache_key, data, timeout=timeout)
    return data


def get_categories():
    """Retourne les categories avec cache versionne."""
    version = _get_catalog_version()
    cache_key = f"catalog:v{version}:all_categories"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = Category.query.all()
    cache.set(cache_key, data, timeout=3600)
    return data
