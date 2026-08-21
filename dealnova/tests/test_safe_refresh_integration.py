from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_safe_refresh_guard_has_input_dirty_and_overlay_protection():
    source = _read("app/static/js/core/safe_refresh.js")

    assert "window.BMSafeRefresh" in source
    assert "function isEditableField(" in source
    assert "function formIsDirty(" in source
    assert "function hasBlockingOverlay(" in source
    assert "function canRefreshNow(" in source
    assert "data-safe-refresh-lock" in source
    assert "EXCLUDED_PATH_PREFIXES" in source
    assert "resume_stale_page" in source


def test_safe_refresh_guard_tracks_user_interaction_and_visibility():
    source = _read("app/static/js/core/safe_refresh.js")

    assert 'document.addEventListener("input", markInteraction, true);' in source
    assert 'document.addEventListener("change", markInteraction, true);' in source
    assert 'document.addEventListener("submit", onSubmit, true);' in source
    assert 'window.addEventListener("focus", onFocus);' in source
    assert 'document.addEventListener("visibilitychange", onVisibilityChange);' in source


def test_safe_refresh_is_loaded_in_public_and_admin_shells():
    public_base = _read("app/templates/base.html")
    admin_base = _read("app/templates/admin/base.html")

    assert "js/core/safe_refresh.js" in public_base
    assert "js/core/safe_refresh.js" in admin_base


def test_service_worker_reload_uses_safe_refresh_guard():
    source = _read("app/static/js/ui_shell.js")

    assert 'window.BMSafeRefresh && typeof window.BMSafeRefresh.request === "function"' in source
    assert 'window.BMSafeRefresh.request("sw_controllerchange"' in source
