from urllib.parse import quote

from flask import current_app


def support_whatsapp_number() -> str:
    raw = (
        current_app.config.get("SUPPORT_WHATSAPP_NUMBER")
        or current_app.config.get("ADMIN_PHONE")
    )
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits


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
        lines.append(f"Type: {clean_issue_type}")
    lines.extend(["", "Probleme constate:"])
    lines.extend(support_message_bullets(details))
    lines.extend(["", "Resultat attendu:"])
    lines.extend(support_message_bullets(expected))
    return lines
