from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urljoin

from flask import current_app, url_for


def _mask_email(email: str | None) -> str:
    value = (email or "").strip().lower()
    if not value or "@" not in value:
        return "-"
    local, domain = value.split("@", 1)
    visible = local[:1] if local else "*"
    return f"{visible}***@{domain}"


def build_public_url(endpoint: str, **values) -> str:
    relative_url = url_for(endpoint, _external=False, **values)
    configured_base = (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured_base:
        return urljoin(f"{configured_base}/", relative_url.lstrip("/"))
    return url_for(endpoint, _external=True, **values)


def _smtp_config() -> dict[str, object]:
    return {
        "server": (current_app.config.get("MAIL_SERVER") or "").strip(),
        "port": int(current_app.config.get("MAIL_PORT") or 0),
        "username": (current_app.config.get("MAIL_USERNAME") or "").strip(),
        "password": current_app.config.get("MAIL_PASSWORD") or "",
        "sender": (current_app.config.get("MAIL_DEFAULT_SENDER") or "").strip(),
        "use_tls": bool(current_app.config.get("MAIL_USE_TLS", True)),
        "use_ssl": bool(current_app.config.get("MAIL_USE_SSL", False)),
        "timeout": max(1, int(current_app.config.get("MAIL_TIMEOUT") or 20)),
    }


def smtp_is_configured() -> bool:
    config = _smtp_config()
    return bool(config["server"] and config["port"] and config["sender"])


def send_account_created_email(
    *,
    recipient_email: str,
    password_plaintext: str,
    login_url: str | None = None,
    account_email: str | None = None,
    site_name: str | None = None,
) -> dict[str, object]:
    safe_recipient = (recipient_email or "").strip().lower()
    if not safe_recipient:
        return {"sent": False, "reason": "missing_recipient"}

    config = _smtp_config()
    if not smtp_is_configured():
        current_app.logger.warning(
            "email.account_created.skipped recipient=%s reason=smtp_not_configured",
            _mask_email(safe_recipient),
        )
        return {"sent": False, "reason": "smtp_not_configured"}

    login_url = (login_url or "").strip() or build_public_url("auth.login")
    site_name = (site_name or current_app.config.get("SITE_NAME") or "Baba Market").strip()
    account_email = (account_email or safe_recipient).strip()

    message = EmailMessage()
    message["Subject"] = f"Votre compte {site_name} est pret"
    message["From"] = str(config["sender"])
    message["To"] = safe_recipient
    message.set_content(
        "\n".join(
            [
                f"Bonjour et bienvenue sur {site_name},",
                "",
                "Votre compte est actif immediatement.",
                f"Adresse e-mail du compte : {account_email}",
                f"Mot de passe choisi : {password_plaintext}",
                f"Connexion : {login_url}",
                "",
                "Conservez cet e-mail dans un endroit sur.",
            ]
        )
    )

    ssl_context = ssl.create_default_context()

    try:
        if config["use_ssl"]:
            smtp_client = smtplib.SMTP_SSL(
                str(config["server"]),
                int(config["port"]),
                timeout=int(config["timeout"]),
                context=ssl_context,
            )
        else:
            smtp_client = smtplib.SMTP(
                str(config["server"]),
                int(config["port"]),
                timeout=int(config["timeout"]),
            )

        with smtp_client as client:
            if config["use_tls"] and not config["use_ssl"]:
                client.starttls(context=ssl_context)
            if config["username"]:
                client.login(str(config["username"]), str(config["password"]))
            client.send_message(message)
    except Exception:
        current_app.logger.exception(
            "email.account_created.failed recipient=%s",
            _mask_email(safe_recipient),
        )
        return {"sent": False, "reason": "smtp_error"}

    current_app.logger.info(
        "email.account_created.sent recipient=%s",
        _mask_email(safe_recipient),
    )
    return {"sent": True, "reason": "sent"}
