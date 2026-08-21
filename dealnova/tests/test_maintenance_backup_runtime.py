import io
import json
import sys
import tarfile
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Blueprint, Flask
from werkzeug.security import generate_password_hash

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _ensure_namespace(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


_ensure_namespace("dealnova", PACKAGE_ROOT)
_ensure_namespace("dealnova.app", PACKAGE_ROOT / "app")
_ensure_namespace("dealnova.app.models", PACKAGE_ROOT / "app" / "models")
_ensure_namespace("dealnova.app.routes", PACKAGE_ROOT / "app" / "routes")
_ensure_namespace("dealnova.app.services", PACKAGE_ROOT / "app" / "services")

if "dealnova.app.services.image" not in sys.modules:
    image_module = types.ModuleType("dealnova.app.services.image")
    image_module.LARGE_SIZE = 1200
    image_module.THUMB_SIZE = 400
    sys.modules["dealnova.app.services.image"] = image_module

if "dealnova.app.services.rentals" not in sys.modules:
    rentals_module = types.ModuleType("dealnova.app.services.rentals")
    rentals_module.ARCHIVE_RETENTION_DAYS = 30

    def _archive_and_remove_listing(*args, **kwargs):
        return None

    rentals_module.archive_and_remove_listing = _archive_and_remove_listing
    sys.modules["dealnova.app.services.rentals"] = rentals_module

from dealnova.app.extensions import db, login_manager
from dealnova.app.models.user import User
from dealnova.app.routes.admin import MAINTENANCE_PANEL_SESSION_KEY, bp as admin_bp
from dealnova.app.services import maintenance as maintenance_service


def _write_uploads(uploads_root: Path, files: dict[str, str]) -> None:
    for relative_path, content in files.items():
        destination = uploads_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _tar_file_names(archive_path: Path) -> list[str]:
    with tarfile.open(archive_path, "r:gz") as archive:
        return sorted(member.name for member in archive.getmembers() if member.isfile())


def _sha256(path: Path) -> str:
    return maintenance_service._file_sha256(path)


def _make_malicious_tar(archive_path: Path, member_name: str, *, symlink: bool = False, linkname: str = "") -> None:
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo(member_name)
        if symlink:
            info.type = tarfile.SYMTYPE
            info.linkname = linkname
            archive.addfile(info)
            return

        payload = b"owned"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))


@pytest.fixture()
def maintenance_app(tmp_path):
    static_root = tmp_path / "static"
    uploads_root = static_root / "uploads"
    backups_root = tmp_path / "backups"
    db_path = tmp_path / "dealnova_test.sqlite3"

    static_root.mkdir(parents=True, exist_ok=True)
    uploads_root.mkdir(parents=True, exist_ok=True)
    backups_root.mkdir(parents=True, exist_ok=True)

    auth_bp = Blueprint("auth", __name__)
    shop_bp = Blueprint("shop", __name__)
    admin_users_bp = Blueprint("admin_users", __name__, url_prefix="/admin-users")

    @auth_bp.route("/login")
    def login():
        return "login"

    @shop_bp.route("/")
    def home():
        return "home"

    @admin_users_bp.route("/dashboard")
    def admin_dashboard():
        return "admin-dashboard"

    app = Flask(
        "dealnova.app",
        static_folder=str(static_root),
        template_folder=str((Path(__file__).resolve().parents[1] / "app" / "templates")),
    )
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path.as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(uploads_root),
        MAINTENANCE_BACKUP_DIR=str(backups_root),
        DB_BACKUP_RETENTION_DAYS=30,
        UPLOADS_BACKUP_RETENTION_DAYS=14,
        FULL_BACKUP_RETENTION_DAYS=14,
        MAINTENANCE_PANEL_PASSWORD_HASH=generate_password_hash("maintenance-pass"),
    )

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    app.register_blueprint(auth_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(admin_users_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        User.__table__.create(bind=db.engine, checkfirst=True)
        admin = User(username="admin", email="admin@example.test", role="admin")
        admin.set_password("admin-secret")
        manager = User(username="manager", email="manager@example.test", role="manager")
        manager.set_password("manager-secret")
        db.session.add_all([admin, manager])
        db.session.commit()
        admin_id = admin.id
        manager_id = manager.id

    yield {
        "app": app,
        "uploads_root": uploads_root,
        "backups_root": backups_root,
        "db_path": db_path,
        "admin_id": admin_id,
        "manager_id": manager_id,
    }

    with app.app_context():
        db.session.remove()
        User.__table__.drop(bind=db.engine, checkfirst=True)
        db.engine.dispose()


def _login(client, user_id: int, *, unlocked: bool = False) -> None:
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        if unlocked:
            session[MAINTENANCE_PANEL_SESSION_KEY] = (
                datetime.utcnow() + timedelta(minutes=30)
            ).isoformat()


def test_create_uploads_backup_archives_files_and_manifest(maintenance_app):
    app = maintenance_app["app"]
    uploads_root = maintenance_app["uploads_root"]
    _write_uploads(
        uploads_root,
        {
            "products/item.txt": "alpha",
            "rentals/cover.webp": "beta",
            "videos/demo.mp4": "gamma",
        },
    )

    with app.app_context():
        result = maintenance_service.create_uploads_backup()

    archive_path = Path(result["backup_file"])
    manifest = json.loads(Path(result["manifest_file"]).read_text(encoding="utf-8"))

    assert archive_path.exists()
    assert _tar_file_names(archive_path) == [
        "products/item.txt",
        "rentals/cover.webp",
        "videos/demo.mp4",
    ]
    assert manifest["type"] == "uploads"
    assert manifest["archive_file"] == str(archive_path)
    assert manifest["file_count"] == 3
    assert manifest["uploads_source"] == str(uploads_root)
    assert manifest["checksum_sha256"] == _sha256(archive_path)
    assert manifest["size_bytes"] == archive_path.stat().st_size
    assert manifest["retention_days"] == 14


def test_verify_backup_integrity_detects_modified_archive(maintenance_app):
    app = maintenance_app["app"]
    uploads_root = maintenance_app["uploads_root"]
    _write_uploads(uploads_root, {"one.txt": "v1"})

    with app.app_context():
        result = maintenance_service.create_uploads_backup()

    archive_path = Path(result["backup_file"])
    with archive_path.open("r+b") as handle:
        handle.seek(-16, 2)
        original = handle.read(1)
        handle.seek(-16, 2)
        handle.write(bytes([original[0] ^ 0xFF]))

    with app.app_context():
        verification = maintenance_service.verify_backup_integrity(str(archive_path))

    assert verification["ok"] is False
    assert verification["state"] == "invalid"


@pytest.mark.parametrize(
    ("member_name", "symlink", "linkname", "message"),
    [
        ("../escape.txt", False, "", "sortie du dossier"),
        ("/absolute.txt", False, "", "chemins absolus"),
        ("bad-link", True, "../../outside", "liens symboliques"),
    ],
)
def test_restore_uploads_backup_rejects_malicious_archives(
    maintenance_app,
    member_name: str,
    symlink: bool,
    linkname: str,
    message: str,
):
    app = maintenance_app["app"]
    uploads_root = maintenance_app["uploads_root"]
    _write_uploads(uploads_root, {"safe.txt": "safe"})
    archive_path = maintenance_app["backups_root"] / "dealnova_uploads_malicious.tar.gz"
    _make_malicious_tar(archive_path, member_name, symlink=symlink, linkname=linkname)

    with app.app_context():
        with pytest.raises(RuntimeError, match=message):
            maintenance_service.restore_uploads_backup(
                str(archive_path),
                yes=True,
                create_safety_backup=False,
                verify_manifest=False,
            )

    assert (uploads_root / "safe.txt").read_text(encoding="utf-8") == "safe"


def test_restore_uploads_backup_replaces_live_uploads_and_creates_safety_backup(maintenance_app):
    app = maintenance_app["app"]
    uploads_root = maintenance_app["uploads_root"]
    _write_uploads(uploads_root, {"catalog/a.txt": "before", "catalog/b.txt": "state"})

    with app.app_context():
        backup = maintenance_service.create_uploads_backup()

    _write_uploads(uploads_root, {"catalog/a.txt": "after", "catalog/c.txt": "current"})

    with app.app_context():
        restored = maintenance_service.restore_uploads_backup(str(backup["backup_file"]), yes=True)

    assert (uploads_root / "catalog" / "a.txt").read_text(encoding="utf-8") == "before"
    assert (uploads_root / "catalog" / "b.txt").read_text(encoding="utf-8") == "state"
    assert not (uploads_root / "catalog" / "c.txt").exists()
    assert restored["pre_restore_backup"]
    assert Path(restored["pre_restore_backup"]["backup_file"]).exists()


def test_restore_uploads_backup_rolls_back_if_directory_swap_fails(maintenance_app, monkeypatch):
    app = maintenance_app["app"]
    uploads_root = maintenance_app["uploads_root"]
    _write_uploads(uploads_root, {"catalog/original.txt": "backup-source"})

    with app.app_context():
        backup = maintenance_service.create_uploads_backup()

    _write_uploads(uploads_root, {"catalog/original.txt": "live-now"})
    original_rename = maintenance_service._rename_path
    state = {"calls": 0}

    def flaky_rename(source: Path, target: Path) -> None:
        state["calls"] += 1
        if state["calls"] == 2:
            raise OSError("simulated swap failure")
        original_rename(source, target)

    monkeypatch.setattr(maintenance_service, "_rename_path", flaky_rename)

    with app.app_context():
        with pytest.raises(OSError, match="simulated swap failure"):
            maintenance_service.restore_uploads_backup(
                str(backup["backup_file"]),
                yes=True,
                create_safety_backup=False,
                verify_manifest=False,
            )

    assert (uploads_root / "catalog" / "original.txt").read_text(encoding="utf-8") == "live-now"


def test_create_full_backup_links_database_uploads_and_manifest(maintenance_app):
    app = maintenance_app["app"]
    uploads_root = maintenance_app["uploads_root"]
    _write_uploads(uploads_root, {"media/file.txt": "payload"})

    with app.app_context():
        result = maintenance_service.create_full_backup()

    assert result["success"] is True
    assert result["state"] == "complete"
    assert Path(result["manifest_file"]).exists()
    assert Path(result["db_backup"]["backup_file"]).exists()
    assert Path(result["uploads_backup"]["backup_file"]).exists()

    manifest = json.loads(Path(result["manifest_file"]).read_text(encoding="utf-8"))
    assert manifest["type"] == "full"
    assert manifest["db_engine"] == "sqlite"
    assert manifest["database_backup"]["checksum_sha256"] == result["db_backup"]["checksum_sha256"]
    assert manifest["uploads_backup"]["checksum_sha256"] == result["uploads_backup"]["checksum_sha256"]
    assert manifest["uploads_backup"]["file_count"] == 1

    with app.app_context():
        kinds = {item["kind"] for item in maintenance_service.list_maintenance_backups()}

    assert {"database", "uploads", "full"} <= kinds


def test_legacy_database_backups_without_checksum_are_still_listed(maintenance_app):
    app = maintenance_app["app"]
    backups_root = maintenance_app["backups_root"]
    backup_file = backups_root / "dealnova_db_sqlite_20240101_010101.sqlite3"
    backup_file.write_text("legacy", encoding="utf-8")
    legacy_manifest = backups_root / "dealnova_db_sqlite_20240101_010101.sqlite3.json"
    legacy_manifest.write_text(
        json.dumps(
            {
                "created_at_utc": "2024-01-01T01:01:01Z",
                "db_engine": "sqlite",
                "database": "legacy.sqlite3",
            }
        ),
        encoding="utf-8",
    )

    with app.app_context():
        backups = maintenance_service.list_database_backups()

    assert any(item["name"] == backup_file.name for item in backups)
    legacy_item = next(item for item in backups if item["name"] == backup_file.name)
    assert legacy_item["integrity_state"] == "missing_checksum"


def test_admin_backup_routes_require_auth_admin_and_unlock(maintenance_app):
    app = maintenance_app["app"]
    client = app.test_client()

    response = client.post(
        "/admin/maintenance/backups/create",
        data={"days": "6", "backup_type": "database"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    _login(client, maintenance_app["manager_id"], unlocked=True)
    response = client.post(
        "/admin/maintenance/backups/create",
        data={"days": "6", "backup_type": "database"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/admin-users/dashboard" in response.headers["Location"]

    client = app.test_client()
    _login(client, maintenance_app["admin_id"], unlocked=False)
    response = client.post(
        "/admin/maintenance/backups/create",
        data={"days": "6", "backup_type": "database"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/admin/maintenance" in response.headers["Location"]


def test_admin_backup_download_allows_valid_file_and_refuses_traversal(maintenance_app):
    app = maintenance_app["app"]
    uploads_root = maintenance_app["uploads_root"]
    _write_uploads(uploads_root, {"public/file.txt": "download-me"})

    with app.app_context():
        backup = maintenance_service.create_uploads_backup()

    archive_name = Path(backup["backup_file"]).name
    client = app.test_client()
    _login(client, maintenance_app["admin_id"], unlocked=True)

    ok_response = client.get(f"/admin/maintenance/backups/download/{archive_name}", follow_redirects=False)
    assert ok_response.status_code == 200
    assert archive_name in ok_response.headers["Content-Disposition"]

    bad_response = client.get(
        "/admin/maintenance/backups/download/..%2F..%2Fetc%2Fpasswd",
        follow_redirects=False,
    )
    assert bad_response.status_code == 404
