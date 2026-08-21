import os
import ast
import operator as op
import subprocess
import datetime
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # dossier app/
ENV_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", ".env"))

if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)


def _get_static_version():
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        return git_hash
    except Exception:
        return datetime.datetime.utcnow().strftime("%Y%m%d%H%M")


class Config:
    @staticmethod
    def _env_bool(name, default=False):
        val = os.getenv(name)
        if val is None:
            return default
        return str(val).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _safe_num_eval(expr: str):
        allowed = {
            ast.Add: op.add,
            ast.Sub: op.sub,
            ast.Mult: op.mul,
            ast.Div: op.truediv,
            ast.FloorDiv: op.floordiv,
        }

        def _eval(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.Num):
                return node.n
            if isinstance(node, ast.BinOp) and type(node.op) in allowed:
                return allowed[type(node.op)](_eval(node.left), _eval(node.right))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                val = _eval(node.operand)
                return +val if isinstance(node.op, ast.UAdd) else -val
            raise ValueError("unsupported expression")

        try:
            return _eval(ast.parse(expr, mode="eval").body)
        except Exception:
            return None

    ENV = os.getenv("FLASK_ENV", "production").lower()
    DEBUG = _env_bool("DEBUG", False)
    APP_STATIC_VERSION = os.getenv("APP_STATIC_VERSION", _get_static_version())
    UI_HOME_TABS_ENABLED = _env_bool("UI_HOME_TABS_ENABLED", True)

    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    if ENV == "production" and (
        not SECRET_KEY or SECRET_KEY.strip().lower() in ("dev", "secret", "password", "123456")
    ):
        print("[WARN] SECRET_KEY faible ou manquant en production. Définis une SECRET_KEY forte.")

    # =========================
    # Database (MySQL only)
    # =========================
    DB_USER = os.getenv("DB_USER", "FORLIFE")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_HOST = os.getenv("DB_HOST", "FORLIFE.mysql.pythonanywhere-services.com")
    DB_NAME = os.getenv("DB_NAME", "FORLIFE$default")

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "").strip()

    if not SQLALCHEMY_DATABASE_URI:
        if not DB_PASSWORD:
            raise ValueError("DATABASE_URL ou DB_PASSWORD manquant pour configurer MySQL.")
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
        )

    if SQLALCHEMY_DATABASE_URI.startswith("mysql://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "mysql://",
            "mysql+pymysql://",
            1,
        )

    if not SQLALCHEMY_DATABASE_URI.startswith("mysql+pymysql://"):
        raise ValueError(
            f"Configuration invalide: MySQL requis. URL reçue: {SQLALCHEMY_DATABASE_URI}"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_timeout": 30,
        "pool_size": 5,
        "max_overflow": 10,
    }

    # =========================
    # Branding / Business rules
    # =========================
    SITE_NAME = os.getenv("SITE_NAME", "Baba Market")
    SITE_LOGO = os.getenv("SITE_LOGO", "")
    PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or os.getenv("SITE_URL") or "").strip().rstrip("/")
    DELIVERY_WHATSAPP_NUMBER = os.getenv("DELIVERY_WHATSAPP_NUMBER", "212602908954")
    DELIVERY_WHATSAPP_DEFAULT_MESSAGE = os.getenv(
        "DELIVERY_WHATSAPP_DEFAULT_MESSAGE",
        "Bonjour, je souhaite programmer une livraison. Merci de me confirmer la disponibilite et le delai.",
    )
    ASSISTANT_DELIVERY_HOURS_TEXT = os.getenv(
        "ASSISTANT_DELIVERY_HOURS_TEXT",
        "Livraison disponible tous les jours de 8h a 3h du matin, selon disponibilite du livreur.",
    )
    ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+212770010264")
    SUPPORT_WHATSAPP_NUMBER = os.getenv("SUPPORT_WHATSAPP_NUMBER", ADMIN_PHONE)
    RENTAL_VISIT_WHATSAPP_NUMBER = os.getenv("RENTAL_VISIT_WHATSAPP_NUMBER", "212602908954")
    VENDOR_PUSH_VAPID_PUBLIC_KEY = os.getenv("VENDOR_PUSH_VAPID_PUBLIC_KEY", os.getenv("VAPID_PUBLIC_KEY", ""))
    VENDOR_PUSH_VAPID_PRIVATE_KEY = os.getenv("VENDOR_PUSH_VAPID_PRIVATE_KEY", os.getenv("VAPID_PRIVATE_KEY", ""))
    VENDOR_PUSH_VAPID_EMAIL = os.getenv("VENDOR_PUSH_VAPID_EMAIL", os.getenv("ADMIN_EMAIL", "admin@babamarket.local"))

    _upload_folder_env = os.getenv("UPLOAD_FOLDER", "app/static/uploads")
    if os.path.isabs(_upload_folder_env):
        UPLOAD_FOLDER = _upload_folder_env
    else:
        UPLOAD_FOLDER = os.path.abspath(os.path.join(BASE_DIR, "..", _upload_folder_env))

    DEFAULT_LANG = os.getenv("DEFAULT_LANG", "fr")
    LANGUAGES = ["fr", "en", "ary"]
    LANG_COOKIE_NAME = os.getenv("LANG_COOKIE_NAME", "lang")
    LANG_COOKIE_MAX_AGE = int(os.getenv("LANG_COOKIE_MAX_AGE", "63072000"))
    LANG_COOKIE_SAMESITE = os.getenv("LANG_COOKIE_SAMESITE", "Lax")
    LANG_COOKIE_SECURE = _env_bool("LANG_COOKIE_SECURE", ENV == "production")
    RTL_LANGUAGES = [
        lang.strip()
        for lang in os.getenv("RTL_LANGUAGES", "ary").split(",")
        if lang.strip()
    ]

    CACHE_TYPE = os.getenv("CACHE_TYPE", "SimpleCache")
    CACHE_DEFAULT_TIMEOUT = int(os.getenv("CACHE_DEFAULT_TIMEOUT", "3600"))
    CACHE_DIR = os.getenv(
        "CACHE_DIR",
        os.path.abspath(os.path.join(BASE_DIR, "..", "instance", "flask_cache")),
    )
    CACHE_THRESHOLD = int(os.getenv("CACHE_THRESHOLD", "10000"))
    CACHE_IGNORE_ERRORS = _env_bool("CACHE_IGNORE_ERRORS", True)
    LOG_LEVEL = (os.getenv("LOG_LEVEL", "INFO") or "INFO").strip().upper()
    LOG_FILE_MAX_BYTES = int(os.getenv("LOG_FILE_MAX_BYTES", str(5 * 1024 * 1024)))
    LOG_FILE_BACKUP_COUNT = int(os.getenv("LOG_FILE_BACKUP_COUNT", "7"))

    try:
        MAX_LIMIT = max(1, int(os.getenv("MAX_LIMIT", "50")))
    except ValueError:
        MAX_LIMIT = 50

    # =========================
    # Session / security
    # =========================
    SESSION_COOKIE_HTTPONLY = True

    _samesite = (os.getenv("SESSION_COOKIE_SAMESITE", "Lax") or "Lax").strip()
    _samesite_cap = _samesite[:1].upper() + _samesite[1:].lower()
    SESSION_COOKIE_SAMESITE = (
        _samesite_cap if _samesite_cap in ("Lax", "Strict", "None") else "Lax"
    )

    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", ENV == "production")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    PERMANENT_SESSION_LIFETIME = int(os.getenv("PERMANENT_SESSION_LIFETIME", "21600"))
    WTF_CSRF_TIME_LIMIT = int(os.getenv("WTF_CSRF_TIME_LIMIT", "3600"))
    PREFERRED_URL_SCHEME = "https" if ENV == "production" else "http"

    SECURITY_HEADERS_ENABLED = _env_bool("SECURITY_HEADERS_ENABLED", True)
    SECURITY_HSTS_ENABLED = _env_bool("SECURITY_HSTS_ENABLED", ENV == "production")
    SECURITY_HSTS_TRUST_X_FORWARDED_PROTO = _env_bool(
        "SECURITY_HSTS_TRUST_X_FORWARDED_PROTO",
        ENV == "production",
    )
    SECURITY_CSP_ENABLED = _env_bool("SECURITY_CSP_ENABLED", True)
    SECURITY_CSP_NONCE_ENABLED = _env_bool("SECURITY_CSP_NONCE_ENABLED", True)
    SECURITY_CSP_STRICT_INLINE = _env_bool("SECURITY_CSP_STRICT_INLINE", True)
    SECURITY_CSP_ALLOW_STYLE_INLINE = _env_bool("SECURITY_CSP_ALLOW_STYLE_INLINE", True)
    SECURITY_PERMISSIONS_POLICY = (
        os.getenv(
            "SECURITY_PERMISSIONS_POLICY",
            "geolocation=(self), microphone=(), camera=(), payment=()",
        )
        or ""
    ).strip()
    SECURITY_RATE_LIMIT_ENABLED = _env_bool("SECURITY_RATE_LIMIT_ENABLED", True)
    FAIL_FAST_CRITICAL_BLUEPRINTS = _env_bool("FAIL_FAST_CRITICAL_BLUEPRINTS", False)

    TRUST_PROXY = _env_bool("TRUST_PROXY", ENV == "production")
    PROXY_FIX_X_FOR = int(os.getenv("PROXY_FIX_X_FOR", "1"))
    PROXY_FIX_X_PROTO = int(os.getenv("PROXY_FIX_X_PROTO", "1"))
    PROXY_FIX_X_HOST = int(os.getenv("PROXY_FIX_X_HOST", "1"))
    PROXY_FIX_X_PORT = int(os.getenv("PROXY_FIX_X_PORT", "0"))
    PROXY_FIX_X_PREFIX = int(os.getenv("PROXY_FIX_X_PREFIX", "0"))
    ANALYTICS_CITY_HEADERS = [
        header.strip()
        for header in os.getenv(
            "ANALYTICS_CITY_HEADERS",
            "CF-IPCity,CloudFront-Viewer-City,CloudFront-Viewer-City-Name,X-City,X-Geo-City,X-AppEngine-City,X-Real-City,X-Client-City,True-Client-City,Fly-Client-City,Geo-City",
        ).split(",")
        if header.strip()
    ]

    BOOTSTRAP_ADMIN = _env_bool("BOOTSTRAP_ADMIN", False)
    BOOTSTRAP_ADMIN_USERNAME = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "")
    BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")
    BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")

    SECURITY_ALERT_WEBHOOK_URL = os.getenv("SECURITY_ALERT_WEBHOOK_URL", "")
    MAINTENANCE_BACKUP_DIR = os.getenv("MAINTENANCE_BACKUP_DIR", "")
    DB_BACKUP_RETENTION_DAYS = int(os.getenv("DB_BACKUP_RETENTION_DAYS", "30"))
    UPLOADS_BACKUP_RETENTION_DAYS = int(os.getenv("UPLOADS_BACKUP_RETENTION_DAYS", "14"))
    FULL_BACKUP_RETENTION_DAYS = int(os.getenv("FULL_BACKUP_RETENTION_DAYS", "14"))
    FULL_BACKUP_KEEP_LATEST_ONLY = _env_bool("FULL_BACKUP_KEEP_LATEST_ONLY", False)

    max_env = os.getenv("MAX_CONTENT_LENGTH")
    if max_env:
        parsed = _safe_num_eval(max_env)
        MAX_CONTENT_LENGTH = int(parsed) if parsed is not None else 80 * 1024 * 1024
    else:
        MAX_CONTENT_LENGTH = 80 * 1024 * 1024


ADMIN_PHONE = Config.ADMIN_PHONE
DELIVERY_PHONE = Config.DELIVERY_WHATSAPP_NUMBER
