import os
import ast
import operator as op
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # dossier app/
ENV_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", ".env"))

# Charger le .env seulement s'il existe (évite surprises en prod)
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)


class Config:
    @staticmethod
    def _env_bool(name, default=False):
        val = os.getenv(name)
        if val is None:
            return default
        return str(val).strip().lower() in ("1", "true", "yes", "on")

    ENV = os.getenv("FLASK_ENV", "production").lower()
    DEBUG = _env_bool.__func__("DEBUG", False)
    APP_STATIC_VERSION = os.getenv("APP_STATIC_VERSION", "20260225a")
    UI_HOME_TABS_ENABLED = _env_bool.__func__("UI_HOME_TABS_ENABLED", True)

    # ⚠️ On garde le fallback "dev" pour ne pas casser,
    # mais on recommande fortement de définir SECRET_KEY en prod.
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    if ENV == "production" and (not SECRET_KEY or SECRET_KEY.strip().lower() in ("dev", "secret", "password", "123456")):
        # Warning non-bloquant (ne casse pas le site)
        print("[WARN] SECRET_KEY faible ou manquant en production. Définis une SECRET_KEY forte dans les variables d'environnement.")

    @staticmethod
    def _normalize_sqlite_url(url):
        if not url:
            return url
        prefix = "sqlite:///"
        if url.startswith(prefix):
            path = url[len(prefix):]
            if not os.path.isabs(path):
                path = os.path.abspath(os.path.join(BASE_DIR, "..", path))
            path = path.replace("\\", "/")
            return prefix + path
        return url

    _db_env = os.getenv("DATABASE_URL")
    SQLALCHEMY_DATABASE_URI = _normalize_sqlite_url.__func__(_db_env) if _db_env else (
        "sqlite:///" + os.path.join(BASE_DIR, "..", "instance", "dealnova.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    if SQLALCHEMY_DATABASE_URI.startswith("sqlite:///"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {"timeout": 30},
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 280,
            "pool_timeout": 30,
        }

    # =========================
    # Branding / Business rules
    # =========================
    SITE_NAME = os.getenv("SITE_NAME", "Baba Market ")
    SITE_LOGO = os.getenv("SITE_LOGO", "")
    DELIVERY_WHATSAPP_NUMBER = os.getenv("DELIVERY_WHATSAPP_NUMBER", "212602908954")
    ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+212770010264")
    SUPPORT_WHATSAPP_NUMBER = os.getenv("SUPPORT_WHATSAPP_NUMBER", ADMIN_PHONE)

    # UPLOAD_FOLDER: rendre absolu si relatif (plus robuste)
    _upload_folder_env = os.getenv("UPLOAD_FOLDER", "app/static/uploads")
    if os.path.isabs(_upload_folder_env):
        UPLOAD_FOLDER = _upload_folder_env
    else:
        # relatif => on le rend absolu à partir de BASE_DIR/..
        UPLOAD_FOLDER = os.path.abspath(os.path.join(BASE_DIR, "..", _upload_folder_env))

    DEFAULT_LANG = os.getenv("DEFAULT_LANG", "fr")
    LANGUAGES = ["fr", "en", "ary"]
    LANG_COOKIE_NAME = os.getenv("LANG_COOKIE_NAME", "lang")
    LANG_COOKIE_MAX_AGE = int(os.getenv("LANG_COOKIE_MAX_AGE", "63072000"))  # 2 ans
    LANG_COOKIE_SAMESITE = os.getenv("LANG_COOKIE_SAMESITE", "Lax")
    LANG_COOKIE_SECURE = _env_bool.__func__("LANG_COOKIE_SECURE", ENV == "production")
    RTL_LANGUAGES = [lang.strip() for lang in os.getenv("RTL_LANGUAGES", "ary").split(",") if lang.strip()]

    CACHE_TYPE = os.getenv("CACHE_TYPE", "SimpleCache")
    CACHE_DEFAULT_TIMEOUT = int(os.getenv("CACHE_DEFAULT_TIMEOUT", "3600"))
    try:
        MAX_LIMIT = max(1, int(os.getenv("MAX_LIMIT", "50")))
    except ValueError:
        MAX_LIMIT = 50

    # =========================
    # Security defaults
    # =========================
    SESSION_COOKIE_HTTPONLY = True

    # Normaliser SameSite (sans casser: on garde Lax par défaut)
    _samesite = (os.getenv("SESSION_COOKIE_SAMESITE", "Lax") or "Lax").strip()
    _samesite_cap = _samesite[:1].upper() + _samesite[1:].lower()
    SESSION_COOKIE_SAMESITE = _samesite_cap if _samesite_cap in ("Lax", "Strict", "None") else "Lax"

    SESSION_COOKIE_SECURE = _env_bool.__func__("SESSION_COOKIE_SECURE", ENV == "production")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    PERMANENT_SESSION_LIFETIME = int(os.getenv("PERMANENT_SESSION_LIFETIME", "21600"))
    WTF_CSRF_TIME_LIMIT = int(os.getenv("WTF_CSRF_TIME_LIMIT", "3600"))
    PREFERRED_URL_SCHEME = "https" if ENV == "production" else "http"

    SECURITY_HEADERS_ENABLED = _env_bool.__func__("SECURITY_HEADERS_ENABLED", True)
    SECURITY_HSTS_ENABLED = _env_bool.__func__("SECURITY_HSTS_ENABLED", ENV == "production")
    SECURITY_HSTS_TRUST_X_FORWARDED_PROTO = _env_bool.__func__(
        "SECURITY_HSTS_TRUST_X_FORWARDED_PROTO",
        ENV == "production",
    )
    SECURITY_CSP_ENABLED = _env_bool.__func__("SECURITY_CSP_ENABLED", True)
    # Transitional mode:
    # - nonce support is enabled by default
    # - strict inline blocking stays optional to avoid breaking legacy inline handlers.
    SECURITY_CSP_NONCE_ENABLED = _env_bool.__func__("SECURITY_CSP_NONCE_ENABLED", True)
    SECURITY_CSP_STRICT_INLINE = _env_bool.__func__("SECURITY_CSP_STRICT_INLINE", True)
    SECURITY_CSP_ALLOW_STYLE_INLINE = _env_bool.__func__("SECURITY_CSP_ALLOW_STYLE_INLINE", True)
    SECURITY_RATE_LIMIT_ENABLED = _env_bool.__func__("SECURITY_RATE_LIMIT_ENABLED", True)
    FAIL_FAST_CRITICAL_BLUEPRINTS = _env_bool.__func__("FAIL_FAST_CRITICAL_BLUEPRINTS", ENV == "production")

    TRUST_PROXY = _env_bool.__func__("TRUST_PROXY", ENV == "production")
    PROXY_FIX_X_FOR = int(os.getenv("PROXY_FIX_X_FOR", "1"))
    PROXY_FIX_X_PROTO = int(os.getenv("PROXY_FIX_X_PROTO", "1"))
    PROXY_FIX_X_HOST = int(os.getenv("PROXY_FIX_X_HOST", "1"))
    PROXY_FIX_X_PORT = int(os.getenv("PROXY_FIX_X_PORT", "0"))
    PROXY_FIX_X_PREFIX = int(os.getenv("PROXY_FIX_X_PREFIX", "0"))

    BOOTSTRAP_ADMIN = _env_bool.__func__("BOOTSTRAP_ADMIN", False)
    BOOTSTRAP_ADMIN_USERNAME = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "")
    BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")
    BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")

    SECURITY_ALERT_WEBHOOK_URL = os.getenv("SECURITY_ALERT_WEBHOOK_URL", "")
    MAINTENANCE_BACKUP_DIR = os.getenv("MAINTENANCE_BACKUP_DIR", "")

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

    max_env = os.getenv("MAX_CONTENT_LENGTH")
    if max_env:
        parsed = _safe_num_eval.__func__(max_env)
        MAX_CONTENT_LENGTH = int(parsed) if parsed is not None else 80 * 1024 * 1024
    else:
        # Taille max requête multipart (uploads)
        # 4 images * 12MB + 1 vidéo * 30MB + marge formulaire
        MAX_CONTENT_LENGTH = 80 * 1024 * 1024


# Valeurs globales (je les laisse inchangées pour ne pas casser ton code)
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+212770010264")
DELIVERY_PHONE = os.getenv("DELIVERY_PHONE", "212602908954")
