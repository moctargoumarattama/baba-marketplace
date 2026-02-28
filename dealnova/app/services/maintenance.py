from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from flask import current_app
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import sessionmaker

from ..extensions import db
from ..models.maintenance import ErrorLog, MaintenanceRun
from ..models.product import Product
from ..models.rental import RentalArchive, RentalListing, RentalMedia
from ..models.shop import Shop
from ..models.user import User
from .image import LARGE_SIZE, THUMB_SIZE
from .rentals import ARCHIVE_RETENTION_DAYS, archive_and_remove_listing

UPLOADS_SIZE_GB_WARNING = 3.0
UPLOADS_SIZE_GB_DANGER = 6.0
ORPHAN_MEDIA_COUNT_WARNING = 50
ORPHAN_MEDIA_COUNT_DANGER = 200
EXPIRED_LOCATIONS_GT_DAYS_WARNING = 20
EXPIRED_LOCATIONS_GT_DAYS_DANGER = 100
DB_SIZE_MB_WARNING = 300.0
DB_SIZE_MB_DANGER = 800.0
ERROR_LOG_RETENTION_DAYS_DEFAULT = 7
ERROR_LOG_SPAM_WINDOW_SECONDS = 60
ERROR_LOG_SPAM_MAX_PER_SIGNATURE = 20
ERROR_LOG_SPAM_MAX_SIGNATURES = 2000

_ERROR_LOG_SPAM_LOCK = Lock()
_ERROR_LOG_SPAM_BUCKETS: dict[tuple[str, str, int, str], deque[float]] = {}


def _project_root() -> Path:
    return Path(current_app.root_path).resolve().parent


def _sqlite_db_file_path() -> Path | None:
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
    if not uri.startswith("sqlite:///"):
        return None

    raw_path = uri[len("sqlite:///"):]
    if not raw_path or raw_path == ":memory:":
        return None

    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = (_project_root() / raw_path).resolve()
    return db_path


def _resolve_backup_dir(custom_dir: str | None = None) -> Path:
    configured = (custom_dir or "").strip() or str(current_app.config.get("MAINTENANCE_BACKUP_DIR") or "").strip()
    if not configured:
        configured = str((_project_root() / "backups").resolve())
    path = Path(configured)
    if not path.is_absolute():
        path = (_project_root() / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_pre_reset_backup(
    *,
    backup_dir: str | None = None,
    requested_by_admin_id: int | None = None,
    requested_by_admin_username: str | None = None,
) -> dict[str, Any]:
    db_path = _sqlite_db_file_path()
    if db_path is None:
        raise RuntimeError("Backup auto avant reset supporte uniquement SQLite.")
    if not db_path.exists():
        raise RuntimeError(f"Fichier SQLite introuvable: {db_path}")

    destination_dir = _resolve_backup_dir(backup_dir)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_file = destination_dir / f"dealnova_pre_reset_{timestamp}.sqlite3"
    manifest_file = destination_dir / f"dealnova_pre_reset_{timestamp}.json"

    source_conn = None
    backup_conn = None
    try:
        source_conn = sqlite3.connect(str(db_path))
        backup_conn = sqlite3.connect(str(backup_file))
        source_conn.backup(backup_conn)
    finally:
        if backup_conn is not None:
            backup_conn.close()
        if source_conn is not None:
            source_conn.close()

    admins_count = int(User.query.filter(User.role == "admin").count())
    manifest = {
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "db_engine": "sqlite",
        "source_db_path": str(db_path),
        "backup_db_path": str(backup_file),
        "requested_by_admin_id": requested_by_admin_id,
        "requested_by_admin_username": requested_by_admin_username,
        "admins_before_reset": admins_count,
    }
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "backup_dir": str(destination_dir),
        "backup_file": str(backup_file),
        "manifest_file": str(manifest_file),
        "db_engine": "sqlite",
    }


def _uploads_root() -> Path:
    return Path(current_app.static_folder).resolve() / "uploads"


def _safe_rel_from_static(path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(Path(current_app.static_folder).resolve()).as_posix()
        return rel
    except Exception:
        return None


def _normalize_upload_rel(raw: str | None) -> str:
    if not raw:
        return ""
    value = str(raw).strip().replace("\\", "/")
    if not value or "://" in value:
        return ""

    value = value.lstrip("/")
    if value.startswith("static/"):
        value = value[len("static/"):]

    marker = value.find("uploads/")
    if marker >= 0:
        value = value[marker:]
    elif value.startswith("rentals/"):
        value = f"uploads/{value}"
    elif not value.startswith("uploads/"):
        value = f"uploads/{value}"

    parts = [part for part in Path(value).parts if part not in ("", ".", "..")]
    normalized = Path(*parts).as_posix()
    return normalized if normalized.startswith("uploads/") else ""


def _variant_rel_paths(rel_path: str) -> set[str]:
    if not rel_path.startswith("uploads/"):
        return set()
    if rel_path.startswith("uploads/rentals/"):
        return set()

    rel_no_prefix = rel_path[len("uploads/"):]
    directory = os.path.dirname(rel_no_prefix)
    filename = os.path.basename(rel_no_prefix)
    base_name, _ = os.path.splitext(filename)

    variants = set()
    for px in (THUMB_SIZE, LARGE_SIZE):
        variant_name = f"{base_name}_{px}.webp"
        if directory:
            variants.add(f"uploads/{directory}/{variant_name}")
        else:
            variants.add(f"uploads/{variant_name}")
    return variants


def _iter_upload_files() -> list[str]:
    uploads = _uploads_root()
    if not uploads.exists():
        return []

    files: list[str] = []
    for root, _, names in os.walk(uploads):
        for name in names:
            abs_path = Path(root) / name
            rel = _safe_rel_from_static(abs_path)
            if rel:
                files.append(rel)
    return files


def _uploads_size_bytes() -> tuple[int, int]:
    uploads = _uploads_root()
    if not uploads.exists():
        return 0, 0

    total_size = 0
    file_count = 0
    for root, _, names in os.walk(uploads):
        for name in names:
            abs_path = Path(root) / name
            try:
                total_size += int(abs_path.stat().st_size)
                file_count += 1
            except Exception:
                continue
    return total_size, file_count


def _used_upload_paths() -> set[str]:
    used: set[str] = set()

    product_rows = db.session.query(Product.image_file).all()
    for (raw_images,) in product_rows:
        if not raw_images:
            continue
        for chunk in str(raw_images).split("|"):
            rel = _normalize_upload_rel(chunk)
            if not rel:
                continue
            used.add(rel)
            used.update(_variant_rel_paths(rel))

    shop_rows = db.session.query(Shop.logo, Shop.banner).all()
    for logo, banner in shop_rows:
        for raw in (logo, banner):
            rel = _normalize_upload_rel(raw)
            if rel:
                used.add(rel)
                used.update(_variant_rel_paths(rel))

    media_rows = db.session.query(RentalMedia.file_path).all()
    for (file_path,) in media_rows:
        rel = _normalize_upload_rel(file_path)
        if rel:
            used.add(rel)

    return used


def find_global_orphan_upload_files() -> list[str]:
    all_files = set(_iter_upload_files())
    if not all_files:
        return []
    used_files = _used_upload_paths()
    return sorted(path for path in all_files if path not in used_files)


def _remove_upload_files(rel_paths: list[str]) -> tuple[int, list[str]]:
    removed = 0
    errors: list[str] = []
    static_root = Path(current_app.static_folder).resolve()

    for rel in rel_paths:
        safe_rel = _normalize_upload_rel(rel)
        if not safe_rel:
            continue
        abs_path = (static_root / safe_rel).resolve()
        if not str(abs_path).startswith(str(static_root)):
            continue
        if not abs_path.exists() or not abs_path.is_file():
            continue
        try:
            abs_path.unlink()
            removed += 1
        except Exception as exc:
            errors.append(f"{safe_rel}: {exc}")
    return removed, errors


def _cache_active() -> bool:
    cache_type = str(current_app.config.get("CACHE_TYPE") or "").strip().lower()
    if not cache_type:
        return False
    return cache_type not in {"nullcache", "none", "disabled"}


def clear_runtime_cache() -> tuple[bool, str | None]:
    if not _cache_active():
        return False, None
    try:
        from .cache import cache

        cache.clear()
        return True, None
    except Exception as exc:
        return False, str(exc)


def _sqlite_db_size_bytes() -> int | None:
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
    if not uri.startswith("sqlite:///"):
        return None

    raw_path = uri[len("sqlite:///"):]
    if not raw_path or raw_path == ":memory:":
        return None

    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = (Path(current_app.root_path).resolve().parent / raw_path).resolve()

    try:
        if db_path.exists() and db_path.is_file():
            return int(db_path.stat().st_size)
    except Exception:
        return None
    return None


def human_size(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "N/A"
    size = float(max(0, int(num_bytes)))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def collect_system_health(expired_days: int = 6) -> dict[str, Any]:
    days = max(0, int(expired_days or 0))
    health: dict[str, Any] = {
        "uploads_size": "N/A",
        "uploads_size_bytes": None,
        "uploads_size_gb": None,
        "uploads_file_count": "N/A",
        "expired_locations_count": None,
        "expired_locations_gt_days": None,
        "orphan_media_count": "N/A",
        "cache_status": "N/A",
        "db_size": "N/A",
        "db_size_bytes": None,
        "db_size_mb": None,
        "db_engine": "N/A",
        "errors": [],
        "days_threshold": days,
    }

    try:
        upload_bytes, upload_files = _uploads_size_bytes()
        health["uploads_size"] = human_size(upload_bytes)
        health["uploads_size_bytes"] = int(upload_bytes)
        health["uploads_size_gb"] = round(upload_bytes / (1024.0 ** 3), 3)
        health["uploads_file_count"] = upload_files
    except Exception as exc:
        health["errors"].append(f"uploads: {exc}")

    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        count = (
            RentalListing.query
            .filter(
                or_(
                    and_(RentalListing.status.in_(["expired", "taken"]), RentalListing.updated_at <= cutoff),
                    and_(RentalListing.expires_at.isnot(None), RentalListing.expires_at <= cutoff),
                )
            )
            .count()
        )
        expired_count = int(count or 0)
        health["expired_locations_count"] = expired_count
        health["expired_locations_gt_days"] = expired_count
    except Exception as exc:
        health["errors"].append(f"expired_locations: {exc}")

    try:
        orphan_count = len(find_global_orphan_upload_files())
        health["orphan_media_count"] = orphan_count
    except Exception as exc:
        health["errors"].append(f"orphan_media: {exc}")

    try:
        health["cache_status"] = "OK" if _cache_active() else "Disabled"
    except Exception as exc:
        health["errors"].append(f"cache_status: {exc}")

    try:
        uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI") or "")
        if uri.startswith("sqlite:///"):
            health["db_engine"] = "SQLite"
            db_size_bytes = _sqlite_db_size_bytes()
            health["db_size_bytes"] = db_size_bytes
            if db_size_bytes is not None:
                health["db_size_mb"] = round(db_size_bytes / (1024.0 ** 2), 2)
            health["db_size"] = human_size(db_size_bytes)
        else:
            health["db_engine"] = "Postgres/Other"
            health["db_size"] = "N/A"
    except Exception as exc:
        health["errors"].append(f"db_size: {exc}")

    return health


def _cleanup_expired_server_sessions() -> tuple[bool, int, str | None]:
    session_type = str(current_app.config.get("SESSION_TYPE") or "").strip().lower()
    if session_type != "filesystem":
        return False, 0, None

    session_dir = current_app.config.get("SESSION_FILE_DIR")
    if not session_dir:
        session_dir = os.path.join(current_app.instance_path, "flask_session")
    if not os.path.isdir(session_dir):
        return True, 0, None

    try:
        lifetime = current_app.permanent_session_lifetime
        ttl = int(lifetime.total_seconds()) if lifetime else 21600
    except Exception:
        ttl = int(current_app.config.get("PERMANENT_SESSION_LIFETIME") or 21600)

    cutoff_ts = time.time() - max(60, ttl)
    deleted = 0
    for name in os.listdir(session_dir):
        path = os.path.join(session_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getmtime(path) <= cutoff_ts:
                os.remove(path)
                deleted += 1
        except Exception:
            continue
    return True, deleted, None


def _purge_stale_rentals(expired_days: int = 6) -> tuple[int, int, int, list[str]]:
    now = datetime.utcnow()
    cutoff = now - timedelta(days=max(0, int(expired_days or 0)))
    errors: list[str] = []

    listings = (
        RentalListing.query
        .filter(
            or_(
                and_(RentalListing.expires_at.isnot(None), RentalListing.expires_at <= cutoff),
                and_(RentalListing.status.in_(["taken", "expired"]), RentalListing.updated_at <= cutoff),
            )
        )
        .all()
    )

    purged_count = 0
    media_deleted = 0
    archives_deleted = 0

    try:
        for listing in listings:
            reason = listing.status if listing.status in {"taken", "expired"} else "expired"
            result = archive_and_remove_listing(listing, closed_reason=reason)
            purged_count += 1
            media_deleted += int(result.get("removed_files") or 0)

        archive_cutoff = now - timedelta(days=ARCHIVE_RETENTION_DAYS)
        old_archives = (
            RentalArchive.query
            .filter(RentalArchive.closed_at <= archive_cutoff)
            .all()
        )
        archives_deleted = len(old_archives)
        for archive in old_archives:
            db.session.delete(archive)

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        errors.append(str(exc))
        purged_count = 0
        media_deleted = 0
        archives_deleted = 0

    return purged_count, media_deleted, archives_deleted, errors


def _purge_old_error_logs(retention_days: int = ERROR_LOG_RETENTION_DAYS_DEFAULT) -> tuple[int, str | None]:
    days = max(1, int(retention_days or ERROR_LOG_RETENTION_DAYS_DEFAULT))
    cutoff = datetime.utcnow() - timedelta(days=days)
    try:
        deleted = (
            ErrorLog.query
            .filter(ErrorLog.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.session.commit()
        return int(deleted or 0), None
    except Exception as exc:
        db.session.rollback()
        return 0, str(exc)


def _allow_error_log_insert(path: str | None, method: str | None, status_code: int, short_message: str | None) -> bool:
    signature = (
        (str(path or "")[:180]),
        (str(method or "").upper()[:16]),
        int(status_code),
        (str(short_message or "")[:180]),
    )
    now_ts = time.time()
    cutoff_ts = now_ts - ERROR_LOG_SPAM_WINDOW_SECONDS

    with _ERROR_LOG_SPAM_LOCK:
        bucket = _ERROR_LOG_SPAM_BUCKETS.get(signature)
        if bucket is None:
            bucket = deque()
            _ERROR_LOG_SPAM_BUCKETS[signature] = bucket

        while bucket and bucket[0] <= cutoff_ts:
            bucket.popleft()

        if len(bucket) >= ERROR_LOG_SPAM_MAX_PER_SIGNATURE:
            return False

        bucket.append(now_ts)

        if len(_ERROR_LOG_SPAM_BUCKETS) > ERROR_LOG_SPAM_MAX_SIGNATURES:
            stale_keys = []
            for key, values in _ERROR_LOG_SPAM_BUCKETS.items():
                while values and values[0] <= cutoff_ts:
                    values.popleft()
                if not values:
                    stale_keys.append(key)
            for key in stale_keys[:500]:
                _ERROR_LOG_SPAM_BUCKETS.pop(key, None)

    return True


def run_maintenance_cleanup(
    mode: str = "quick",
    expired_days: int = 6,
    purge_error_logs_days: int | None = ERROR_LOG_RETENTION_DAYS_DEFAULT,
) -> dict[str, Any]:
    normalized_mode = (mode or "quick").strip().lower()
    if normalized_mode not in {"quick", "full"}:
        normalized_mode = "quick"

    report: dict[str, Any] = {
        "mode": normalized_mode,
        "ran_at": datetime.utcnow().isoformat(),
        "files_deleted": 0,
        "orphan_media_removed": 0,
        "locations_purged": 0,
        "locations_media_deleted": 0,
        "archives_purged": 0,
        "cache_cleared": False,
        "sessions_cleaned": False,
        "sessions_deleted": 0,
        "error_logs_purged": 0,
        "errors": [],
    }

    orphan_files = []
    try:
        orphan_files = find_global_orphan_upload_files()
    except Exception as exc:
        report["errors"].append(f"orphan_scan: {exc}")

    if orphan_files:
        removed, remove_errors = _remove_upload_files(orphan_files)
        report["files_deleted"] += removed
        report["orphan_media_removed"] = removed
        if remove_errors:
            report["errors"].extend(remove_errors[:20])

    cache_cleared, cache_error = clear_runtime_cache()
    report["cache_cleared"] = cache_cleared
    if cache_error:
        report["errors"].append(f"cache: {cache_error}")

    if normalized_mode == "full":
        purged, media_deleted, archives_deleted, rental_errors = _purge_stale_rentals(expired_days=expired_days)
        report["locations_purged"] = purged
        report["locations_media_deleted"] = media_deleted
        report["archives_purged"] = archives_deleted
        report["files_deleted"] += media_deleted
        if rental_errors:
            report["errors"].extend(rental_errors[:10])

        sessions_supported, sessions_deleted, sessions_error = _cleanup_expired_server_sessions()
        report["sessions_cleaned"] = sessions_supported
        report["sessions_deleted"] = sessions_deleted
        if sessions_error:
            report["errors"].append(f"sessions: {sessions_error}")

        if purge_error_logs_days is not None and int(purge_error_logs_days or 0) > 0:
            deleted_logs, purge_error = _purge_old_error_logs(retention_days=int(purge_error_logs_days))
            report["error_logs_purged"] = deleted_logs
            if purge_error:
                report["errors"].append(f"error_logs_purge: {purge_error}")

    return report


def run_and_store_maintenance_report(
    mode: str = "quick",
    expired_days: int = 6,
    purge_error_logs_days: int | None = ERROR_LOG_RETENTION_DAYS_DEFAULT,
) -> dict[str, Any]:
    safe_days = max(1, min(365, int(expired_days or 6)))
    started_at = datetime.utcnow()
    cleanup_report = run_maintenance_cleanup(
        mode=mode,
        expired_days=safe_days,
        purge_error_logs_days=purge_error_logs_days,
    )
    health_report = collect_system_health(expired_days=safe_days)
    finished_at = datetime.utcnow()

    report: dict[str, Any] = {
        "mode": cleanup_report.get("mode", "quick"),
        "days": safe_days,
        "ran_at": finished_at.isoformat(),
        "cleanup": cleanup_report,
        "health": health_report,
    }

    cleanup_errors = cleanup_report.get("errors") or []
    health_errors = health_report.get("errors") or []
    error_count = len(cleanup_errors) + len(health_errors)
    duration_ms = int(max(0.0, (finished_at - started_at).total_seconds() * 1000))

    persisted = False
    persist_error = None
    try:
        run = MaintenanceRun(
            mode=str(report["mode"]),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            result_counts=report,
            error_count=error_count,
        )
        db.session.add(run)
        db.session.commit()
        persisted = True
    except Exception as exc:
        db.session.rollback()
        persist_error = str(exc)

    report["duration_ms"] = duration_ms
    report["error_count"] = error_count
    report["persisted"] = persisted
    if persist_error:
        report["persist_error"] = persist_error

    return report


def log_http_error(path: str | None, method: str | None, status_code: int, message: str | None) -> None:
    short_message = (str(message or "").strip().replace("\n", " "))[:255] or None
    safe_path = (str(path or "").strip() or None)
    safe_method = (str(method or "").strip().upper()[:16] or None)
    safe_status = int(status_code)

    if not _allow_error_log_insert(safe_path, safe_method, safe_status, short_message):
        return

    session = None
    try:
        bind = db.session.get_bind()
        session = sessionmaker(bind=bind)()
        session.add(
            ErrorLog(
                path=safe_path,
                method=safe_method,
                status_code=safe_status,
                short_message=short_message,
            )
        )
        session.commit()
    except Exception:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def reset_database_keep_admins() -> dict[str, Any]:
    admin_ids = [row.id for row in User.query.with_entities(User.id).filter(User.role == "admin").all()]
    if not admin_ids:
        raise RuntimeError("Aucun administrateur n'existe pour conserver l'accès.")

    db.session.commit()
    db.session.remove()

    engine = db.engine
    user_table = User.__table__

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys = OFF"))

        for table in reversed(db.metadata.sorted_tables):
            if table.name in {"user", "alembic_version"}:
                continue
            conn.execute(table.delete())

        conn.execute(user_table.delete().where(user_table.c.role != "admin"))

        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys = ON"))

    return {"admins_kept": len(admin_ids)}
