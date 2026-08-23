from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_catalog_version_reads_flask_cache_before_runtime_state():
    source = _read("app/services/cache.py")
    body = source.split("def _get_catalog_version() -> int:", 1)[1].split(
        "def bump_catalog_version() -> int:", 1
    )[0]

    assert body.index("cache.get(CATALOG_VERSION_KEY)") < body.index(
        "get_int_state(CATALOG_VERSION_KEY"
    )
    assert "cache.set(CATALOG_VERSION_KEY, shared_value" in body


def test_catalog_version_timeout_is_configurable():
    source = _read("app/config.py")
    cache_source = _read("app/services/cache.py")

    assert "CATALOG_VERSION_CACHE_TIMEOUT" in source
    assert "current_app.config.get(\"CATALOG_VERSION_CACHE_TIMEOUT\"" in cache_source
