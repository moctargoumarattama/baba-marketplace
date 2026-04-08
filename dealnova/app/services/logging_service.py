import hashlib
import ipaddress
import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from flask import current_app, request
from ..extensions import db
from ..services.cache import cache

_PHONE_RE = re.compile(r"\d")
_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
_SENSITIVE_KEY_RE = re.compile(
    r"(phone|mobile|tel|address|lat|lng|lon|coord|token|secret|password|email|ip|user[_-]?agent)",
    re.IGNORECASE,
)


def _hash_value(value: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY") or "dealnova")
    payload = f"{secret}|{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _anonymize_ip(raw_ip: str | None) -> str | None:
    value = (raw_ip or "").strip()
    if not value:
        return None
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
    return f"ua:{_hash_value(ua)}"


def _mask_text_value(value: str) -> str:
    text = str(value or "")
    if _EMAIL_RE.match(text):
        name, domain = text.split("@", 1)
        keep = name[:1] if name else "*"
        return f"{keep}***@{domain}"
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"***{digits[-4:]}"
    return f"h:{_hash_value(text)}"


def _sanitize_details(value, depth=0, max_depth=5):
    if depth > max_depth:
        return f"[max depth exceeded: {type(value).__name__}]"
    
    if value is None:
        return None
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                if isinstance(item, (dict, list, tuple, set)):
                    result[key_text] = _sanitize_details(item, depth + 1, max_depth)
                else:
                    result[key_text] = _mask_text_value(str(item))
            else:
                result[key_text] = _sanitize_details(item, depth + 1, max_depth)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_details(item, depth + 1, max_depth) for item in value]
    if isinstance(value, str):
        if _EMAIL_RE.match(value):
            return _mask_text_value(value)
        if len(_PHONE_RE.findall(value)) >= 8:
            return _mask_text_value(value)
    return value


class ActivityLog(db.Model):
    """Model pour stocker les logs d'activité"""
    __tablename__ = 'activity_logs'
    __table_args__ = (
        db.Index('ix_activity_logs_timestamp', 'timestamp'),
        db.Index('ix_activity_logs_category', 'category'),
        db.Index('ix_activity_logs_level', 'level'),
        db.Index('ix_activity_logs_user_id', 'user_id'),
        db.Index('ix_activity_logs_resource', 'resource_type', 'resource_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    level = db.Column(db.String(20), default='INFO')  # INFO, WARNING, ERROR, DEBUG
    category = db.Column(db.String(50), nullable=False)  # user, order, shop, product, admin, system
    action = db.Column(db.String(100), nullable=False)  # login, create, update, delete, etc.
    user_id = db.Column(db.Integer, nullable=True)  # ID de l'utilisateur qui a fait l'action
    username = db.Column(db.String(80), nullable=True)  # Nom d'utilisateur
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4/IPv6
    user_agent = db.Column(db.Text, nullable=True)
    resource_type = db.Column(db.String(50), nullable=True)  # order, user, shop, product
    resource_id = db.Column(db.Integer, nullable=True)  # ID de la ressource affectée
    details = db.Column(db.Text, nullable=True)  # Détails supplémentaires en JSON
    message = db.Column(db.Text, nullable=False)  # Message descriptif

    def __repr__(self):
        return f"<ActivityLog {self.category}:{self.action} by {self.username or 'system'}>"


class LoggingService:
    """Service de logging pour l'application"""

    @staticmethod
    def setup_logging():
        """Configure le système de logging"""
        logs_dir = os.path.join(current_app.root_path, '..', 'logs')
        os.makedirs(logs_dir, exist_ok=True)

        logger = current_app.logger
        if getattr(logger, "_configured", False):
            return logger
        level_name = str(current_app.config.get("LOG_LEVEL", "INFO") or "INFO").strip().upper()
        level = getattr(logging, level_name, logging.INFO)
        logger.setLevel(level)
        logger.propagate = False

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        log_file = os.path.join(logs_dir, 'dealnova.log')
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max(1024, int(current_app.config.get("LOG_FILE_MAX_BYTES", 5 * 1024 * 1024) or (5 * 1024 * 1024))),
            backupCount=max(1, int(current_app.config.get("LOG_FILE_BACKUP_COUNT", 7) or 7)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        if not any(
            isinstance(handler, RotatingFileHandler)
            and getattr(handler, "baseFilename", None) == file_handler.baseFilename
            for handler in logger.handlers
        ):
            logger.addHandler(file_handler)

        if current_app.config.get('DEBUG', False):
            has_console_handler = any(
                isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler)
                for handler in logger.handlers
            )
            if not has_console_handler:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(formatter)
                console_handler.setLevel(level)
                logger.addHandler(console_handler)

        service_logger = logging.getLogger('dealnova')
        service_logger.setLevel(level)
        service_logger.handlers = []
        for handler in logger.handlers:
            service_logger.addHandler(handler)
        service_logger.propagate = False
        service_logger._configured = True

        logger._configured = True
        return logger

    @staticmethod
    def log_activity(category, action, user=None, resource_type=None, resource_id=None,
                    details=None, level='INFO', message=None):
        """Log une activité dans la base de données et les fichiers"""

        if not message:
            if user:
                message = f"{user.username} ({category}) - {action}"
                if resource_type and resource_id:
                    message += f" {resource_type} #{resource_id}"
            else:
                message = f"Système ({category}) - {action}"
                if resource_type and resource_id:
                    message += f" {resource_type} #{resource_id}"

        ip_address = None
        user_agent = None
        try:
            ip_address = _anonymize_ip(request.remote_addr if request else None)
            user_agent = _anonymize_user_agent(request.headers.get('User-Agent') if request else None)
        except:
            pass

        sanitized_details = _sanitize_details(details) if details is not None else None
        serialized_details = None
        if sanitized_details is not None:
            try:
                serialized_details = json.dumps(sanitized_details, ensure_ascii=False)
            except Exception:
                serialized_details = str(sanitized_details)

        log_entry = ActivityLog(
            level=level,
            category=category,
            action=action,
            user_id=user.id if user else None,
            username=user.username if user else None,
            ip_address=ip_address,
            user_agent=user_agent,
            resource_type=resource_type,
            resource_id=resource_id,
            details=serialized_details,
            message=message
        )

        try:
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            current_app.logger.error(f"Erreur lors du logging DB: {e}")

        logger = current_app.logger
        log_method = getattr(logger, level.lower(), logger.info)
        log_method(f"[{category}] {message}")

    @staticmethod
    def get_recent_logs(limit=100, category=None, level=None, user_id=None, days=None):
        """Récupère les logs récents avec filtres"""
        query = ActivityLog.query

        if category:
            query = query.filter_by(category=category)

        if level:
            query = query.filter_by(level=level)

        if user_id:
            query = query.filter_by(user_id=user_id)

        if days:
            since = datetime.utcnow() - timedelta(days=days)
            query = query.filter(ActivityLog.timestamp >= since)

        return query.order_by(ActivityLog.timestamp.desc()).limit(limit).all()

    @staticmethod
    @cache.cached(timeout=300, key_prefix="logs_stats")
    def get_logs_stats(days=7):
        """Récupère les statistiques des logs avec cache"""
        since = datetime.utcnow() - timedelta(days=days)

        category_stats = db.session.query(
            ActivityLog.category,
            db.func.count(ActivityLog.id).label('count')
        ).filter(ActivityLog.timestamp >= since)\
         .group_by(ActivityLog.category)\
         .all()

        level_stats = db.session.query(
            ActivityLog.level,
            db.func.count(ActivityLog.id).label('count')
        ).filter(ActivityLog.timestamp >= since)\
         .group_by(ActivityLog.level)\
         .all()

        daily_stats = []
        for i in range(days):
            day = datetime.utcnow() - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)

            count = ActivityLog.query.filter(
                ActivityLog.timestamp >= day_start,
                ActivityLog.timestamp <= day_end
            ).count()

            daily_stats.append({
                'date': day.strftime('%Y-%m-%d'),
                'count': count
            })

        return {
            'category_stats': dict(category_stats),
            'level_stats': dict(level_stats),
            'daily_stats': daily_stats[::-1]
        }

    @staticmethod
    def cleanup_old_logs(days=10):
        """Supprime les logs plus vieux que days."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            deleted = ActivityLog.query.filter(ActivityLog.timestamp < cutoff).delete()
            db.session.commit()
            current_app.logger.info(f"Cleanup: {deleted} logs supprimés (> {days} jours)")
            return deleted
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Cleanup logs failed: {e}")
            return 0


# Instance globale du service
logging_service = LoggingService()
