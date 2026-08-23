import importlib.util
import sys
from pathlib import Path

import dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _reload_config_module(monkeypatch):
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)
    module_name = "dealnova_test_config_runtime"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "app" / "config.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _clear_database_env(monkeypatch):
    for name in ("DATABASE_URL", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"):
        monkeypatch.delenv(name, raising=False)


def test_single_config_uses_sqlite_by_default_in_local_dev(monkeypatch):
    _clear_database_env(monkeypatch)

    config_module = _reload_config_module(monkeypatch)

    assert config_module.Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite:///")
    assert config_module.Config.SQLALCHEMY_ENGINE_OPTIONS == {
        "connect_args": {"timeout": 30},
    }


def test_single_config_builds_mysql_uri_from_explicit_env(monkeypatch):
    _clear_database_env(monkeypatch)
    monkeypatch.setenv("DB_USER", "demo_user")
    monkeypatch.setenv("DB_PASSWORD", "demo_pass")
    monkeypatch.setenv("DB_HOST", "db.example.test")
    monkeypatch.setenv("DB_NAME", "dealnova_prod")

    config_module = _reload_config_module(monkeypatch)

    assert (
        config_module.Config.SQLALCHEMY_DATABASE_URI
        == "mysql+pymysql://demo_user:demo_pass@db.example.test/dealnova_prod"
    )
    assert config_module.Config.SQLALCHEMY_ENGINE_OPTIONS["pool_pre_ping"] is True
    assert config_module.Config.SQLALCHEMY_ENGINE_OPTIONS["pool_size"] == 5


def test_single_config_normalizes_mysql_database_url(monkeypatch):
    _clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pass@db.example.test/dealnova")

    config_module = _reload_config_module(monkeypatch)

    assert (
        config_module.Config.SQLALCHEMY_DATABASE_URI
        == "mysql+pymysql://user:pass@db.example.test/dealnova"
    )


def test_cache_can_be_configured_for_local_redis_in_production(monkeypatch):
    _clear_database_env(monkeypatch)
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("CACHE_TYPE", "RedisCache")
    monkeypatch.setenv("CACHE_REDIS_URL", "redis://127.0.0.1:6379/0")

    config_module = _reload_config_module(monkeypatch)

    assert config_module.Config.CACHE_TYPE == "RedisCache"
    assert config_module.Config.CACHE_REDIS_URL == "redis://127.0.0.1:6379/0"
    assert config_module.Config.CACHE_KEY_PREFIX == "babamarket:"
    assert config_module.Config.STATIC_CACHE_MAX_AGE == 2592000
    assert config_module.Config.STATIC_UNVERSIONED_CACHE_MAX_AGE == 86400
