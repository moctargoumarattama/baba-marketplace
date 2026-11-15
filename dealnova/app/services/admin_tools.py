"""Shared helpers for admin operations: CSV exports, badges, charts, and audit summaries."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta
from typing import Iterable

from flask import Response
from sqlalchemy import func, or_

from ..extensions import db
from ..models.booking import Booking
from ..models.maintenance import ErrorLog
from ..models.platform_settings import PlatformSettings
from ..models.product_contact_lead import ProductContactLead
from ..models.promo import Promo
from ..models.user import User
from ..models.vendor_change_request import VendorChangeRequest
from ..services.cache import cache

_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_AUDIT_ACTION_META: dict[str, tuple[str, str, str]] = {
    "deletion_snapshot": ("Suppression", "danger", "Archive de suppression"),
    "block_contact": ("Blocage fraude", "danger", "Contact bloque (antispam)"),
    "unblock_contact": ("Deblocage fraude", "success", "Contact debloque"),
    "vendor_change_request_approve": ("Validation boutique", "success", "Demande vendeur approuvee"),
    "vendor_change_request_approved": ("Validation boutique", "success", "Demande vendeur approuvee"),
    "vendor_change_request_reject": ("Refus boutique", "warning", "Demande vendeur refusee"),
    "vendor_change_request_rejected": ("Refus boutique", "warning", "Demande vendeur refusee"),
    "vendor_change_request_create": ("Demande vendeur", "info", "Demande de modification envoyee"),
    "mark_subscription_paid": ("Abonnement paye", "success", "Paiement abonnement enregistre"),
    "subscription_paid": ("Abonnement paye", "success", "Paiement abonnement enregistre"),
    "subscription_free_vendor": ("Gratuite vendeur", "info", "Gratuite accordee au vendeur"),
    "subscription_block_vendor": ("Blocage vendeur", "danger", "Vendeur bloque (abonnement)"),
    "subscription_unblock_vendor": ("Deblocage vendeur", "success", "Vendeur reactive"),
    "create_user": ("Creation compte", "info", "Nouvel utilisateur cree"),
    "update_user": ("Edition compte", "info", "Compte utilisateur mis a jour"),
    "reset_password": ("Mot de passe", "warning", "Mot de passe reinitialise"),
    "toggle_user_active": ("Statut compte", "warning", "Activation du compte modifiee"),
    "delete_user": ("Suppression compte", "danger", "Compte utilisateur supprime"),
    "update_shop": ("Edition boutique", "info", "Boutique mise a jour"),
    "toggle_shop": ("Statut boutique", "warning", "Visibilite boutique modifiee"),
    "delete_shop": ("Suppression boutique", "danger", "Boutique supprimee"),
    "pricing_settings": ("Tarifs location", "info", "Parametres commissions mis a jour"),
    "booking_status_update": ("Reservation", "info", "Statut de reservation modifie"),
    "login": ("Connexion", "success", "Connexion reussie"),
    "logout": ("Deconnexion", "neutral", "Session fermee"),
    "create_product": ("Nouveau produit", "info", "Offre ajoutee au catalogue"),
    "update_product": ("Edition produit", "info", "Offre catalogue modifiee"),
}

_AUDIT_ENTITY_LABELS: dict[str, str] = {
    "user": "Utilisateur",
    "shop": "Boutique",
    "product": "Produit",
    "booking": "Reservation",
    "blocked_contact": "Contact fraude",
    "vendor_change_request": "Demande modification",
    "platform_settings": "Parametres plateforme",
    "category": "Categorie",
    "rental": "Location",
}


def digits_only(value: str | None) -> str:
    """Extract ASCII digits from a phone-like string."""
    return re.sub(r"\D", "", str(value or ""))


def _sanitize_csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    text = str(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return f"'{text}"
    return text


def csv_download_response(
    filename: str,
    headers: Iterable[str],
    rows: Iterable[Iterable],
) -> Response:
    """Build a UTF-8 BOM CSV download response safe against spreadsheet formula injection."""
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(filename or "export.csv")).strip("._") or "export.csv"
    if not safe_name.lower().endswith(".csv"):
        safe_name = f"{safe_name}.csv"

    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([_sanitize_csv_cell(h) for h in headers])
    for row in rows:
        writer.writerow([_sanitize_csv_cell(cell) for cell in row])

    response = Response(buffer.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    return response


def describe_audit_log(log) -> dict[str, str]:
    """Convert a raw AuditLog record into a human-readable summary dict."""
    action = (getattr(log, "action", None) or "").strip()
    entity_type = (getattr(log, "entity_type", None) or "").strip()
    entity_id = getattr(log, "entity_id", None)
    changes = getattr(log, "changes", None)
    payload = changes if isinstance(changes, dict) else {}

    actor = "Systeme"
    user_obj = getattr(log, "user", None)
    if user_obj is not None and getattr(user_obj, "username", None):
        actor = user_obj.username
    elif getattr(log, "user_id", None):
        actor = f"Compte #{log.user_id}"

    badge_label, badge_tone, base_summary = _AUDIT_ACTION_META.get(
        action,
        (action or "Action", "neutral", action.replace("_", " ").capitalize() if action else "Evenement enregistre"),
    )

    detail_parts: list[str] = []
    entity_label = _AUDIT_ENTITY_LABELS.get(entity_type, entity_type)
    if entity_label and entity_id:
        detail_parts.append(f"{entity_label} #{entity_id}")

    name_hint = (
        payload.get("shop_name")
        or payload.get("name")
        or payload.get("entity_name")
        or payload.get("label")
        or payload.get("username")
    )
    if name_hint:
        detail_parts.append(f"« {name_hint} »")
    if payload.get("kind") and payload.get("value"):
        detail_parts.append(f"{payload['kind']}: {payload['value']}")
    if payload.get("reason"):
        detail_parts.append(f"Motif: {str(payload['reason'])[:90]}")
    elif payload.get("status"):
        detail_parts.append(f"Statut: {payload['status']}")
    elif payload.get("months"):
        detail_parts.append(f"+{payload['months']} mois")
    elif payload.get("new_value"):
        detail_parts.append(f"Nouvelle valeur: {payload['new_value']}")

    summary = base_summary
    if detail_parts:
        summary = f"{base_summary} — {' · '.join(detail_parts)}"

    return {
        "actor": actor,
        "badge_label": badge_label,
        "badge_tone": badge_tone,
        "summary": summary,
    }


def get_admin_sidebar_badges(now: datetime | None = None) -> dict[str, int]:
    """Return lightweight pending-task counts for the admin sidebar (cached briefly)."""
    try:
        cached = cache.get("admin:sidebar:badges:v1")
        if isinstance(cached, dict):
            return cached
    except Exception:
        cached = None

    ref_now = now or datetime.utcnow()
    soon_cutoff = ref_now + timedelta(days=7)

    counts = {
        "pending_promos": 0,
        "pending_vendor_changes": 0,
        "pending_bookings": 0,
        "expiring_subs": 0,
    }

    try:
        counts["pending_promos"] = int(
            db.session.query(func.count(Promo.id))
            .filter(Promo.status == Promo.STATUS_PENDING)
            .scalar()
            or 0
        )
        counts["pending_vendor_changes"] = int(
            db.session.query(func.count(VendorChangeRequest.id))
            .filter(VendorChangeRequest.status == VendorChangeRequest.STATUS_PENDING)
            .scalar()
            or 0
        )
        counts["pending_bookings"] = int(
            db.session.query(func.count(Booking.id))
            .filter(Booking.status == "pending")
            .scalar()
            or 0
        )

        settings = PlatformSettings.query.first()
        free_until = getattr(settings, "vendor_free_until", None)
        if not (free_until and free_until >= ref_now):
            counts["expiring_subs"] = int(
                db.session.query(func.count(User.id))
                .filter(
                    User.role == "vendor",
                    User.is_active == True,
                    User.subscription_expires_at.isnot(None),
                    User.subscription_expires_at <= soon_cutoff,
                    or_(User.subscription_free_until.is_(None), User.subscription_free_until < ref_now),
                )
                .scalar()
                or 0
            )
    except Exception:
        return counts

    try:
        cache.set("admin:sidebar:badges:v1", counts, timeout=20)
    except Exception:
        pass
    return counts


def invalidate_admin_sidebar_badges() -> None:
    """Clear the cached sidebar badges after a moderated action."""
    try:
        cache.delete("admin:sidebar:badges:v1")
    except Exception:
        pass


def get_admin_recent_error_count(hours: int = 24, now: datetime | None = None) -> int:
    """Count ErrorLog entries in the last `hours` hours (best-effort)."""
    since = (now or datetime.utcnow()) - timedelta(hours=max(1, int(hours)))
    try:
        return int(
            db.session.query(func.count(ErrorLog.id))
            .filter(ErrorLog.created_at >= since)
            .scalar()
            or 0
        )
    except Exception:
        return 0


def build_daily_activity_series(days: int = 7, now: datetime | None = None) -> list[dict]:
    """Return 7-day daily counts of WhatsApp product leads and service bookings."""
    window_days = max(1, min(30, int(days or 7)))
    today = (now or datetime.utcnow()).date()
    start_day = today - timedelta(days=window_days - 1)
    start_dt = datetime.combine(start_day, datetime.min.time())

    leads_by_day: dict[str, int] = {}
    bookings_by_day: dict[str, int] = {}

    try:
        lead_rows = (
            db.session.query(
                func.date(ProductContactLead.created_at).label("day"),
                func.count(ProductContactLead.id).label("cnt"),
            )
            .filter(
                ProductContactLead.source == "product_whatsapp",
                ProductContactLead.created_at >= start_dt,
            )
            .group_by(func.date(ProductContactLead.created_at))
            .all()
        )
        for day_val, cnt in lead_rows:
            if day_val is not None:
                leads_by_day[str(day_val)[:10]] = int(cnt or 0)

        booking_rows = (
            db.session.query(
                func.date(Booking.created_at).label("day"),
                func.count(Booking.id).label("cnt"),
            )
            .filter(Booking.created_at >= start_dt)
            .group_by(func.date(Booking.created_at))
            .all()
        )
        for day_val, cnt in booking_rows:
            if day_val is not None:
                bookings_by_day[str(day_val)[:10]] = int(cnt or 0)
    except Exception:
        pass

    series: list[dict] = []
    for offset in range(window_days):
        day_obj = start_day + timedelta(days=offset)
        iso = day_obj.isoformat()
        series.append(
            {
                "iso": iso,
                "label": day_obj.strftime("%d/%m"),
                "leads": leads_by_day.get(iso, 0),
                "bookings": bookings_by_day.get(iso, 0),
            }
        )
    return series
