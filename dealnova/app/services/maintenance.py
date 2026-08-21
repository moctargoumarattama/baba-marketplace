from __future__ import annotations

import json
import os
import gzip
import hashlib
import shutil
import sqlite3
import subprocess
import tarfile
import time
import random
import tempfile
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
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

DB_BACKUP_PREFIX = "dealnova_db_"
UPLOADS_BACKUP_PREFIX = "dealnova_uploads_"
FULL_BACKUP_PREFIX = "dealnova_full_"
PRE_RESET_BACKUP_PREFIX = "dealnova_pre_reset_"
BACKUP_PATH_CHUNK_SIZE = 1024 * 1024
BACKUP_DISK_MARGIN_BYTES = 64 * 1024 * 1024
BACKUP_DISK_MIN_REQUIRED_BYTES = 96 * 1024 * 1024
UPLOADS_RESTORE_CONFIRM_TEXT = "RESTAURER UPLOADS"
FULL_RESTORE_CONFIRM_TEXT = "RESTAURER COMPLET"

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


def _uploads_backup_retention_days(value: int | None = None) -> int:
    if value is not None:
        return max(1, int(value))
    configured = current_app.config.get("UPLOADS_BACKUP_RETENTION_DAYS", 14)
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return 14


def _full_backup_retention_days(value: int | None = None) -> int:
    if value is not None:
        return max(1, int(value))
    configured = current_app.config.get("FULL_BACKUP_RETENTION_DAYS", 14)
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return 14


def _full_backup_keep_latest_only(value: bool | None = None) -> bool:
    if value is not None:
        return bool(value)
    return bool(current_app.config.get("FULL_BACKUP_KEEP_LATEST_ONLY", False))


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


def _backup_timestamp(now: datetime | None = None) -> tuple[str, str]:
    created_at = now or datetime.utcnow()
    return created_at.strftime("%Y%m%d_%H%M%S"), created_at.isoformat() + "Z"


def _manifest_path_for_backup_file(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".json")


def _read_backup_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(BACKUP_PATH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _stamp_manifest_integrity(manifest: dict[str, Any], backup_path: Path, *, verified_at_utc: str | None = None) -> None:
    stat = backup_path.stat()
    manifest["size_bytes"] = int(stat.st_size)
    manifest["checksum_sha256"] = _file_sha256(backup_path)
    manifest["integrity_status"] = "valid"
    manifest["verified_at_utc"] = verified_at_utc or datetime.utcnow().isoformat() + "Z"
    manifest["verified_size_bytes"] = int(stat.st_size)
    manifest["verified_mtime_ns"] = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))


def _quick_integrity_report(path: Path, manifest: dict[str, Any], *, manifest_present: bool) -> dict[str, Any]:
    if not manifest_present:
        return {
            "state": "missing_manifest",
            "label": "⚠ Manifeste absent",
            "class_name": "status-warn",
            "details": "Aucun manifeste associe n'a ete trouve.",
        }

    expected_checksum = str(manifest.get("checksum_sha256") or "").strip().lower()
    if not expected_checksum:
        return {
            "state": "missing_checksum",
            "label": "⚠ Checksum absent",
            "class_name": "status-warn",
            "details": "Manifeste legacy detecte, verification SHA-256 non disponible sans action explicite.",
        }

    try:
        stat = path.stat()
    except OSError:
        return {
            "state": "missing_file",
            "label": "✗ Fichier manquant",
            "class_name": "status-danger",
            "details": "Le fichier de sauvegarde n'existe plus dans le dossier autorise.",
        }

    expected_size = manifest.get("verified_size_bytes", manifest.get("size_bytes"))
    try:
        if expected_size is not None and int(expected_size) != int(stat.st_size):
            return {
                "state": "invalid",
                "label": "✗ Checksum invalide",
                "class_name": "status-danger",
                "details": "La taille du fichier ne correspond plus au manifeste.",
            }
    except (TypeError, ValueError):
        pass

    expected_mtime = manifest.get("verified_mtime_ns")
    if expected_mtime is not None:
        try:
            current_mtime = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
            if int(expected_mtime) != current_mtime:
                return {
                    "state": "invalid",
                    "label": "✗ Checksum invalide",
                    "class_name": "status-danger",
                    "details": "Le fichier a ete modifie apres la derniere verification connue.",
                }
        except (TypeError, ValueError):
            pass

    if str(manifest.get("integrity_status") or "").strip().lower() == "invalid":
        return {
            "state": "invalid",
            "label": "✗ Checksum invalide",
            "class_name": "status-danger",
            "details": "Une verification precedente a detecte un ecart d'integrite.",
        }

    return {
        "state": "valid",
        "label": "✓ Integre",
        "class_name": "status-ok",
        "details": "Checksum SHA-256 present et metadonnees de verification coherentes.",
    }


def _verify_file_integrity(path: Path, *, manifest_path: Path | None = None) -> dict[str, Any]:
    resolved_manifest = manifest_path or _manifest_path_for_backup_file(path)
    manifest_present = resolved_manifest.exists()
    manifest = _read_backup_manifest(resolved_manifest) if manifest_present else {}
    return _verify_checksum_against_manifest_data(
        path,
        manifest,
        manifest_path=resolved_manifest if manifest_present else None,
        manifest_present=manifest_present,
    )


def _verify_checksum_against_manifest_data(
    path: Path,
    manifest: dict[str, Any],
    *,
    manifest_path: Path | None = None,
    manifest_present: bool = True,
) -> dict[str, Any]:
    expected_checksum = str(manifest.get("checksum_sha256") or "").strip().lower()
    if not manifest_present:
        return {
            "ok": False,
            "state": "missing_manifest",
            "label": "⚠ Manifeste absent",
            "path": str(path),
            "manifest_file": str(manifest_path) if manifest_path else "",
        }

    if not expected_checksum:
        return {
            "ok": False,
            "state": "missing_checksum",
            "label": "⚠ Checksum absent",
            "path": str(path),
            "manifest_file": str(manifest_path) if manifest_path else "",
        }

    try:
        actual_checksum = _file_sha256(path)
        stat = path.stat()
    except OSError:
        return {
            "ok": False,
            "state": "missing_file",
            "label": "✗ Fichier manquant",
            "path": str(path),
            "manifest_file": str(manifest_path) if manifest_path else "",
        }

    ok = actual_checksum == expected_checksum
    manifest["integrity_status"] = "valid" if ok else "invalid"
    manifest["last_verified_at_utc"] = datetime.utcnow().isoformat() + "Z"
    manifest["last_verified_checksum_sha256"] = actual_checksum
    manifest["verified_at_utc"] = manifest["last_verified_at_utc"]
    manifest["verified_size_bytes"] = int(stat.st_size)
    manifest["verified_mtime_ns"] = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
    if manifest_path is not None:
        _write_backup_manifest(manifest_path, manifest)
    return {
        "ok": ok,
        "state": "valid" if ok else "invalid",
        "label": "✓ Integre" if ok else "✗ Checksum invalide",
        "path": str(path),
        "manifest_file": str(manifest_path) if manifest_path else "",
        "expected_checksum_sha256": expected_checksum,
        "actual_checksum_sha256": actual_checksum,
    }


def _is_allowed_backup_filename(name: str) -> bool:
    if not name or name != Path(name).name:
        return False

    allowed_prefixes = (
        DB_BACKUP_PREFIX,
        UPLOADS_BACKUP_PREFIX,
        FULL_BACKUP_PREFIX,
        PRE_RESET_BACKUP_PREFIX,
    )
    allowed_suffixes = (
        ".sql.gz",
        ".sql.gz.json",
        ".sqlite3",
        ".sqlite3.json",
        ".tar.gz",
        ".tar.gz.json",
        ".json",
    )
    return name.startswith(allowed_prefixes) and name.endswith(allowed_suffixes)


def resolve_managed_backup_path(filename: str, *, backup_dir: str | None = None) -> Path:
    raw_name = (filename or "").strip()
    if not _is_allowed_backup_filename(raw_name):
        raise RuntimeError("Nom de fichier de sauvegarde invalide.")

    destination_dir = _resolve_backup_dir(backup_dir)
    path = (destination_dir / raw_name).resolve()
    try:
        path.relative_to(destination_dir.resolve())
    except ValueError as exc:
        raise RuntimeError("Acces refuse au fichier demande.") from exc

    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Fichier de sauvegarde introuvable: {path}")
    return path


def _prune_backup_prefix(
    *,
    destination_dir: Path,
    prefix: str,
    retention_days: int,
    allowed_name_endings: tuple[str, ...],
) -> list[str]:
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    removed: list[str] = []

    for path in destination_dir.iterdir():
        try:
            if not path.is_file():
                continue
            if not path.name.startswith(prefix):
                continue
            if not path.name.endswith(allowed_name_endings):
                continue
            if datetime.utcfromtimestamp(path.stat().st_mtime) >= cutoff:
                continue
            path.unlink()
            removed.append(str(path))
        except OSError:
            continue
    return removed


def _ensure_free_space_for_backup(*, destination_dir: Path, estimated_bytes: int, label: str) -> dict[str, int]:
    usage = shutil.disk_usage(destination_dir)
    estimated = max(0, int(estimated_bytes or 0))
    required = max(
        BACKUP_DISK_MIN_REQUIRED_BYTES,
        estimated + max(BACKUP_DISK_MARGIN_BYTES, estimated // 10),
    )
    if usage.free < required:
        raise RuntimeError(
            f"Espace disque insuffisant pour la sauvegarde {label}: "
            f"{human_size(usage.free)} libres, environ {human_size(required)} necessaires."
        )
    return {
        "free_bytes": int(usage.free),
        "required_bytes": int(required),
        "estimated_bytes": estimated,
    }


def _resolve_full_backup_component_path(raw_path: str | None, *, backup_dir: Path) -> Path:
    candidate_name = Path(str(raw_path or "").strip()).name
    return resolve_managed_backup_path(candidate_name, backup_dir=str(backup_dir))


def _backup_name_has_timestamp(name: str, timestamp: str) -> bool:
    return f"_{timestamp}." in name


def _collect_full_backup_component_targets(manifest_path: Path) -> list[Path]:
    targets = [manifest_path]
    manifest = _read_backup_manifest(manifest_path)
    if str(manifest.get("type") or "").strip().lower() != "full":
        return targets

    backup_dir = manifest_path.parent.resolve()
    for key in ("database_backup", "uploads_backup"):
        item = manifest.get(key) or {}
        raw_file = str(item.get("file") or "").strip()
        if not raw_file:
            continue
        try:
            component_path = _resolve_full_backup_component_path(raw_file, backup_dir=backup_dir)
        except RuntimeError:
            continue
        targets.append(component_path)
        targets.append(_manifest_path_for_backup_file(component_path))

        raw_manifest = str(item.get("manifest_file") or "").strip()
        if not raw_manifest:
            continue
        try:
            targets.append(_resolve_full_backup_component_path(raw_manifest, backup_dir=backup_dir))
        except RuntimeError:
            continue
    return targets


def _prune_full_backup_sets_except_timestamp(*, destination_dir: Path, keep_timestamp: str) -> list[str]:
    removed: list[str] = []
    seen: set[Path] = set()

    for manifest_path in sorted(destination_dir.glob(f"{FULL_BACKUP_PREFIX}*.json")):
        if _backup_name_has_timestamp(manifest_path.name, keep_timestamp):
            continue
        for target in _collect_full_backup_component_targets(manifest_path):
            if target in seen:
                continue
            seen.add(target)
            try:
                if not target.exists() or not target.is_file():
                    continue
                if not _is_allowed_backup_filename(target.name):
                    continue
                target.unlink()
                removed.append(str(target))
            except OSError:
                continue
    return removed


def prune_database_backups(
    *,
    backup_dir: str | None = None,
    retention_days: int | None = None,
) -> list[str]:
    destination_dir = _resolve_backup_dir(backup_dir)
    safe_retention = _backup_retention_days(retention_days)
    return _prune_backup_prefix(
        destination_dir=destination_dir,
        prefix=DB_BACKUP_PREFIX,
        retention_days=safe_retention,
        allowed_name_endings=(".sql.gz", ".sql.gz.json", ".sqlite3", ".sqlite3.json"),
    )


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
    timestamp: str | None = None,
    created_at_utc: str | None = None,
    prune_existing: bool = True,
) -> dict[str, Any]:
    destination_dir = _resolve_backup_dir(backup_dir)
    safe_retention = _backup_retention_days(retention_days)
    backup_timestamp = timestamp or _backup_timestamp()[0]
    backend = _db_backend_name()
    database_name = ""

    if backend == "mysql":
        backup_file, database_name = _create_mysql_database_backup(destination_dir, backup_timestamp)
    elif backend == "sqlite":
        backup_file = _create_sqlite_database_backup(destination_dir, backup_timestamp)
        database_name = str(_sqlite_db_file_path() or "")
    else:
        raise RuntimeError(f"Sauvegarde non supportee pour ce moteur de base: {backend or 'inconnu'}")

    removed = []
    if prune_existing:
        removed = prune_database_backups(
            backup_dir=str(destination_dir),
            retention_days=safe_retention,
        )
    manifest_file = _manifest_path_for_backup_file(backup_file)
    manifest_created_at_utc = created_at_utc or datetime.utcnow().isoformat() + "Z"
    manifest = {
        "created_at_utc": manifest_created_at_utc,
        "type": "database",
        "db_engine": backend,
        "database": database_name,
        "backup_file": str(backup_file),
        "backup_dir": str(destination_dir),
        "retention_days": safe_retention,
        "removed_old_backups": removed,
    }
    _stamp_manifest_integrity(manifest, backup_file, verified_at_utc=manifest_created_at_utc)
    _write_backup_manifest(manifest_file, manifest)
    manifest["manifest_file"] = str(manifest_file)
    current_app.logger.info(
        "maintenance.database_backup.created",
        extra={
            "backup_file": str(backup_file),
            "backup_dir": str(destination_dir),
            "db_engine": backend,
        },
    )
    return manifest


def list_database_backups(*, backup_dir: str | None = None) -> list[dict[str, Any]]:
    destination_dir = _resolve_backup_dir(backup_dir)
    backups: list[dict[str, Any]] = []
    for path in sorted(destination_dir.glob(f"{DB_BACKUP_PREFIX}*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.name.endswith(".json"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        manifest_path = _manifest_path_for_backup_file(path)
        manifest_present = manifest_path.exists()
        manifest: dict[str, Any] = _read_backup_manifest(manifest_path) if manifest_present else {}
        integrity = _quick_integrity_report(path, manifest, manifest_present=manifest_present)
        backups.append(
            {
                "kind": "database",
                "type": "database",
                "type_label": "Base de donnees",
                "file": str(path),
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at_utc": datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                "db_engine": manifest.get("db_engine", "inconnu"),
                "database": manifest.get("database", ""),
                "manifest_file": str(manifest_path) if manifest_present else "",
                "manifest_name": manifest_path.name if manifest_present else "",
                "manifest_present": manifest_present,
                "checksum_sha256": manifest.get("checksum_sha256", ""),
                "checksum_short": str(manifest.get("checksum_sha256", ""))[:12],
                "integrity_state": integrity["state"],
                "integrity_label": integrity["label"],
                "integrity_class": integrity["class_name"],
                "integrity_details": integrity["details"],
                "status_label": "Disponible",
                "downloads": [
                    {"label": "Archive DB", "name": path.name},
                    *([{"label": "Manifeste", "name": manifest_path.name}] if manifest_present else []),
                ],
                "restore_supported": path.name.endswith(".sql.gz"),
                "restore_confirm_text": "RESTAURER",
                "restore_button_label": "Restaurer la base",
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
    timestamp, created_at_utc = _backup_timestamp()
    destination = destination_dir / f"dealnova_db_mysql_imported_{timestamp}_{secure_name}"
    source_stream.save(str(destination))

    manifest_file = _manifest_path_for_backup_file(destination)
    manifest = {
        "imported_at_utc": created_at_utc,
        "created_at_utc": created_at_utc,
        "type": "database",
        "db_engine": "mysql",
        "database": "",
        "backup_file": str(destination),
        "backup_dir": str(destination_dir),
        "original_filename": raw_name,
    }
    _stamp_manifest_integrity(manifest, destination, verified_at_utc=created_at_utc)
    _write_backup_manifest(manifest_file, manifest)
    manifest["manifest_file"] = str(manifest_file)
    current_app.logger.info(
        "maintenance.database_backup.imported",
        extra={
            "backup_file": str(destination),
            "backup_dir": str(destination_dir),
            "original_filename": raw_name,
        },
    )
    return manifest


def restore_database_backup(
    backup_file: str,
    *,
    yes: bool = False,
    verify_manifest: bool = True,
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

    verification: dict[str, Any] | None = None
    if verify_manifest:
        verification = _verify_file_integrity(path)
        if verification.get("state") == "invalid":
            raise RuntimeError("Restauration refusee: checksum de la sauvegarde invalide.")

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
        "integrity_check": verification,
    }


def _uploads_root() -> Path:
    configured = str(current_app.config.get("UPLOAD_FOLDER") or "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = (_project_root() / path).resolve()
        return path.resolve()
    return Path(current_app.static_folder).resolve() / "uploads"


def _safe_rel_from_static(path: Path) -> str | None:
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(Path(current_app.static_folder).resolve()).as_posix()
        return rel
    except Exception:
        try:
            rel = resolved.relative_to(_uploads_root().resolve()).as_posix()
            rel = rel.strip("/")
            return f"uploads/{rel}" if rel else "uploads"
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


def prune_uploads_backups(
    *,
    backup_dir: str | None = None,
    retention_days: int | None = None,
) -> list[str]:
    destination_dir = _resolve_backup_dir(backup_dir)
    safe_retention = _uploads_backup_retention_days(retention_days)
    return _prune_backup_prefix(
        destination_dir=destination_dir,
        prefix=UPLOADS_BACKUP_PREFIX,
        retention_days=safe_retention,
        allowed_name_endings=(".tar.gz", ".tar.gz.json"),
    )


def prune_full_backups(
    *,
    backup_dir: str | None = None,
    retention_days: int | None = None,
) -> list[str]:
    destination_dir = _resolve_backup_dir(backup_dir)
    safe_retention = _full_backup_retention_days(retention_days)
    return _prune_backup_prefix(
        destination_dir=destination_dir,
        prefix=FULL_BACKUP_PREFIX,
        retention_days=safe_retention,
        allowed_name_endings=(".json",),
    )


def _estimated_database_backup_size_bytes() -> int:
    backend = _db_backend_name()
    if backend == "sqlite":
        return int(_sqlite_db_size_bytes() or 0)
    if backend == "mysql":
        size = _mysql_db_size_bytes()
        return int(size) if size is not None else 64 * 1024 * 1024
    return 0


def _safe_archive_member_path(raw_name: str) -> PurePosixPath:
    normalized = PurePosixPath(str(raw_name or "").replace("\\", "/"))
    if normalized.is_absolute():
        raise RuntimeError("Archive uploads invalide: chemins absolus interdits.")

    safe_parts: list[str] = []
    for part in normalized.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise RuntimeError("Archive uploads invalide: tentative de sortie du dossier uploads detectee.")
        if part.endswith(":"):
            raise RuntimeError("Archive uploads invalide: lecteur absolu interdit.")
        safe_parts.append(part)

    if not safe_parts:
        return PurePosixPath(".")

    if safe_parts[0] == "uploads":
        safe_parts = safe_parts[1:]
    return PurePosixPath(*safe_parts) if safe_parts else PurePosixPath(".")


def _extract_validated_uploads_archive(archive_path: Path, destination_root: Path) -> dict[str, Any]:
    file_count = 0
    total_size = 0
    destination_root.mkdir(parents=True, exist_ok=True)
    root_resolved = destination_root.resolve()

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if member.issym() or member.islnk():
                    raise RuntimeError("Archive uploads invalide: liens symboliques et hard links refuses.")
                if member.isdev():
                    raise RuntimeError("Archive uploads invalide: fichiers speciaux refuses.")

                safe_rel = _safe_archive_member_path(member.name)
                if safe_rel == PurePosixPath("."):
                    if member.isdir():
                        continue
                    raise RuntimeError("Archive uploads invalide: membre vide non supporte.")

                destination_path = (destination_root / Path(*safe_rel.parts)).resolve()
                try:
                    destination_path.relative_to(root_resolved)
                except ValueError as exc:
                    raise RuntimeError("Archive uploads invalide: tentative de sortie du dossier de restauration.") from exc

                if member.isdir():
                    destination_path.mkdir(parents=True, exist_ok=True)
                    continue

                if not member.isfile():
                    raise RuntimeError("Archive uploads invalide: type de fichier non supporte.")

                destination_path.parent.mkdir(parents=True, exist_ok=True)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError("Archive uploads invalide: lecture d'un membre impossible.")
                with extracted, destination_path.open("wb") as output:
                    shutil.copyfileobj(extracted, output, BACKUP_PATH_CHUNK_SIZE)

                file_count += 1
                total_size += int(destination_path.stat().st_size)
    except tarfile.TarError as exc:
        raise RuntimeError("Archive uploads invalide ou corrompue.") from exc

    return {
        "file_count": file_count,
        "size_bytes": total_size,
    }


def _rename_path(source: Path, target: Path) -> None:
    source.replace(target)


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    shutil.rmtree(path)


def _replace_directory_atomically(*, live_dir: Path, prepared_dir: Path, rollback_dir: Path) -> None:
    moved_live = False
    try:
        if rollback_dir.exists():
            _remove_tree(rollback_dir)

        if live_dir.exists():
            _rename_path(live_dir, rollback_dir)
            moved_live = True

        _rename_path(prepared_dir, live_dir)
    except Exception:
        if live_dir.exists() and live_dir != prepared_dir:
            try:
                _remove_tree(live_dir)
            except Exception:
                pass
        if moved_live and rollback_dir.exists():
            _rename_path(rollback_dir, live_dir)
        raise


def create_uploads_backup(
    *,
    backup_dir: str | None = None,
    retention_days: int | None = None,
    timestamp: str | None = None,
    created_at_utc: str | None = None,
    reason: str | None = None,
    prune_existing: bool = True,
) -> dict[str, Any]:
    destination_dir = _resolve_backup_dir(backup_dir)
    safe_retention = _uploads_backup_retention_days(retention_days)
    uploads_root = _uploads_root()
    if uploads_root.exists() and not uploads_root.is_dir():
        raise RuntimeError(f"Dossier uploads invalide: {uploads_root}")
    uploads_bytes, uploads_files = _uploads_size_bytes()
    disk_check = _ensure_free_space_for_backup(
        destination_dir=destination_dir,
        estimated_bytes=uploads_bytes,
        label="uploads",
    )

    archive_timestamp = timestamp or _backup_timestamp()[0]
    manifest_created_at_utc = created_at_utc or datetime.utcnow().isoformat() + "Z"
    archive_file = destination_dir / f"{UPLOADS_BACKUP_PREFIX}{archive_timestamp}.tar.gz"
    manifest_file = _manifest_path_for_backup_file(archive_file)

    added_files = 0
    try:
        with tarfile.open(archive_file, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            if uploads_root.exists():
                for root, dirnames, filenames in os.walk(uploads_root, topdown=True, followlinks=False):
                    root_path = Path(root)
                    dirnames[:] = [
                        name
                        for name in dirnames
                        if not (root_path / name).is_symlink()
                    ]

                    rel_root = root_path.relative_to(uploads_root).as_posix()
                    if rel_root and rel_root != ".":
                        dir_info = archive.gettarinfo(str(root_path), arcname=rel_root)
                        if dir_info.isdir():
                            archive.addfile(dir_info)

                    for filename in filenames:
                        source_path = root_path / filename
                        if source_path.is_symlink():
                            current_app.logger.warning(
                                "maintenance.uploads_backup.skip_symlink",
                                extra={"path": str(source_path)},
                            )
                            continue

                        rel_path = source_path.relative_to(uploads_root).as_posix()
                        file_info = archive.gettarinfo(str(source_path), arcname=rel_path)
                        if not file_info.isfile():
                            continue
                        with source_path.open("rb") as handle:
                            archive.addfile(file_info, handle)
                        added_files += 1
    except Exception:
        archive_file.unlink(missing_ok=True)
        manifest_file.unlink(missing_ok=True)
        raise

    removed = []
    if prune_existing:
        removed = prune_uploads_backups(
            backup_dir=str(destination_dir),
            retention_days=safe_retention,
        )
    manifest = {
        "created_at_utc": manifest_created_at_utc,
        "type": "uploads",
        "archive_file": str(archive_file),
        "backup_file": str(archive_file),
        "backup_dir": str(destination_dir),
        "file_count": int(added_files if uploads_root.exists() else uploads_files),
        "uploads_source": str(uploads_root),
        "retention_days": safe_retention,
        "removed_old_backups": removed,
        "disk_free_bytes_before_backup": disk_check["free_bytes"],
        "disk_required_bytes": disk_check["required_bytes"],
        "reason": reason or "",
    }
    _stamp_manifest_integrity(manifest, archive_file, verified_at_utc=manifest_created_at_utc)
    _write_backup_manifest(manifest_file, manifest)
    manifest["manifest_file"] = str(manifest_file)
    current_app.logger.info(
        "maintenance.uploads_backup.created",
        extra={
            "archive_file": str(archive_file),
            "backup_dir": str(destination_dir),
            "file_count": manifest["file_count"],
        },
    )
    return manifest


def list_uploads_backups(*, backup_dir: str | None = None) -> list[dict[str, Any]]:
    destination_dir = _resolve_backup_dir(backup_dir)
    backups: list[dict[str, Any]] = []
    for path in sorted(destination_dir.glob(f"{UPLOADS_BACKUP_PREFIX}*.tar.gz"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue

        manifest_path = _manifest_path_for_backup_file(path)
        manifest_present = manifest_path.exists()
        manifest = _read_backup_manifest(manifest_path) if manifest_present else {}
        integrity = _quick_integrity_report(path, manifest, manifest_present=manifest_present)
        backups.append(
            {
                "kind": "uploads",
                "type": "uploads",
                "type_label": "Uploads",
                "file": str(path),
                "name": path.name,
                "size_bytes": int(stat.st_size),
                "modified_at_utc": datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                "manifest_file": str(manifest_path) if manifest_present else "",
                "manifest_name": manifest_path.name if manifest_present else "",
                "manifest_present": manifest_present,
                "checksum_sha256": manifest.get("checksum_sha256", ""),
                "checksum_short": str(manifest.get("checksum_sha256", ""))[:12],
                "integrity_state": integrity["state"],
                "integrity_label": integrity["label"],
                "integrity_class": integrity["class_name"],
                "integrity_details": integrity["details"],
                "status_label": "Disponible",
                "uploads_file_count": int(manifest.get("file_count", 0) or 0),
                "downloads": [
                    {"label": "Archive uploads", "name": path.name},
                    *([{"label": "Manifeste", "name": manifest_path.name}] if manifest_present else []),
                ],
                "restore_supported": True,
                "restore_confirm_text": UPLOADS_RESTORE_CONFIRM_TEXT,
                "restore_button_label": "Restaurer les uploads",
            }
        )
    return backups


def create_full_backup(
    *,
    backup_dir: str | None = None,
    db_retention_days: int | None = None,
    uploads_retention_days: int | None = None,
    full_retention_days: int | None = None,
    keep_latest_only: bool | None = None,
) -> dict[str, Any]:
    destination_dir = _resolve_backup_dir(backup_dir)
    timestamp, created_at_utc = _backup_timestamp()
    keep_latest = _full_backup_keep_latest_only(keep_latest_only)
    safe_full_retention = _full_backup_retention_days(full_retention_days)
    safe_db_retention = max(_backup_retention_days(db_retention_days), safe_full_retention)
    safe_uploads_retention = max(_uploads_backup_retention_days(uploads_retention_days), safe_full_retention)
    uploads_bytes, _ = _uploads_size_bytes()
    _ensure_free_space_for_backup(
        destination_dir=destination_dir,
        estimated_bytes=uploads_bytes + _estimated_database_backup_size_bytes(),
        label="complete",
    )

    db_backup = create_database_backup(
        backup_dir=str(destination_dir),
        retention_days=safe_db_retention,
        timestamp=timestamp,
        created_at_utc=created_at_utc,
        prune_existing=not keep_latest,
    )
    try:
        uploads_backup = create_uploads_backup(
            backup_dir=str(destination_dir),
            retention_days=safe_uploads_retention,
            timestamp=timestamp,
            created_at_utc=created_at_utc,
            prune_existing=not keep_latest,
        )
    except Exception as exc:
        current_app.logger.exception(
            "maintenance.full_backup.partial",
            extra={
                "backup_dir": str(destination_dir),
                "db_backup_file": db_backup.get("backup_file"),
            },
        )
        return {
            "success": False,
            "state": "partial",
            "error": str(exc),
            "timestamp": timestamp,
            "created_at_utc": created_at_utc,
            "backup_dir": str(destination_dir),
            "db_engine": db_backup.get("db_engine"),
            "db_backup": db_backup,
            "uploads_backup": None,
            "keep_latest_only": keep_latest,
        }

    manifest_file = destination_dir / f"{FULL_BACKUP_PREFIX}{timestamp}.json"
    removed = []
    manifest = {
        "created_at_utc": created_at_utc,
        "type": "full",
        "format_version": 1,
        "backup_dir": str(destination_dir),
        "retention_days": safe_full_retention,
        "removed_old_backups": removed,
        "keep_latest_only": keep_latest,
        "db_engine": db_backup.get("db_engine"),
        "database_backup": {
            "file": db_backup.get("backup_file"),
            "manifest_file": db_backup.get("manifest_file"),
            "checksum_sha256": db_backup.get("checksum_sha256"),
            "size_bytes": db_backup.get("size_bytes"),
            "verified_mtime_ns": db_backup.get("verified_mtime_ns"),
            "database": db_backup.get("database"),
        },
        "uploads_backup": {
            "file": uploads_backup.get("backup_file"),
            "manifest_file": uploads_backup.get("manifest_file"),
            "checksum_sha256": uploads_backup.get("checksum_sha256"),
            "size_bytes": uploads_backup.get("size_bytes"),
            "verified_mtime_ns": uploads_backup.get("verified_mtime_ns"),
            "file_count": uploads_backup.get("file_count"),
            "uploads_source": uploads_backup.get("uploads_source"),
        },
        "total_size_bytes": int((db_backup.get("size_bytes") or 0) + (uploads_backup.get("size_bytes") or 0)),
    }
    _write_backup_manifest(manifest_file, manifest)
    if keep_latest:
        removed = _prune_full_backup_sets_except_timestamp(
            destination_dir=destination_dir,
            keep_timestamp=timestamp,
        )
        manifest["removed_old_backups"] = removed
        _write_backup_manifest(manifest_file, manifest)
    else:
        removed = prune_full_backups(
            backup_dir=str(destination_dir),
            retention_days=safe_full_retention,
        )
        manifest["removed_old_backups"] = removed
        _write_backup_manifest(manifest_file, manifest)
    current_app.logger.info(
        "maintenance.full_backup.created",
        extra={
            "manifest_file": str(manifest_file),
            "backup_dir": str(destination_dir),
            "db_backup_file": db_backup.get("backup_file"),
            "uploads_backup_file": uploads_backup.get("backup_file"),
            "keep_latest_only": keep_latest,
        },
    )
    return {
        "success": True,
        "state": "complete",
        "timestamp": timestamp,
        "created_at_utc": created_at_utc,
        "backup_dir": str(destination_dir),
        "manifest_file": str(manifest_file),
        "db_engine": db_backup.get("db_engine"),
        "db_backup": db_backup,
        "uploads_backup": uploads_backup,
        "removed_old_backups": removed,
        "retention_days": safe_full_retention,
        "keep_latest_only": keep_latest,
        "size_bytes": manifest["total_size_bytes"],
    }


def _quick_full_backup_integrity(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if str(manifest.get("type") or "").strip().lower() != "full":
        return {
            "state": "invalid",
            "label": "✗ Checksum invalide",
            "class_name": "status-danger",
            "details": "Le manifeste complet est invalide ou incomplet.",
        }

    backup_dir = manifest_path.parent.resolve()
    for key in ("database_backup", "uploads_backup"):
        item = manifest.get(key) or {}
        backup_file = str(item.get("file") or "").strip()
        if not backup_file:
            return {
                "state": "invalid",
                "label": "✗ Checksum invalide",
                "class_name": "status-danger",
                "details": "Le manifeste complet ne reference pas tous les fichiers attendus.",
            }
        try:
            path = _resolve_full_backup_component_path(backup_file, backup_dir=backup_dir)
        except Exception:
            return {
                "state": "invalid",
                "label": "✗ Checksum invalide",
                "class_name": "status-danger",
                "details": "Le manifeste complet reference un fichier hors du dossier de sauvegarde autorise.",
            }
        report = _quick_integrity_report(
            path,
            {
                "checksum_sha256": item.get("checksum_sha256"),
                "size_bytes": item.get("size_bytes"),
                "verified_size_bytes": item.get("size_bytes"),
                "verified_mtime_ns": item.get("verified_mtime_ns"),
                "integrity_status": "valid",
            },
            manifest_present=True,
        )
        if report["state"] != "valid":
            return report

    return {
        "state": "valid",
        "label": "✓ Integre",
        "class_name": "status-ok",
        "details": "Les composants references par le backup complet sont coherents selon leurs checksums stockes.",
    }


def list_full_backups(*, backup_dir: str | None = None) -> list[dict[str, Any]]:
    destination_dir = _resolve_backup_dir(backup_dir)
    backups: list[dict[str, Any]] = []
    for path in sorted(destination_dir.glob(f"{FULL_BACKUP_PREFIX}*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue

        manifest = _read_backup_manifest(path)
        if not manifest:
            continue
        integrity = _quick_full_backup_integrity(path, manifest)
        db_backup = manifest.get("database_backup") or {}
        uploads_backup = manifest.get("uploads_backup") or {}
        downloads = [{"label": "Manifeste full", "name": path.name}]
        db_name = Path(str(db_backup.get("file") or "")).name
        uploads_name = Path(str(uploads_backup.get("file") or "")).name
        if db_name:
            downloads.append({"label": "Archive DB", "name": db_name})
        if uploads_name:
            downloads.append({"label": "Archive uploads", "name": uploads_name})

        backups.append(
            {
                "kind": "full",
                "type": "full",
                "type_label": "Complete",
                "file": str(path),
                "name": path.name,
                "size_bytes": int(manifest.get("total_size_bytes", stat.st_size) or stat.st_size),
                "modified_at_utc": str(manifest.get("created_at_utc") or datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z"),
                "manifest_file": str(path),
                "manifest_name": path.name,
                "manifest_present": True,
                "checksum_sha256": "",
                "checksum_short": "",
                "integrity_state": integrity["state"],
                "integrity_label": integrity["label"],
                "integrity_class": integrity["class_name"],
                "integrity_details": integrity["details"],
                "status_label": "Pack complet",
                "downloads": downloads,
                "restore_supported": True,
                "restore_confirm_text": FULL_RESTORE_CONFIRM_TEXT,
                "restore_button_label": "Restaurer complet",
                "db_engine": manifest.get("db_engine", "inconnu"),
                "database": db_backup.get("database", ""),
                "uploads_file_count": int(uploads_backup.get("file_count", 0) or 0),
                "database_file_name": db_name,
                "uploads_file_name": uploads_name,
            }
        )
    return backups


def list_maintenance_backups(*, backup_dir: str | None = None) -> list[dict[str, Any]]:
    backups = [
        *list_database_backups(backup_dir=backup_dir),
        *list_uploads_backups(backup_dir=backup_dir),
        *list_full_backups(backup_dir=backup_dir),
    ]
    return sorted(backups, key=lambda item: str(item.get("modified_at_utc") or ""), reverse=True)


def verify_backup_integrity(backup_file: str) -> dict[str, Any]:
    path = Path(backup_file).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Fichier de sauvegarde introuvable: {path}")

    if path.name.startswith(FULL_BACKUP_PREFIX) and path.name.endswith(".json"):
        manifest = _read_backup_manifest(path)
        if not manifest:
            raise RuntimeError("Manifeste de sauvegarde complete illisible.")
        db_backup = manifest.get("database_backup") or {}
        uploads_backup = manifest.get("uploads_backup") or {}
        backup_dir = path.parent.resolve()
        db_path = _resolve_full_backup_component_path(db_backup.get("file"), backup_dir=backup_dir)
        uploads_path = _resolve_full_backup_component_path(uploads_backup.get("file"), backup_dir=backup_dir)
        db_result = _verify_checksum_against_manifest_data(
            db_path,
            {
                "checksum_sha256": db_backup.get("checksum_sha256"),
                "size_bytes": db_backup.get("size_bytes"),
            },
            manifest_present=True,
        )
        uploads_result = _verify_checksum_against_manifest_data(
            uploads_path,
            {
                "checksum_sha256": uploads_backup.get("checksum_sha256"),
                "size_bytes": uploads_backup.get("size_bytes"),
            },
            manifest_present=True,
        )
        ok = bool(db_result.get("ok")) and bool(uploads_result.get("ok"))
        current_app.logger.info(
            "maintenance.full_backup.verified",
            extra={
                "manifest_file": str(path),
                "success": ok,
            },
        )
        return {
            "ok": ok,
            "state": "valid" if ok else "invalid",
            "label": "✓ Integre" if ok else "✗ Checksum invalide",
            "path": str(path),
            "db_backup": db_result,
            "uploads_backup": uploads_result,
        }

    result = _verify_file_integrity(path)
    current_app.logger.info(
        "maintenance.backup.verified",
        extra={"backup_file": str(path), "success": bool(result.get("ok"))},
    )
    return result


def restore_uploads_backup(
    archive_file: str,
    *,
    yes: bool = False,
    create_safety_backup: bool = True,
    verify_manifest: bool = True,
) -> dict[str, Any]:
    if not yes:
        raise RuntimeError("Restauration refusee: confirmation explicite requise.")

    path = Path(archive_file).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Archive uploads introuvable: {path}")
    if not path.name.endswith(".tar.gz"):
        raise RuntimeError("La restauration uploads attend un fichier .tar.gz.")

    integrity_check: dict[str, Any] | None = None
    if verify_manifest:
        integrity_check = _verify_file_integrity(path)
        if integrity_check.get("state") == "invalid":
            raise RuntimeError("Restauration uploads refusee: checksum invalide.")

    uploads_root = _uploads_root()
    uploads_parent = uploads_root.parent
    uploads_parent.mkdir(parents=True, exist_ok=True)

    temp_root = Path(tempfile.mkdtemp(prefix="dealnova_restore_uploads_", dir=str(uploads_parent)))
    prepared_dir = temp_root / "prepared_uploads"
    rollback_dir = uploads_parent / f"{uploads_root.name}_rollback_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
    pre_restore_backup: dict[str, Any] | None = None
    extracted = {"file_count": 0, "size_bytes": 0}

    try:
        prepared_dir.mkdir(parents=True, exist_ok=True)
        extracted = _extract_validated_uploads_archive(path, prepared_dir)

        if create_safety_backup:
            pre_restore_backup = create_uploads_backup(
                backup_dir=str(_resolve_backup_dir()),
                reason="pre_restore_uploads",
            )

        _replace_directory_atomically(
            live_dir=uploads_root,
            prepared_dir=prepared_dir,
            rollback_dir=rollback_dir,
        )
    except Exception:
        current_app.logger.exception(
            "maintenance.uploads_restore.failed",
            extra={"archive_file": str(path), "uploads_root": str(uploads_root)},
        )
        raise
    finally:
        try:
            if temp_root.exists():
                _remove_tree(temp_root)
        except Exception:
            pass

    if rollback_dir.exists():
        try:
            _remove_tree(rollback_dir)
        except Exception:
            current_app.logger.warning(
                "maintenance.uploads_restore.rollback_cleanup_failed",
                extra={"rollback_dir": str(rollback_dir)},
            )

    current_app.logger.info(
        "maintenance.uploads_restore.completed",
        extra={
            "archive_file": str(path),
            "uploads_root": str(uploads_root),
            "file_count": extracted["file_count"],
        },
    )
    return {
        "restored_file": str(path),
        "uploads_root": str(uploads_root),
        "restored_at_utc": datetime.utcnow().isoformat() + "Z",
        "restored_file_count": extracted["file_count"],
        "restored_size_bytes": extracted["size_bytes"],
        "pre_restore_backup": pre_restore_backup,
        "integrity_check": integrity_check,
    }


def restore_full_backup(
    manifest_file: str,
    *,
    yes: bool = False,
) -> dict[str, Any]:
    if not yes:
        raise RuntimeError("Restauration complete refusee: confirmation explicite requise.")

    path = Path(manifest_file).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Manifeste full introuvable: {path}")
    if not path.name.startswith(FULL_BACKUP_PREFIX) or not path.name.endswith(".json"):
        raise RuntimeError("La restauration complete attend un manifeste dealnova_full_*.json.")

    verification = verify_backup_integrity(str(path))
    if not verification.get("ok"):
        raise RuntimeError("Restauration complete refusee: integrite du backup complet invalide.")

    manifest = _read_backup_manifest(path)
    db_backup = manifest.get("database_backup") or {}
    uploads_backup = manifest.get("uploads_backup") or {}
    try:
        db_backup_path = _resolve_full_backup_component_path(db_backup.get("file"), backup_dir=path.parent.resolve())
        uploads_backup_path = _resolve_full_backup_component_path(uploads_backup.get("file"), backup_dir=path.parent.resolve())
    except Exception as exc:
        raise RuntimeError("Manifeste full invalide: composants hors dossier autorise.") from exc
    if not db_backup_path or not uploads_backup_path:
        raise RuntimeError("Manifeste full incomplet: composants manquants.")

    uploads_restore = restore_uploads_backup(
        str(uploads_backup_path),
        yes=True,
        create_safety_backup=True,
        verify_manifest=False,
    )
    try:
        db_restore = restore_database_backup(
            str(db_backup_path),
            yes=True,
            verify_manifest=False,
        )
    except Exception as exc:
        rollback_result = None
        rollback_error = None
        pre_restore_backup = uploads_restore.get("pre_restore_backup") or {}
        rollback_source = str(pre_restore_backup.get("backup_file") or "").strip()
        if rollback_source:
            try:
                rollback_result = restore_uploads_backup(
                    rollback_source,
                    yes=True,
                    create_safety_backup=False,
                    verify_manifest=False,
                )
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)
        current_app.logger.exception(
            "maintenance.full_restore.failed",
            extra={"manifest_file": str(path)},
        )
        return {
            "success": False,
            "state": "partial",
            "error": str(exc),
            "manifest_file": str(path),
            "verification": verification,
            "uploads_restore": uploads_restore,
            "uploads_rollback": rollback_result,
            "uploads_rollback_error": rollback_error,
        }

    current_app.logger.info(
        "maintenance.full_restore.completed",
        extra={"manifest_file": str(path)},
    )
    return {
        "success": True,
        "state": "complete",
        "manifest_file": str(path),
        "verification": verification,
        "uploads_restore": uploads_restore,
        "db_restore": db_restore,
        "restored_at_utc": datetime.utcnow().isoformat() + "Z",
    }


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

    @app.cli.command("uploads-backup")
    @click.option("--backup-dir", default=None, help="Dossier de stockage des sauvegardes")
    @click.option("--retention-days", default=None, type=int, help="Nombre de jours a conserver")
    def uploads_backup_command(backup_dir, retention_days):
        """Cree une sauvegarde compressee des uploads."""
        result = create_uploads_backup(backup_dir=backup_dir, retention_days=retention_days)
        click.echo(f"Sauvegarde creee: {result['backup_file']}")
        click.echo(f"Manifeste: {result['manifest_file']}")
        click.echo(f"Fichiers archives: {result['file_count']}")
        click.echo(f"Retention: {result['retention_days']} jours")

    @app.cli.command("full-backup")
    @click.option("--backup-dir", default=None, help="Dossier de stockage des sauvegardes")
    @click.option("--db-retention-days", default=None, type=int, help="Retention pour les sauvegardes DB")
    @click.option("--uploads-retention-days", default=None, type=int, help="Retention pour les sauvegardes uploads")
    @click.option("--full-retention-days", default=None, type=int, help="Retention pour les manifestes full")
    @click.option(
        "--keep-latest-only",
        is_flag=True,
        help="Supprime les anciens jeux de sauvegarde complete apres verification du nouveau.",
    )
    def full_backup_command(backup_dir, db_retention_days, uploads_retention_days, full_retention_days, keep_latest_only):
        """Cree une sauvegarde complete DB + uploads + manifeste global."""
        result = create_full_backup(
            backup_dir=backup_dir,
            db_retention_days=db_retention_days,
            uploads_retention_days=uploads_retention_days,
            full_retention_days=full_retention_days,
            keep_latest_only=keep_latest_only or _full_backup_keep_latest_only(),
        )
        if not result.get("success"):
            click.echo("Sauvegarde complete partielle")
            click.echo(f"Backup DB: {result['db_backup']['backup_file']}")
            click.echo(f"Erreur uploads: {result['error']}")
            raise click.ClickException("La sauvegarde complete n'a pas pu se terminer.")
        click.echo(f"Manifeste full: {result['manifest_file']}")
        click.echo(f"Backup DB: {result['db_backup']['backup_file']}")
        click.echo(f"Backup uploads: {result['uploads_backup']['backup_file']}")
        click.echo(f"Taille totale: {human_size(result['size_bytes'])}")
        click.echo(
            "Rotation: "
            + ("dernier backup complet uniquement" if result.get("keep_latest_only") else "historique conserve")
        )
        click.echo(f"Fichiers remplaces: {len(result['removed_old_backups'])}")

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
