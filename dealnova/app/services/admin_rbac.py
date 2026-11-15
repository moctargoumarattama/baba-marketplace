"""Shared role-based access control helpers for admin-facing blueprints."""

from __future__ import annotations

from flask import flash, jsonify, redirect, request, url_for
from flask_login import current_user

ADMIN_ROLE = "admin"
MANAGER_ROLE = "manager"
STAFF_ADMIN_ROLES = frozenset({ADMIN_ROLE, MANAGER_ROLE})

MANAGER_BLOCKED_ADMIN_ENDPOINTS = frozenset(
    {
        "admin.maintenance",
        "admin.maintenance_unlock",
        "admin.maintenance_error_delete",
        "admin.maintenance_errors_purge",
        "admin.maintenance_mode_enable",
        "admin.maintenance_mode_disable",
        "admin.maintenance_mode_schedule",
        "admin.run_maintenance",
        "admin.maintenance_backup_create",
        "admin.maintenance_backup_import",
        "admin.maintenance_backup_verify",
        "admin.maintenance_backup_download",
        "admin.maintenance_backup_restore",
        "admin.maintenance_reset_data",
    }
)


def current_admin_role() -> str:
    """Return the normalized lowercase role of the authenticated user."""
    return (getattr(current_user, "role", "") or "").strip().lower()


def is_full_admin() -> bool:
    """Return True only when the current user has the full `admin` role."""
    return current_admin_role() == ADMIN_ROLE


def is_manager_role() -> bool:
    """Return True when the current user has the operational `manager` role."""
    return current_admin_role() == MANAGER_ROLE


def is_staff_admin() -> bool:
    """Return True for `admin` or `manager` staff roles."""
    return current_admin_role() in STAFF_ADMIN_ROLES


def is_ajax_request() -> bool:
    """Detect XHR/fetch/JSON requests across admin and rental endpoints."""
    return (
        request.headers.get("X-Requested-With") in ("fetch", "XMLHttpRequest")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )


def ensure_staff_admin_access(
    *,
    require_authenticated: bool = False,
    message: str = "Accès réservé aux administrateurs",
    category: str = "danger",
):
    """Return None when authorized, or a login/home redirect response."""
    if require_authenticated and not getattr(current_user, "is_authenticated", False):
        return redirect(url_for("auth.login"))
    if is_staff_admin():
        return None
    flash(message, category)
    return redirect(url_for("shop.home"))


def sensitive_admin_forbidden_response(
    message: str = "Accès réservé aux administrateurs principaux.",
):
    """Return 403 JSON for AJAX or flash + redirect to dashboard for HTML requests."""
    if is_ajax_request():
        return jsonify(success=False, message=message), 403
    flash(message, "danger")
    return redirect(url_for("admin_users.admin_dashboard"))


def restrict_manager_blocked_endpoints(
    blocked_endpoints: frozenset[str] | set[str] = MANAGER_BLOCKED_ADMIN_ENDPOINTS,
):
    """Block `manager` accounts from maintenance-only endpoints."""
    if is_manager_role() and request.endpoint in blocked_endpoints:
        return sensitive_admin_forbidden_response()
    return None
