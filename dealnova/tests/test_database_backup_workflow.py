from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_database_backup_commands_are_available():
    source = _read("app/services/maintenance.py")

    assert '@app.cli.command("db-backup")' in source
    assert '@app.cli.command("uploads-backup")' in source
    assert '@app.cli.command("full-backup")' in source
    assert '@app.cli.command("db-backups")' in source
    assert '@app.cli.command("db-restore")' in source
    assert "--keep-latest-only" in source
    assert "create_database_backup(" in source
    assert "create_uploads_backup(" in source
    assert "create_full_backup(" in source
    assert "list_database_backups(" in source
    assert "restore_database_backup(" in source


def test_mysql_backup_uses_safe_dump_options_without_password_argument():
    source = _read("app/services/maintenance.py")

    assert '"mysqldump"' in source
    assert "--single-transaction" in source
    assert "--quick" in source
    assert "--routines" in source
    assert "--triggers" in source
    assert "--events" in source
    assert "--password=" not in source
    assert "[client]" in source
    assert "defaults-extra-file" in source


def test_backup_directory_is_not_allowed_inside_public_static_uploads():
    source = _read("app/services/maintenance.py")

    assert "def _guard_backup_dir_not_public(" in source
    assert "static_folder" in source
    assert "UPLOAD_FOLDER" in source
    assert "ne doit pas etre dans un dossier public" in source


def test_backup_retention_is_configurable():
    config = _read("app/config.py")
    source = _read("app/services/maintenance.py")

    assert "DB_BACKUP_RETENTION_DAYS" in config
    assert "UPLOADS_BACKUP_RETENTION_DAYS" in config
    assert "FULL_BACKUP_RETENTION_DAYS" in config
    assert "FULL_BACKUP_KEEP_LATEST_ONLY" in config
    assert "DB_USER" in config
    assert "DB_PASSWORD" in config
    assert "DB_HOST" in config
    assert "DB_NAME" in config
    assert not (ROOT / "app" / "confprod.py").exists()
    assert "prune_database_backups(" in source
    assert "prune_uploads_backups(" in source
    assert "prune_full_backups(" in source
    assert "retention_days" in source
    assert "_prune_full_backup_sets_except_timestamp(" in source
