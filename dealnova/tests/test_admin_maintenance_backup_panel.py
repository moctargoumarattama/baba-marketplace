from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_maintenance_page_shows_database_backup_panel():
    template = _read("app/templates/admin/maintenance.html")

    assert "Sauvegardes" in template
    assert "Derniere sauvegarde" in template
    assert "Historique des sauvegardes" in template
    assert "Sauvegarder la base" in template
    assert "Sauvegarder les uploads" in template
    assert "Sauvegarde complete" in template
    assert "Importer une sauvegarde" in template
    assert 'accept=".sql.gz"' in template
    assert "Verifier" in template
    assert "restore_button_label" in template
    assert "backup.restore_confirm_text" in template
    assert "Tape RESTAURER" in template
    assert "Rotation full" in template


def test_maintenance_route_exposes_backup_context():
    source = _read("app/routes/admin.py")

    assert "def _maintenance_backup_context(" in source
    assert '"backup_panel": _maintenance_backup_context()' in source
    assert "list_maintenance_backups(" in source
    assert "cd {project_dir} && workon {venv_name}" in source
    assert "PYTHONANYWHERE_VENV_NAME" in source
    assert "db-backup --backup-dir" in source
    assert "uploads-backup --backup-dir" in source
    assert "full-backup --backup-dir" in source
    assert "FULL_BACKUP_KEEP_LATEST_ONLY" in source
    assert "status_label" in source


def test_maintenance_backup_actions_are_protected_admin_routes():
    source = _read("app/routes/admin.py")

    assert '@bp.route("/maintenance/backups/create", methods=["POST"])' in source
    assert '@bp.route("/maintenance/backups/import", methods=["POST"])' in source
    assert '@bp.route("/maintenance/backups/verify", methods=["POST"])' in source
    assert '@bp.route("/maintenance/backups/download/<path:filename>", methods=["GET"])' in source
    assert '@bp.route("/maintenance/backups/restore", methods=["POST"])' in source
    assert "maintenance_panel_is_unlocked" in source
    assert "expected_confirm = {" in source
    assert "current_user.check_password(password)" in source
    assert "create_database_backup(" in source
    assert "create_uploads_backup(" in source
    assert "create_full_backup(" in source
    assert "import_database_backup(" in source
    assert "verify_backup_integrity(" in source
    assert "resolve_managed_backup_path(" in source
    assert "restore_database_backup(" in source
    assert "restore_uploads_backup(" in source
    assert "restore_full_backup(" in source


def test_database_backup_import_is_limited_to_mysql_gzip_files():
    source = _read("app/services/maintenance.py")

    assert "def import_database_backup(" in source
    assert ".sql.gz" in source
    assert "secure_name" in source
    assert "imported_at_utc" in source
