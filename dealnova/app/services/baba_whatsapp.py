import os
import re
import threading
from datetime import datetime
from urllib.parse import quote
import requests
from flask import current_app

from .logging_service import logging_service

DEFAULT_WHATSAPP_SEND_URL = "http://127.0.0.1:3002/api/send"
DEFAULT_WHATSAPP_STATUS_URL = "http://127.0.0.1:3002/api/status"
DEFAULT_WHATSAPP_LOGOUT_URL = "http://127.0.0.1:3002/api/logout"
DEFAULT_WHATSAPP_RECONNECT_URL = "http://127.0.0.1:3002/api/reconnect"

_SAFE_QR_DATA_URI_RE = re.compile(
    r"^data:image/(?:png|jpeg|jpg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=\s]+$",
    re.IGNORECASE,
)

STATUS_LABELS = {
    "connected": "Connecté",
    "qr_ready": "En attente de scan",
    "disconnected": "Déconnecté",
}


def sanitize_whatsapp_qr_data_uri(raw_qr: str | None) -> str | None:
    """Valide et nettoie une image QR Code encodée en base64 (data URI)."""
    if not raw_qr or not isinstance(raw_qr, str):
        return None
    candidate = raw_qr.strip()
    if not _SAFE_QR_DATA_URI_RE.match(candidate):
        return None
    return re.sub(r"\s+", "", candidate)


def normalize_whatsapp_number(raw_phone: str | None) -> str:
    """Normalise un numéro de téléphone marocain ou international pour WhatsApp.
    
    Exemples :
    - '0612345678' -> '212612345678'
    - '0712345678' -> '212712345678'
    - '+212 6 12 34 56 78' -> '212612345678'
    - '06-12-34-56-78' -> '212612345678'
    """
    digits = re.sub(r"\D", "", str(raw_phone or ""))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10 and digits[1] in ("6", "7"):
        return "212" + digits[1:]
    if len(digits) == 9 and digits[0] in ("6", "7"):
        return "212" + digits
    return digits


def build_vendor_welcome_message(
    full_name: str,
    shop_name: str,
    phone: str,
    login_url: str,
) -> str:
    """Génère le message officiel de bienvenue Baba Market pour le nouveau vendeur."""
    safe_name = (full_name or "Commerçant").strip()
    safe_shop = (shop_name or "Votre boutique").strip()
    safe_phone = (phone or "").strip()
    safe_url = (login_url or "https://www.babamarket.ma/login").strip()

    return (
        f"🌟 Bienvenue sur Baba Market ! 🌟\n\n"
        f"Bonjour {safe_name},\n"
        f"Félicitations ! Votre boutique \"{safe_shop}\" a été créée et activée avec succès sur la plateforme Baba Market (axe Rabat - Salé - Témara - Kénitra).\n\n"
        f"🔑 Vos identifiants de connexion vendeur :\n"
        f"• Identifiant (Numéro de téléphone) : {safe_phone}\n"
        f"• Mot de passe : Celui que vous avez choisi lors de votre inscription\n\n"
        f"🚀 Accédez dès maintenant à votre espace vendeur pour ajouter vos produits et gérer votre activité :\n"
        f"{safe_url}\n\n"
        f"L'équipe Baba Market vous souhaite d'excellentes ventes !\n"
        f"Pour toute question ou assistance, notre équipe support est à votre disposition au +212 770 010 264."
    )


def get_whatsapp_gateway_status(
    *,
    status_url: str | None = None,
    api_key: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Interroge l'API GET /api/status du micro-service baba-whatsapp (port 3002)."""
    url = (
        status_url
        or ((current_app and current_app.config.get("BABA_WHATSAPP_STATUS_URL")) or os.getenv("BABA_WHATSAPP_STATUS_URL"))
        or DEFAULT_WHATSAPP_STATUS_URL
    ).strip()
    key = (
        api_key
        or ((current_app and current_app.config.get("BABA_WHATSAPP_API_KEY")) or os.getenv("BABA_WHATSAPP_API_KEY", ""))
    ).strip()
    timeout_sec = timeout or int(
        ((current_app and current_app.config.get("BABA_WHATSAPP_TIMEOUT")) or os.getenv("BABA_WHATSAPP_TIMEOUT", "4"))
    )

    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key

    checked_at = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S UTC")

    try:
        resp = requests.get(url, headers=headers, timeout=timeout_sec)
        if resp.status_code == 200:
            data = resp.json() if resp.content else {}
            if not isinstance(data, dict):
                data = {}
            raw_status = str(data.get("status") or "").strip().lower()
            if raw_status not in ("connected", "disconnected", "qr_ready"):
                raw_status = "disconnected"

            raw_phone = str(
                data.get("phone")
                or data.get("number")
                or (data.get("user") or {}).get("id")
                or data.get("connected_number")
                or ""
            ).strip()
            if raw_phone and "@" in raw_phone:
                raw_phone = raw_phone.split("@")[0]
            if ":" in raw_phone:
                raw_phone = raw_phone.split(":")[0]

            safe_qr = sanitize_whatsapp_qr_data_uri(data.get("qr")) if raw_status == "qr_ready" else None

            return {
                "status": raw_status,
                "status_label": STATUS_LABELS.get(raw_status, "Déconnecté"),
                "qr": safe_qr,
                "phone": raw_phone or None,
                "reachable": True,
                "status_code": resp.status_code,
                "status_url": url,
                "checked_at": checked_at,
                "error": None,
            }

        if current_app:
            current_app.logger.warning(
                "baba_whatsapp.status_http_error: status=%s, body=%s",
                resp.status_code,
                resp.text[:200],
            )
        return {
            "status": "disconnected",
            "status_label": STATUS_LABELS["disconnected"],
            "qr": None,
            "phone": None,
            "reachable": False,
            "status_code": resp.status_code,
            "status_url": url,
            "checked_at": checked_at,
            "error": f"Le micro-service a répondu avec le code HTTP {resp.status_code}.",
        }
    except Exception as exc:
        if current_app:
            current_app.logger.warning(
                "baba_whatsapp.status_unreachable: url=%s, error=%s",
                url,
                str(exc),
            )
        return {
            "status": "disconnected",
            "status_label": STATUS_LABELS["disconnected"],
            "qr": None,
            "phone": None,
            "reachable": False,
            "status_code": None,
            "status_url": url,
            "checked_at": checked_at,
            "error": "Impossible de joindre le micro-service WhatsApp local (127.0.0.1:3002).",
        }


def disconnect_whatsapp_gateway(
    *,
    logout_url: str | None = None,
    api_key: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Demande la déconnexion et réinitialisation de la session au micro-service WhatsApp (port 3002)."""
    base_url = (
        logout_url
        or ((current_app and current_app.config.get("BABA_WHATSAPP_LOGOUT_URL")) or os.getenv("BABA_WHATSAPP_LOGOUT_URL"))
        or DEFAULT_WHATSAPP_LOGOUT_URL
    ).strip()
    key = (
        api_key
        or ((current_app and current_app.config.get("BABA_WHATSAPP_API_KEY")) or os.getenv("BABA_WHATSAPP_API_KEY", ""))
    ).strip()
    timeout_sec = timeout or int(
        ((current_app and current_app.config.get("BABA_WHATSAPP_TIMEOUT")) or os.getenv("BABA_WHATSAPP_TIMEOUT", "6"))
    )

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key

    candidate_urls = [base_url]
    if base_url.endswith("/logout"):
        candidate_urls.append(base_url.replace("/logout", "/disconnect"))
        candidate_urls.append(base_url.replace("/logout", "/reset"))
    elif base_url.endswith("/status"):
        candidate_urls.append(base_url.replace("/status", "/logout"))
        candidate_urls.append(base_url.replace("/status", "/disconnect"))
        candidate_urls.append(base_url.replace("/status", "/reset"))

    last_error = None
    for target_url in candidate_urls:
        try:
            resp = requests.post(target_url, headers=headers, json={"action": "logout"}, timeout=timeout_sec)
            if resp.status_code in (200, 201, 202, 204):
                data = resp.json() if resp.content and "application/json" in resp.headers.get("Content-Type", "") else {}
                safe_qr = sanitize_whatsapp_qr_data_uri(data.get("qr")) if isinstance(data, dict) else None
                return {
                    "success": True,
                    "message": "Session WhatsApp déconnectée et réinitialisée avec succès.",
                    "status": data.get("status") if isinstance(data, dict) else "qr_ready",
                    "qr": safe_qr,
                    "target_url": target_url,
                }
            elif resp.status_code == 404:
                continue
            else:
                last_error = f"Le serveur a répondu avec le statut {resp.status_code} sur {target_url}."
        except Exception as exc:
            last_error = str(exc)

    return {
        "success": False,
        "message": f"Impossible de contacter l'endpoint de déconnexion du micro-service ({last_error or 'inaccessible'}).",
        "error": last_error,
    }


def reconnect_whatsapp_gateway(
    *,
    reconnect_url: str | None = None,
    api_key: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Demande la génération d'un nouveau QR Code ou la reconnexion au micro-service."""
    base_url = (
        reconnect_url
        or ((current_app and current_app.config.get("BABA_WHATSAPP_RECONNECT_URL")) or os.getenv("BABA_WHATSAPP_RECONNECT_URL"))
        or DEFAULT_WHATSAPP_RECONNECT_URL
    ).strip()
    key = (
        api_key
        or ((current_app and current_app.config.get("BABA_WHATSAPP_API_KEY")) or os.getenv("BABA_WHATSAPP_API_KEY", ""))
    ).strip()
    timeout_sec = timeout or int(
        ((current_app and current_app.config.get("BABA_WHATSAPP_TIMEOUT")) or os.getenv("BABA_WHATSAPP_TIMEOUT", "6"))
    )

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key

    candidate_urls = [base_url]
    if base_url.endswith("/reconnect"):
        candidate_urls.append(base_url.replace("/reconnect", "/restart"))
        candidate_urls.append(base_url.replace("/reconnect", "/reset"))
        candidate_urls.append(base_url.replace("/reconnect", "/logout"))

    last_error = None
    for target_url in candidate_urls:
        try:
            resp = requests.post(target_url, headers=headers, json={"action": "reconnect"}, timeout=timeout_sec)
            if resp.status_code in (200, 201, 202, 204):
                data = resp.json() if resp.content and "application/json" in resp.headers.get("Content-Type", "") else {}
                safe_qr = sanitize_whatsapp_qr_data_uri(data.get("qr")) if isinstance(data, dict) else None
                return {
                    "success": True,
                    "message": "Demande de nouveau QR Code transmise avec succès.",
                    "status": data.get("status") if isinstance(data, dict) else "qr_ready",
                    "qr": safe_qr,
                }
            elif resp.status_code == 404:
                continue
            else:
                last_error = f"Le serveur a répondu {resp.status_code}."
        except Exception as exc:
            last_error = str(exc)

    return {
        "success": False,
        "message": f"Échec de la demande de nouveau QR Code ({last_error or 'inaccessible'}).",
        "error": last_error,
    }


def send_whatsapp_message(
    phone: str,
    message: str,
    *,
    gateway_url: str | None = None,
    api_key: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Transmet un message à la passerelle baba-whatsapp via HTTP POST.
    
    Gestion d'erreurs tolérante : si la passerelle est indisponible,
    génère un lien direct wa.me et ne bloque jamais le flux applicatif.
    """
    normalized_phone = normalize_whatsapp_number(phone)
    if not normalized_phone:
        return {"sent": False, "reason": "invalid_phone", "phone": phone}

    url = gateway_url or (
        (current_app and current_app.config.get("BABA_WHATSAPP_GATEWAY_URL"))
        or os.getenv("BABA_WHATSAPP_GATEWAY_URL", DEFAULT_WHATSAPP_SEND_URL)
    )
    key = (
        api_key
        or ((current_app and current_app.config.get("BABA_WHATSAPP_API_KEY")) or os.getenv("BABA_WHATSAPP_API_KEY", ""))
    ).strip()
    timeout_sec = timeout or int(
        ((current_app and current_app.config.get("BABA_WHATSAPP_TIMEOUT")) or os.getenv("BABA_WHATSAPP_TIMEOUT", "4"))
    )

    payload = {
        "phone": normalized_phone,
        "number": normalized_phone,
        "message": message,
        "text": message,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key

    wa_me_url = f"https://wa.me/{normalized_phone}?text={quote(message)}"

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout_sec)
        if resp.status_code in (200, 201, 202):
            try:
                logging_service.log_activity(
                    "whatsapp",
                    "vendor_welcome_sent",
                    message=f"Message de bienvenue WhatsApp transmis avec succès à {normalized_phone} via baba-whatsapp",
                    level="INFO",
                )
            except Exception:
                pass
            return {
                "sent": True,
                "method": "baba-whatsapp",
                "phone": normalized_phone,
                "status_code": resp.status_code,
                "wa_me_url": wa_me_url,
            }
        else:
            if current_app:
                current_app.logger.warning(
                    "baba_whatsapp.gateway_http_error: status=%s, body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
            return {
                "sent": False,
                "method": "gateway_http_error",
                "phone": normalized_phone,
                "status_code": resp.status_code,
                "wa_me_url": wa_me_url,
            }
    except Exception as exc:
        if current_app:
            current_app.logger.warning(
                "baba_whatsapp.gateway_unreachable: url=%s, error=%s",
                url,
                str(exc),
            )
        return {
            "sent": False,
            "method": "gateway_unreachable",
            "phone": normalized_phone,
            "error": str(exc),
            "wa_me_url": wa_me_url,
        }


def send_vendor_welcome_whatsapp(
    phone: str,
    full_name: str,
    shop_name: str,
    login_url: str,
    *,
    async_send: bool = False,
    app=None,
) -> dict:
    """Construit et déclenche l'envoi WhatsApp de bienvenue pour un nouveau vendeur."""
    message = build_vendor_welcome_message(full_name, shop_name, phone, login_url)
    if async_send:
        target_app = app or (current_app._get_current_object() if current_app else None)

        def _worker():
            if target_app:
                with target_app.app_context():
                    send_whatsapp_message(phone, message)
            else:
                send_whatsapp_message(phone, message)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        normalized_phone = normalize_whatsapp_number(phone)
        return {
            "sent": True,
            "method": "async_queued",
            "phone": normalized_phone,
            "wa_me_url": f"https://wa.me/{normalized_phone}?text={quote(message)}",
        }

    return send_whatsapp_message(phone, message)


