from urllib.parse import quote

from flask import current_app

from ..config import Config
from .baba_whatsapp import normalize_whatsapp_number


def support_whatsapp_number() -> str:
    """Retourne le numéro WhatsApp du support / manager normalisé."""
    raw = (
        current_app.config.get("SUPPORT_WHATSAPP_NUMBER")
        or current_app.config.get("ADMIN_PHONE")
        or Config.SUPPORT_WHATSAPP_NUMBER
    )
    return normalize_whatsapp_number(raw)


def raw_shop_contact_phone(shop) -> str:
    """Retourne le numéro brut du vendeur/boutique (avec repli sur User.phone)."""
    if not shop:
        return ""
    fallback_raw = ""
    for attr in ("contact_phone", "whatsapp_phone", "phone"):
        raw = (getattr(shop, attr, None) or "").strip()
        if raw:
            fallback_raw = fallback_raw or raw
            if len(normalize_whatsapp_number(raw)) >= 8:
                return raw
    vendor = getattr(shop, "vendor", None)
    if vendor is not None:
        raw = (getattr(vendor, "phone", None) or "").strip()
        if raw:
            fallback_raw = fallback_raw or raw
            if len(normalize_whatsapp_number(raw)) >= 8:
                return raw
    return fallback_raw


def resolve_shop_whatsapp_number(shop) -> str:
    """Retourne le numéro WhatsApp normalisé du vendeur/boutique, ou '' si indisponible."""
    normalized = normalize_whatsapp_number(raw_shop_contact_phone(shop))
    return normalized if len(normalized) >= 8 else ""


def resolve_order_whatsapp_target(shop) -> tuple[str, bool]:
    """Retourne (numero_normalise, is_vendor_number) avec repli vers le support manager."""
    vendor_phone = resolve_shop_whatsapp_number(shop)
    if vendor_phone:
        return vendor_phone, True
    return support_whatsapp_number(), False


def build_whatsapp_wa_url(phone: str | None, message: str = "") -> str:
    """Construit une URL wa.me normalisée avec repli sur le support manager."""
    normalized = normalize_whatsapp_number(phone) or support_whatsapp_number()
    return f"https://wa.me/{normalized}?text={quote(message or '', safe='')}"


def build_support_whatsapp_url(lines) -> str:
    message = "\n".join(
        str(line).strip()
        for line in (lines or [])
        if str(line or "").strip()
    )
    return f"https://wa.me/{support_whatsapp_number()}?text={quote(message)}"


def safe_support_back_target(raw: str | None, fallback: str) -> str:
    candidate = (raw or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return fallback


def support_user_label(user) -> str:
    if user is None:
        return "Utilisateur"
    for attr in ("business_name", "full_name", "name", "username", "email", "phone"):
        value = getattr(user, attr, None)
        if value and str(value).strip():
            return str(value).strip()
    user_id = getattr(user, "id", None)
    return f"Utilisateur #{user_id}" if user_id is not None else "Utilisateur"


def clean_support_text(value: str | None, *, limit: int = 160) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) > limit:
        normalized = normalized[:limit].rstrip()
    return normalized


def support_message_bullets(value: str | None, *, limit: int = 700) -> list[str]:
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    chunks = []
    total = 0
    for piece in raw.split("\n"):
        cleaned = " ".join(piece.split())
        if not cleaned:
            continue
        if len(cleaned) > 220:
            cleaned = cleaned[:220].rstrip()
        next_total = total + len(cleaned)
        if chunks and next_total > limit:
            break
        total = next_total
        chunks.append(f"- {cleaned.lstrip('- ').strip()}")
    return chunks or ["- "]


def append_support_request(
    lines: list[str],
    *,
    issue_type: str | None = None,
    details: str | None = None,
    expected: str | None = None,
) -> list[str]:
    clean_issue_type = clean_support_text(issue_type, limit=120)
    if clean_issue_type:
        lines.append(f"Sujet : {clean_issue_type}")
    lines.extend(["", "Problème rencontré :"])
    lines.extend(support_message_bullets(details))
    lines.extend(["", "Ce que je souhaitais faire :"])
    lines.extend(support_message_bullets(expected))
    return lines
