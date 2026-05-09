from __future__ import annotations

import json
import os
import gzip
import shutil
import sqlite3
import subprocess
import time
import random
import tempfile
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import click
from flask import current_app
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import sessionmaker

from ..extensions import db
from ..models.maintenance import ErrorLog, MaintenanceRun
from ..models.platform_settings import PlatformSettings
from ..models.product import Product
from ..models.rental import RentalArchive, RentalListing, RentalMedia
from ..models.runtime_state import RuntimeState
from ..models.shop import Shop
from ..models.user import User
from .image import LARGE_SIZE, THUMB_SIZE
from .rentals import ARCHIVE_RETENTION_DAYS, archive_and_remove_listing

# Définition du blueprint pour les commandes CLI
try:
    from flask import Blueprint
    bp = Blueprint("maintenance_cli", __name__)
except ImportError:
    bp = None


# Seuils par défaut (surchargés par PlatformSettings)
UPLOADS_SIZE_GB_WARNING = 3.0
UPLOADS_SIZE_GB_DANGER = 6.0
ORPHAN_MEDIA_COUNT_WARNING = 50
ORPHAN_MEDIA_COUNT_DANGER = 200
EXPIRED_LOCATIONS_GT_DAYS_WARNING = 20
EXPIRED_LOCATIONS_GT_DAYS_DANGER = 100
DB_SIZE_MB_WARNING = 300.0
DB_SIZE_MB_DANGER = 800.0
ERROR_LOG_RETENTION_DAYS_DEFAULT = 7
RATE_LIMIT_STATE_RETENTION_DAYS_DEFAULT = 7
ERROR_LOG_SPAM_WINDOW_SECONDS = 60
ERROR_LOG_SPAM_MAX_PER_SIGNATURE = 20
ERROR_LOG_SPAM_MAX_SIGNATURES = 2000

_HTTP_STATUS_LABELS_FR = {
    400: "400 Requete invalide",
    401: "401 Non autorise",
    403: "403 Acces interdit",
    404: "404 Introuvable",
    405: "405 Methode non autorisee",
    413: "413 Charge utile trop volumineuse",
    429: "429 Trop de requetes",
    500: "500 Erreur interne du serveur",
}

_HTTP_STATUS_DETAILS_FR = {
    "The browser (or proxy) sent a request that this server could not understand.": (
        "Le navigateur (ou le proxy) a envoye une requete que le serveur n'a pas pu comprendre."
    ),
    "The server could not verify that you are authorized to access the URL requested.": (
        "Le serveur n'a pas pu verifier que vous etes autorise a acceder a l'URL demandee."
    ),
    "You do not have the permission to access the requested resource.": (
        "Vous n'avez pas la permission d'acceder a la ressource demandee."
    ),
    "The requested URL was not found on the server.": (
        "L'URL demandee est introuvable sur le serveur."
    ),
    "The method is not allowed for the requested URL.": (
        "La methode utilisee n'est pas autorisee pour cette URL."
    ),
    "The data value transmitted exceeds the capacity limit.": (
        "Les donnees envoyees depassent la limite acceptee par le serveur."
    ),
    "This user has exceeded an allotted request count. Try again later.": (
        "Cette limite de requetes a ete depassee. Reessayez plus tard."
    ),
    "The server encountered an internal error and was unable to complete your request. Either the server is overloaded or there is an error in the application.": (
        "Le serveur a rencontre une erreur interne et n'a pas pu terminer votre requete. Le serveur est peut-etre surcharge ou une erreur s'est produite dans l'application."
    ),
}

_ERROR_LOG_SPAM_LOCK = Lock()
_ERROR_LOG_SPAM_BUCKETS: dict[tuple[str, str, int, str], deque[float]] = {}


def _get_thresholds():
    """Récupère les seuils depuis PlatformSettings ou utilise les défauts."""
    settings = PlatformSettings.get()
    return {
        "uploads_warning": getattr(settings, "uploads_size_gb_warning", UPLOADS_SIZE_GB_WARNING),
        "uploads_danger": getattr(settings, "uploads_size_gb_danger", UPLOADS_SIZE_GB_DANGER),
        "orphan_warning": getattr(settings, "orphan_media_warning", ORPHAN_MEDIA_COUNT_WARNING),
        "orphan_danger": getattr(settings, "orphan_media_danger", ORPHAN_MEDIA_COUNT_DANGER),
        "expired_warning": getattr(settings, "expired_locations_warning", EXPIRED_LOCATIONS_GT_DAYS_WARNING),
        "expired_danger": getattr(settings, "expired_locations_danger", EXPIRED_LOCATIONS_GT_DAYS_DANGER),
        "db_warning": getattr(settings, "db_size_mb_warning", DB_SIZE_MB_WARNING),
        "db_danger": getattr(settings, "db_size_mb_danger", DB_SIZE_MB_DANGER),
    }


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


def _validate_backup_dir(path: Path) -> bool:
    """Vérifie que le dossier de backup est accessible en écriture."""
    try:
        test_file = path / ".write_test"
        test_file.touch()
        test_file.unlink()
        return True
    except Exception:
        return False


def _guard_backup_dir_not_public(path: Path) -> None:
    """Evite de mettre les sauvegardes dans static/uploads ou un dossier public."""
    resolved = path.resolve()
    public_roots: list[Path] = []

    static_folder = getattr(current_app, "static_folder", None)
    if static_folder:
        public_roots.append(Path(static_folder).resolve())

    upload_folder = str(current_app.config.get("UPLOAD_FOLDER") or "").strip()
    if upload_folder:
        upload_path = Path(upload_folder)
        if not upload_path.is_absolute():
            upload_path = (_project_root() / upload_path).resolve()
        public_roots.append(upload_path.resolve())

    for public_root in public_roots:
        try:
            resolved.relative_to(public_root)
        except ValueError:
            continue
        raise RuntimeError(
            "Le dossier de sauvegarde ne doit pas etre dans un dossier public "
            f"comme static/uploads: {resolved}"
        )


def _resolve_backup_dir(custom_dir: str | None = None) -> Path:
    configured = (custom_dir or "").strip() or str(current_app.config.get("MAINTENANCE_BACKUP_DIR") or "").strip()
    if not configured:
        configured = str((_project_root() / "backups").resolve())
    path = Path(configured)
    if not path.is_absolute():
        path = (_project_root() / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    _guard_backup_dir_not_public(path)

    if not _validate_backup_dir(path):
        raise RuntimeError(f"Le dossier de backup {path} n'est pas accessible en écriture.")

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


def _backup_retention_days(value: int | None = None) -> int:
    if value is not None:
        return max(1, int(value))
    configured = current_app.config.get("DB_BACKUP_RETENTION_DAYS", 30)
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return 30


def _find_required_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(
            f"{name} est introuvable sur ce serveur. Installe le client MySQL "
            f"ou lance la commande depuis un serveur qui contient {name}."
        )
    return executable


def _mysql_client_defaults_file() -> tuple[str, str]:
    url = db.engine.url
    username = url.username or ""
    password = url.password or ""
    host = url.host or "localhost"
    port = url.port
    database = url.database or ""
    if not database:
        raise RuntimeError("Nom de base MySQL introuvable dans la configuration.")

    lines = [
        "[client]",
        f"user={username}",
        f"password={password}",
        f"host={host}",
        "default-character-set=utf8mb4",
    ]
    if port:
        lines.append(f"port={port}")

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="dealnova_mysql_",
        suffix=".cnf",
        delete=False,
    )
    try:
        handle.write("\n".join(lines) + "\n")
        defaults_path = handle.name
    finally:
        handle.close()

    try:
        os.chmod(defaults_path, 0o600)
    except OSError:
        pass
    return defaults_path, database


def _write_backup_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def prune_database_backups(
    *,
    backup_dir: str | None = None,
    retention_days: int | None = None,
) -> list[str]:
    destination_dir = _resolve_backup_dir(backup_dir)
    safe_retention = _backup_retention_days(retention_days)
    cutoff = datetime.utcnow() - timedelta(days=safe_retention)
    removed: list[str] = []

    for path in destination_dir.glob("dealnova_db_*"):
        try:
            if datetime.utcfromtimestamp(path.stat().st_mtime) >= cutoff:
                continue
            if path.suffix not in {".gz", ".json", ".sqlite3"}:
                continue
            path.unlink()
            removed.append(str(path))
        except OSError:
            continue
    return removed


def _create_sqlite_database_backup(destination_dir: Path, timestamp: str) -> Path:
    db_path = _sqlite_db_file_path()
    if db_path is None or not db_path.exists():
        raise RuntimeError("Fichier SQLite introuvable pour la sauvegarde.")

    backup_file = destination_dir / f"dealnova_db_sqlite_{timestamp}.sqlite3"
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
    return backup_file


def _create_mysql_database_backup(destination_dir: Path, timestamp: str) -> tuple[Path, str]:
    mysqldump = _find_required_executable("mysqldump")
    defaults_path, database = _mysql_client_defaults_file()
    backup_file = destination_dir / f"dealnova_db_mysql_{timestamp}.sql.gz"
    command = [
        mysqldump,
        f"--defaults-extra-file={defaults_path}",
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--events",
        "--default-character-set=utf8mb4",
        database,
    ]

    try:
        with gzip.open(backup_file, "wb") as output:
            result = subprocess.run(
                command,
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            backup_file.unlink(missing_ok=True)
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"mysqldump a echoue: {error or 'erreur inconnue'}")
    finally:
        try:
            Path(defaults_path).unlink(missing_ok=True)
        except OSError:
            pass
    return backup_file, database


def create_database_backup(
    *,
    backup_dir: str | None = None,
    retention_days: int | None = None,
) -> dict[str, Any]:
    destination_dir = _resolve_backup_dir(backup_dir)
    safe_retention = _backup_retention_days(retention_days)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backend = _db_backend_name()
    database_name = ""

    if backend == "mysql":
        backup_file, database_name = _create_mysql_database_backup(destination_dir, timestamp)
    elif backend == "sqlite":
        backup_file = _create_sqlite_database_backup(destination_dir, timestamp)
        database_name = str(_sqlite_db_file_path() or "")
    else:
        raise RuntimeError(f"Sauvegarde non supportee pour ce moteur de base: {backend or 'inconnu'}")

    removed = prune_database_backups(
        backup_dir=str(destination_dir),
        retention_days=safe_retention,
    )
    manifest_file = backup_file.with_suffix(backup_file.suffix + ".json")
    manifest = {
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "db_engine": backend,
        "database": database_name,
        "backup_file": str(backup_file),
        "backup_dir": str(destination_dir),
        "size_bytes": backup_file.stat().st_size,
        "retention_days": safe_retention,
        "removed_old_backups": removed,
    }
    _write_backup_manifest(manifest_file, manifest)
    manifest["manifest_file"] = str(manifest_file)
    return manifest


def list_database_backups(*, backup_dir: str | None = None) -> list[dict[str, Any]]:
    destination_dir = _resolve_backup_dir(backup_dir)
    backups: list[dict[str, Any]] = []
    for path in sorted(destination_dir.glob("dealnova_db_*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.name.endswith(".json"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        manifest_path = path.with_suffix(path.suffix + ".json")
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
        backups.append(
            {
                "file": str(path),
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at_utc": datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                "db_engine": manifest.get("db_engine", "inconnu"),
                "database": manifest.get("database", ""),
            }
        )
    return backups


def import_database_backup(
    *,
    source_stream,
    filename: str,
    backup_dir: str | None = None,
) -> dict[str, Any]:
    raw_name = (filename or "").strip()
    if not raw_name.endswith(".sql.gz"):
        raise RuntimeError("Import refuse: seuls les fichiers .sql.gz sont acceptes.")

    secure_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw_name)
    secure_name = secure_name.strip("._") or "backup.sql.gz"
    if not secure_name.endswith(".sql.gz"):
        raise RuntimeError("Import refuse: nom de fichier invalide.")

    destination_dir = _resolve_backup_dir(backup_dir)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    destination = destination_dir / f"dealnova_db_mysql_imported_{timestamp}_{secure_name}"
    source_stream.save(str(destination))

    manifest_file = destination.with_suffix(destination.suffix + ".json")
    manifest = {
        "imported_at_utc": datetime.utcnow().isoformat() + "Z",
        "db_engine": "mysql",
        "database": "",
        "backup_file": str(destination),
        "backup_dir": str(destination_dir),
        "original_filename": raw_name,
        "size_bytes": destination.stat().st_size,
    }
    _write_backup_manifest(manifest_file, manifest)
    manifest["manifest_file"] = str(manifest_file)
    return manifest


def restore_database_backup(
    backup_file: str,
    *,
    yes: bool = False,
) -> dict[str, Any]:
    if not yes:
        raise RuntimeError("Restauration refusee: ajoute --yes pour confirmer.")

    path = Path(backup_file).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Fichier de sauvegarde introuvable: {path}")

    backend = _db_backend_name()
    if backend != "mysql":
        raise RuntimeError("Restauration simple supportee uniquement pour MySQL en production.")
    if not path.name.endswith(".sql.gz"):
        raise RuntimeError("La restauration MySQL attend un fichier .sql.gz.")

    mysql = _find_required_executable("mysql")
    defaults_path, database = _mysql_client_defaults_file()
    command = [
        mysql,
        f"--defaults-extra-file={defaults_path}",
        "--default-character-set=utf8mb4",
        database,
    ]
    try:
        with gzip.open(path, "rb") as dump:
            result = subprocess.run(
                command,
                stdin=dump,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"mysql restore a echoue: {error or 'erreur inconnue'}")
    finally:
        try:
            Path(defaults_path).unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "restored_file": str(path),
        "db_engine": backend,
        "database": database,
        "restored_at_utc": datetime.utcnow().isoformat() + "Z",
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

    # ── Protection vidéos produits ──────────────────────────────────────
    # Tous les fichiers dans uploads/product_videos/ sont considérés utilisés
    # pour éviter leur suppression lors du nettoyage des orphelins.
    try:
        videos_dir = _uploads_root() / "product_videos"
        if videos_dir.exists():
            for video_file in videos_dir.iterdir():
                if video_file.is_file():
                    rel = _safe_rel_from_static(video_file)
                    if rel:
                        used.add(rel)
    except Exception:
        pass
    # ────────────────────────────────────────────────────────────────────

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


def _db_backend_name() -> str:
    try:
        return str(db.engine.url.get_backend_name() or "").strip().lower()
    except Exception:
        uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip().lower()
        if uri.startswith("mysql"):
            return "mysql"
        if uri.startswith("postgresql") or uri.startswith("postgres"):
            return "postgresql"
        if uri.startswith("sqlite"):
            return "sqlite"
        return ""


def _mysql_db_size_bytes() -> int | None:
    try:
        with db.engine.connect() as conn:
            db_name = conn.execute(text("SELECT DATABASE()")).scalar()
            if not db_name:
                return None
            size_bytes = conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(data_length + index_length), 0)
                    FROM information_schema.tables
                    WHERE table_schema = :db_name
                    """
                ),
                {"db_name": db_name},
            ).scalar()
            if size_bytes is None:
                return None
            return int(size_bytes)
    except Exception:
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
    thresholds = _get_thresholds()

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
        "thresholds": thresholds,
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
        backend_name = _db_backend_name()
        if backend_name == "sqlite":
            health["db_engine"] = "SQLite"
            db_size_bytes = _sqlite_db_size_bytes()
            health["db_size_bytes"] = db_size_bytes
            if db_size_bytes is not None:
                health["db_size_mb"] = round(db_size_bytes / (1024.0 ** 2), 2)
            health["db_size"] = human_size(db_size_bytes)
        elif backend_name == "mysql":
            health["db_engine"] = "MySQL"
            db_size_bytes = _mysql_db_size_bytes()
            health["db_size_bytes"] = db_size_bytes
            if db_size_bytes is not None:
                health["db_size_mb"] = round(db_size_bytes / (1024.0 ** 2), 2)
            health["db_size"] = human_size(db_size_bytes)
        elif backend_name in {"postgresql", "postgres"}:
            health["db_engine"] = "PostgreSQL"
            health["db_size"] = "N/A"
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

        archives_deleted = 0

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


def _purge_stale_rate_limit_states(
    retention_days: int = RATE_LIMIT_STATE_RETENTION_DAYS_DEFAULT,
) -> tuple[int, str | None]:
    days = max(1, int(retention_days or RATE_LIMIT_STATE_RETENTION_DAYS_DEFAULT))
    cutoff = datetime.utcnow() - timedelta(days=days)
    try:
        deleted = (
            RuntimeState.query
            .filter(
                RuntimeState.state_key.like("rate:%"),
                RuntimeState.updated_at < cutoff,
            )
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


def localize_http_error_message(status_code: int | None, message: str | None) -> str | None:
    raw_message = " ".join(str(message or "").strip().replace("\n", " ").split())
    if not raw_message:
        return None

    safe_status = None
    try:
        safe_status = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        safe_status = None

    prefix, separator, detail = raw_message.partition(": ")
    translated_prefix = _HTTP_STATUS_LABELS_FR.get(safe_status, prefix)
    translated_detail = _HTTP_STATUS_DETAILS_FR.get(detail, detail)

    if separator:
        if translated_prefix != prefix or translated_detail != detail:
            return f"{translated_prefix}: {translated_detail}"[:255]
        return raw_message[:255]

    if safe_status in _HTTP_STATUS_LABELS_FR and raw_message == prefix:
        return _HTTP_STATUS_LABELS_FR[safe_status][:255]

    if raw_message in _HTTP_STATUS_DETAILS_FR:
        return _HTTP_STATUS_DETAILS_FR[raw_message][:255]

    return raw_message[:255]


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
        "rate_limit_states_purged": 0,
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

    deleted_rate_states, rate_states_error = _purge_stale_rate_limit_states()
    report["rate_limit_states_purged"] = deleted_rate_states
    if rate_states_error:
        report["errors"].append(f"rate_limit_states_purge: {rate_states_error}")

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
    safe_status = int(status_code)
    short_message = localize_http_error_message(safe_status, message)
    safe_path = (str(path or "").strip() or None)
    safe_method = (str(method or "").strip().upper()[:16] or None)

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


def cleanup_old_reports(days=20) -> int:
    """Supprime les rapports de maintenance plus vieux que days."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = MaintenanceRun.query.filter(MaintenanceRun.finished_at < cutoff).delete()
        db.session.commit()
        return deleted
    except Exception as e:
        db.session.rollback()
        return 0


# =====================================================
# NETTOYAGE AUTOMATIQUE NIGHTLY
# =====================================================

def auto_cleanup_nightly():
    """Nettoyage automatique quotidien (à lancer à 3h du matin)"""
    start = datetime.utcnow()
    results = {
        "sessions_deleted": 0,
        "logs_deleted": 0,
        "rate_limit_states_deleted": 0,
        "cache_cleared": False,
        "duration_ms": 0
    }

    try:
        # 1. Supprimer les sessions expirées
        _, sessions_deleted, sessions_error = _cleanup_expired_server_sessions()
        results["sessions_deleted"] = sessions_deleted
        if sessions_error:
            current_app.logger.warning(f"Erreur sessions: {sessions_error}")

        # 2. Nettoyer les vieux logs (>30 jours)
        cutoff = datetime.utcnow() - timedelta(days=30)
        deleted_logs = ErrorLog.query.filter(ErrorLog.created_at < cutoff).delete()
        results["logs_deleted"] = deleted_logs

        # 3. Nettoyer les anciens quotas de rate limit partagés
        deleted_rate_states, rate_states_error = _purge_stale_rate_limit_states()
        results["rate_limit_states_deleted"] = deleted_rate_states
        if rate_states_error:
            current_app.logger.warning(f"Erreur rate_limit_states: {rate_states_error}")

        # 4. Vider le cache périmé (pas tous les jours)
        if random.random() < 0.1:  # 10% de chance
            from .cache import cache
            cache.clear()
            results["cache_cleared"] = True

        db.session.commit()

        duration = (datetime.utcnow() - start).total_seconds() * 1000
        results["duration_ms"] = int(duration)

        current_app.logger.info(
            f"Nettoyage auto: {results['sessions_deleted']} sessions, "
            f"{results['logs_deleted']} logs, "
            f"{results['rate_limit_states_deleted']} rate states, "
            f"{'cache vidé' if results['cache_cleared'] else 'cache intact'} "
            f"({results['duration_ms']} ms)"
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Nettoyage auto échoué: {e}")
        results["error"] = str(e)

    return results


# =====================================================
# COMMANDES CLI
# =====================================================

def init_cli_commands(app):
    """Initialise les commandes CLI pour l'application."""

    @app.cli.command("nightly-cleanup")
    def nightly_cleanup_command():
        """Commande CLI pour le nettoyage automatique"""
        results = auto_cleanup_nightly()
        click.echo(f"Sessions supprimées: {results['sessions_deleted']}")
        click.echo(f"Logs supprimés: {results['logs_deleted']}")
        click.echo(f"Cache vidé: {results['cache_cleared']}")
        click.echo(f"Durée: {results['duration_ms']} ms")

    @app.cli.command("cleanup-old-reports")
    @click.option("--days", default=20, help="Nombre de jours de rétention")
    def cleanup_old_reports_command(days):
        """Supprime les anciens rapports de maintenance"""
        deleted = cleanup_old_reports(days=days)
        click.echo(f"{deleted} rapports supprimés (>{days} jours)")

    @app.cli.command("db-backup")
    @click.option("--backup-dir", default=None, help="Dossier de stockage des sauvegardes")
    @click.option("--retention-days", default=None, type=int, help="Nombre de jours a conserver")
    def db_backup_command(backup_dir, retention_days):
        """Cree une sauvegarde complete de la base de donnees."""
        result = create_database_backup(backup_dir=backup_dir, retention_days=retention_days)
        click.echo(f"Sauvegarde creee: {result['backup_file']}")
        click.echo(f"Manifeste: {result['manifest_file']}")
        click.echo(f"Retention: {result['retention_days']} jours")
        click.echo(f"Anciens fichiers supprimes: {len(result['removed_old_backups'])}")

    @app.cli.command("db-backups")
    @click.option("--backup-dir", default=None, help="Dossier de stockage des sauvegardes")
    def db_backups_command(backup_dir):
        """Liste les sauvegardes disponibles."""
        backups = list_database_backups(backup_dir=backup_dir)
        if not backups:
            click.echo("Aucune sauvegarde trouvee.")
            return
        for item in backups:
            size = human_size(item.get("size_bytes"))
            click.echo(f"{item['modified_at_utc']} | {size} | {item['db_engine']} | {item['file']}")

    @app.cli.command("db-restore")
    @click.argument("backup_file")
    @click.option("--yes", is_flag=True, help="Confirme la restauration")
    def db_restore_command(backup_file, yes):
        """Restaure une sauvegarde MySQL .sql.gz."""
        if not yes:
            click.confirm(
                "Cette action remplace la base actuelle par la sauvegarde choisie. Continuer ?",
                abort=True,
            )
        result = restore_database_backup(backup_file, yes=True)
        click.echo(f"Base restauree depuis: {result['restored_file']}")
        click.echo(f"Base cible: {result['database']}")
