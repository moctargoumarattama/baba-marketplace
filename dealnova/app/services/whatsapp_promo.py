"""Promotion WhatsApp quotidienne : Statuts 24h, Groupes WhatsApp & Messages Opt-in.

Fonctionnalités :
- Interrupteurs granulaires : Global (Kill-Switch), Statuts, Groupes, Messages Privés.
- Sélection automatique de produits en stock (priorité promotions, rotation anti-répétition).
- Rédaction commerciale intelligente via Google Gemini (avec repli local).
- Gestion des Groupes WhatsApp (liens d'invitation https://chat.whatsapp.com/... ou JID @g.us).
- Gestion des contacts opt-in avec désinscription automatique au mot-clé STOP.
- Anti-ban complet : simulation de frappe, délais aléatoires (30–90 s), plafond journalier.
- Transparence totale : prévisualisation en direct du message généré + journal des logs récents.

Stockage dans `RuntimeState` (sans migration de base de données).
"""
from __future__ import annotations

import json
import random
import re
import time
from time import sleep
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from flask import current_app
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models.product import Product
from ..models.shop import Shop
from .baba_whatsapp import get_whatsapp_gateway_status, normalize_whatsapp_number
from .db_session import safe_session_rollback
from .pricing import get_active_promos_for_products, prix_final
from .shared_state import get_json_state, locked_json_states, mutate_json_states

SETTINGS_KEY = "whatsapp_promo_settings"
LOG_KEY = "whatsapp_promo_log"

HARD_MAX_MESSAGES_PER_DAY = 50
MAX_STATUS_PRODUCTS = 5
MIN_DELAY_FLOOR = 20
MAX_DELAY_CEILING = 300
MAX_CONSECUTIVE_FAILURES = 3
STATUS_DELAY_RANGE = (15, 45)
MAX_RUNS_KEPT = 20
MAX_RECENT_LOGS_KEPT = 100
OPT_OUT_FOOTER = "Répondez STOP pour ne plus recevoir nos offres."

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "dry_run": True,
    "status_enabled": True,
    "groups_enabled": True,
    "direct_messages_enabled": False,
    "admin_phone": "",
    "schedule_time": "10:30",
    "pinned_product_ids": [],
    "groups": [],
    "recipients": [],
    "status_products": 4,
    "daily_message_limit": 20,
    "min_delay": 30,
    "max_delay": 90,
    "cooldown_days": 7,
}

_URL_RE = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(?:ma|com|net|org)\b\S*)", re.IGNORECASE)
_UNSAFE_CHARS_RE = re.compile(r"[<>`]")


# ---------------------------------------------------------------------------
# Nettoyage et normalisation des réglages
# ---------------------------------------------------------------------------
def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _clean_recipients(raw: Any) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        phone = normalize_whatsapp_number(entry.get("phone"))
        if not phone or not 8 <= len(phone) <= 15 or phone in seen:
            continue
        seen.add(phone)
        cleaned.append({
            "phone": phone,
            "label": str(entry.get("label") or "").strip()[:40],
            "opted_out": bool(entry.get("opted_out")),
            "invalid": bool(entry.get("invalid")),
            "added_at": str(entry.get("added_at") or "")[:32],
        })
    return cleaned


def _clean_groups(raw: Any) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        target = str(entry.get("target") or "").strip()
        if not target or target in seen:
            continue
        seen.add(target)
        cleaned.append({
            "target": target,
            "label": str(entry.get("label") or "").strip()[:50],
            "added_at": str(entry.get("added_at") or "")[:32],
        })
    return cleaned


def normalize_settings(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    min_delay = _clamp_int(raw.get("min_delay"), DEFAULT_SETTINGS["min_delay"], MIN_DELAY_FLOOR, MAX_DELAY_CEILING)
    max_delay = _clamp_int(raw.get("max_delay"), DEFAULT_SETTINGS["max_delay"], MIN_DELAY_FLOOR, MAX_DELAY_CEILING)
    return {
        "enabled": bool(raw.get("enabled", DEFAULT_SETTINGS["enabled"])),
        "dry_run": bool(raw.get("dry_run", DEFAULT_SETTINGS["dry_run"])),
        "status_enabled": bool(raw.get("status_enabled", DEFAULT_SETTINGS["status_enabled"])),
        "groups_enabled": bool(raw.get("groups_enabled", DEFAULT_SETTINGS["groups_enabled"])),
        "direct_messages_enabled": bool(raw.get("direct_messages_enabled", DEFAULT_SETTINGS["direct_messages_enabled"])),
        "admin_phone": normalize_whatsapp_number(raw.get("admin_phone")),
        "schedule_time": str(raw.get("schedule_time") or "10:30").strip() if re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", str(raw.get("schedule_time") or "").strip()) else "10:30",
        "pinned_product_ids": [int(x) for x in (raw.get("pinned_product_ids") or []) if str(x).isdigit()][:10],
        "groups": _clean_groups(raw.get("groups")),
        "recipients": _clean_recipients(raw.get("recipients")),
        "status_products": _clamp_int(raw.get("status_products"), DEFAULT_SETTINGS["status_products"], 1, MAX_STATUS_PRODUCTS),
        "daily_message_limit": _clamp_int(raw.get("daily_message_limit"), DEFAULT_SETTINGS["daily_message_limit"], 0, HARD_MAX_MESSAGES_PER_DAY),
        "min_delay": min(min_delay, max_delay),
        "max_delay": max(min_delay, max_delay),
        "cooldown_days": _clamp_int(raw.get("cooldown_days"), DEFAULT_SETTINGS["cooldown_days"], 0, 60),
    }


def get_settings() -> dict[str, Any]:
    try:
        return normalize_settings(get_json_state(SETTINGS_KEY, dict))
    except Exception:
        safe_session_rollback()
        return normalize_settings({})


def _persist_json_state(key: str, data: Any) -> None:
    """Sauvegarde directe et non-bloquante dans RuntimeState (sans FOR UPDATE pour éviter les deadlocks MySQL)."""
    try:
        from ..models.runtime_state import RuntimeState
        row = RuntimeState.query.filter_by(state_key=key).first()
        now = datetime.utcnow()
        val_str = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
        if row is None:
            row = RuntimeState(state_key=key, created_at=now, updated_at=now, value_json=val_str)
            db.session.add(row)
        else:
            row.value_json = val_str
            row.updated_at = now
        db.session.commit()
    except Exception as exc:
        safe_session_rollback()
        current_app.logger.warning("whatsapp_promo.persist_failed key=%s: %s", key, exc)


def save_settings(values: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_settings(values)
    _persist_json_state(SETTINGS_KEY, normalized)
    return normalized


# ---------------------------------------------------------------------------
# Parseurs de listes textes (Groupes & Contacts)
# ---------------------------------------------------------------------------
def parse_recipients_text(text: str, existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Une ligne par contact : `numéro` ou `numéro, prénom`. Conserve les statuts STOP."""
    previous = {item["phone"]: item for item in _clean_recipients(existing or [])}
    now = datetime.utcnow().isoformat(timespec="seconds")
    parsed: list[dict[str, Any]] = []
    for line in str(text or "").splitlines()[:500]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        phone_part, _, label = line.partition(",")
        phone = normalize_whatsapp_number(phone_part)
        if not phone:
            continue
        old = previous.get(phone, {})
        parsed.append({
            "phone": phone,
            "label": label.strip()[:40],
            "opted_out": bool(old.get("opted_out")),
            "invalid": bool(old.get("invalid")),
            "added_at": old.get("added_at") or now,
        })
    return _clean_recipients(parsed)


def recipients_to_text(recipients: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{item['phone']}, {item['label']}" if item.get("label") else item["phone"]
        for item in recipients
    )


def parse_groups_text(text: str, existing: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Une ligne par groupe : `lien_ou_jid` ou `lien_ou_jid, nom du groupe`."""
    previous = {item["target"]: item for item in _clean_groups(existing or [])}
    now = datetime.utcnow().isoformat(timespec="seconds")
    parsed: list[dict[str, Any]] = []
    for line in str(text or "").splitlines()[:100]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        target_part, _, label = line.partition(",")
        target = target_part.strip()
        if not target:
            continue
        old = previous.get(target, {})
        parsed.append({
            "target": target,
            "label": label.strip()[:50] or old.get("label", ""),
            "added_at": old.get("added_at") or now,
        })
    return _clean_groups(parsed)


def groups_to_text(groups: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{item['target']}, {item['label']}" if item.get("label") else item["target"]
        for item in groups
    )


def get_log() -> dict[str, Any]:
    try:
        log = get_json_state(LOG_KEY, dict)
    except Exception:
        safe_session_rollback()
        log = {}
    return log if isinstance(log, dict) else {}


def _mark_recipient(phone: str, field: str) -> None:
    def _apply(payloads: dict[str, Any]) -> None:
        settings = normalize_settings(payloads.get(SETTINGS_KEY))
        for item in settings["recipients"]:
            if item["phone"] == phone:
                item[field] = True
        payloads[SETTINGS_KEY] = settings

    try:
        mutate_json_states({SETTINGS_KEY: dict}, _apply)
    except Exception:
        safe_session_rollback()


# ---------------------------------------------------------------------------
# Horodatage Maroc
# ---------------------------------------------------------------------------
def _local_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Africa/Casablanca"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=1)))


def _today() -> str:
    return _local_now().date().isoformat()


# ---------------------------------------------------------------------------
# Sélection des produits
# ---------------------------------------------------------------------------
def _first_image(product: Product) -> str:
    return next((name.strip() for name in (product.image_file or "").split("|") if name.strip()), "")


def _image_exists(filename: str) -> bool:
    root = current_app.config.get("UPLOAD_FOLDER") or str(Path(current_app.static_folder) / "uploads")
    try:
        root_path = Path(root).resolve()
        candidate = (root_path / filename).resolve()
        return candidate.is_relative_to(root_path) and candidate.is_file()
    except (OSError, ValueError):
        return False


def select_products(
    count: int,
    *,
    cooldown_days: int,
    promoted: dict[str, str] | None = None,
    pinned_ids: list[int] | None = None,
) -> list[Product]:
    """Sélectionne des produits physiques actifs, avec priorité aux coups de cœur épinglés."""
    promoted = promoted or {}
    pinned_ids = pinned_ids or []
    selected: list[Product] = []
    seen_ids: set[int] = set()

    # 1. Sélection prioritaire des produits "Coup de cœur" choisis manuellement par l'admin
    if pinned_ids:
        try:
            pinned_query = (
                Product.query
                .outerjoin(Shop, Shop.id == Product.shop_id)
                .options(selectinload(Product.shop), selectinload(Product.category))
                .filter(Product.id.in_(pinned_ids))
                .filter(Product.is_active.is_(True))
                .all()
            )
            pinned_map = {p.id: p for p in pinned_query}
            for pid in pinned_ids:
                if pid in pinned_map and pid not in seen_ids:
                    selected.append(pinned_map[pid])
                    seen_ids.add(pid)
        except Exception:
            safe_session_rollback()

    remaining_quota = max(0, count - len(selected))
    if remaining_quota <= 0:
        return selected[:count]

    cutoff = (_local_now().date() - timedelta(days=cooldown_days)).isoformat()
    recent_ids = {int(pid) for pid, day in promoted.items() if str(day) > cutoff and str(pid).isdigit()}
    try:
        candidates = (
            Product.query
            .outerjoin(Shop, Shop.id == Product.shop_id)
            .options(selectinload(Product.shop), selectinload(Product.category))
            .filter(Product.is_active.is_(True))
            .filter(or_(Product.shop_id.is_(None), Shop.is_active.is_(True)))
            .filter(Product.kind == "physical")
            .filter(Product.stock > 0)
            .filter(Product.image_file.isnot(None), Product.image_file != "")
            .order_by(Product.created_at.desc())
            .limit(300)
            .all()
        )
    except Exception:
        safe_session_rollback()
        return selected

    candidates = [p for p in candidates if p.id not in seen_ids and _image_exists(_first_image(p))]
    fresh = [p for p in candidates if p.id not in recent_ids]
    pool = fresh if len(fresh) >= remaining_quota else candidates
    promos = get_active_promos_for_products([p.id for p in pool])
    with_promo = [p for p in pool if p.id in promos]
    without_promo = [p for p in pool if p.id not in promos]
    random.shuffle(with_promo)
    random.shuffle(without_promo)
    auto_selected = (with_promo + without_promo)[:remaining_quota]
    return selected + auto_selected


def _public_base_url() -> str:
    return (
        current_app.config.get("WHATSAPP_PROMO_PUBLIC_URL")
        or current_app.config.get("PUBLIC_BASE_URL")
        or "https://www.babamarket.ma"
    ).rstrip("/")


def _format_dh(value: float) -> str:
    amount = float(value or 0)
    return f"{amount:.0f}" if amount.is_integer() else f"{amount:.2f}"


def build_product_card(product: Product, promo=None) -> dict[str, Any]:
    final = float(prix_final(product, promo))
    base_price = float(product.price or 0)
    base = _public_base_url()
    page = f"{base}/p/{product.id}"
    image = f"{base}/shop/product/{product.id}/photo/0/download"
    shop_name = getattr(product.shop, "name", "") or ""
    category = getattr(getattr(product, "category", None), "name", "") or ""
    return {
        "id": product.id,
        "name": product.name,
        "description": " ".join(str(product.description or "").split())[:300],
        "shop": shop_name,
        "category": category,
        "price": final,
        "old_price": base_price if final < base_price else None,
        "price_line": (
            f"💰 {_format_dh(final)} DH au lieu de {_format_dh(base_price)} DH"
            if final < base_price else f"💰 {_format_dh(final)} DH"
        ),
        "page_url": page,
        "image_url": image,
    }


def _tracked(url: str, medium: str = "") -> str:
    """Retourne une URL courte, propre et digne de confiance pour WhatsApp."""
    return url


# ---------------------------------------------------------------------------
# Textes commerciaux (Gemini + Repli)
# ---------------------------------------------------------------------------
def _clean_body_text(text: str) -> str:
    """Nettoie le texte pour enlever les résidus de templates, liens, STOP, salutations ou badges."""
    if not text:
        return ""
    lines = []
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if "http://" in lower or "https://" in lower:
            continue
        if "stop" in lower and ("répondez" in lower or "repondez" in lower or lower == "stop"):
            continue
        if lower.startswith("bonjour"):
            continue
        if any(line.startswith(c) for c in ("✨", "🌟", "📢", "💰", "👉", "✅", "🚚", "💵", "*")):
            continue
        lines.append(line)
    return " ".join(lines).strip()


def _sanitize_copy(text: Any, limit: int) -> str:
    value = _UNSAFE_CHARS_RE.sub("", _URL_RE.sub("", str(text or "")))
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value[:limit].strip()


def _fallback_copy(card: dict[str, Any]) -> dict[str, str]:
    shop = f" chez {card['shop']}" if card.get("shop") else ""
    return {
        "status": f"⚡ {card['name']}{shop} disponible !",
        "message": f"Produit de qualité disponible immédiatement en commande directe{shop}.",
    }


def generate_copy(cards: list[dict[str, Any]], *, session: requests.Session | None = None) -> tuple[dict[int, dict[str, str]], str]:
    """Génère les textes promotionnels via Gemini avec repli automatique."""
    fallback = {card["id"]: _fallback_copy(card) for card in cards}
    api_key = str(current_app.config.get("GEMINI_API_KEY") or "").strip()
    if not api_key or not cards:
        return fallback, "fallback"

    model = str(current_app.config.get("GEMINI_MODEL") or "gemini-flash-lite-latest").strip()
    data = [
        {key: card[key] for key in ("id", "name", "description", "shop", "category")}
        for card in cards
    ]
    instruction = (
        "Tu es le conseiller commercial WhatsApp de Baba Market au Maroc. "
        "RÈGLE ABSOLUE : INTERDICTION DU BLABLA GÉNÉRIQUE ET COMMERCIAL BANAL "
        "(Bannis formellement: 'Savourez nos excellents...', 'Profitez de...', 'Simplifiez votre...', 'Découvrez nos...'). "
        "Un client WhatsApp veut une description concrète, utile, naturelle et rassurante en français. "
        "Pour chaque produit ou service, écris deux champs : "
        "1. \"status\" : 1 courte phrase percutante et concrète (30 à 45 caractères max, 1 emoji). "
        "2. \"message\" : 1 seule phrase simple, précise et rassurante (8 à 14 mots max) qui décrit l'utilité réelle du produit/service "
        "(fraîcheur, qualité vérifiée, efficacité, soin). "
        "Exemples concrets : "
        "- Alimentaire -> status: '🌿 Feuilles de patate fraîches du jour !', message: 'Feuilles fraîches de qualité supérieure, idéales pour vos sauces et plats.' "
        "- Déménagement -> status: '📦 Déménagement soigné et rapide !', message: 'Transport sécurisé et manipulation méticuleuse de vos meubles et cartons.' "
        "- Repas -> status: '🍗 Riz poulet chaud et savoureux !', message: 'Plat copieux préparé à la commande avec des ingrédients frais.' "
        "N'écris JAMAIS de prix, JAMAIS de lien, JAMAIS de numéro : ils sont ajoutés automatiquement dans le modèle. "
        "Réponds STRICTEMENT en JSON : {\"items\":[{\"id\":0,\"status\":\"...\",\"message\":\"...\"}]}."
    )
    payload = {
        "system_instruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(data, ensure_ascii=False)}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.7, "maxOutputTokens": 1500},
    }
    try:
        response = (session or requests).post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key}, json=payload, timeout=(3, 25),
        )
        if response.status_code != 200:
            current_app.logger.info("whatsapp_promo.gemini_failed status=%s", response.status_code)
            return fallback, "fallback"
        parts = response.json()["candidates"][0]["content"]["parts"]
        parsed = json.loads("".join(part.get("text", "") for part in parts if not part.get("thought")))
        result = dict(fallback)
        for item in parsed.get("items", []) if isinstance(parsed, dict) else []:
            try:
                pid = int(item.get("id"))
            except (TypeError, ValueError, AttributeError):
                continue
            if pid not in result:
                continue
            status = _sanitize_copy(item.get("status"), 120)
            message = _sanitize_copy(item.get("message"), 400)
            result[pid] = {
                "status": status or fallback[pid]["status"],
                "message": message or fallback[pid]["message"],
            }
        return result, "gemini"
    except Exception as exc:
        current_app.logger.info("whatsapp_promo.gemini_fallback reason=%s", type(exc).__name__)
        return fallback, "fallback"


def compose_status_caption(card: dict[str, Any], copy: dict[str, str]) -> str:
    """Légende pour le Statut WhatsApp 24h."""
    if copy.get("is_custom") and copy.get("custom_caption"):
        body = _clean_body_text(copy["custom_caption"])
    else:
        body = _clean_body_text(copy.get("status") or copy.get("message") or "")
    parts = []
    if body:
        parts.append(body)
    if card.get("price_line"):
        parts.append(card["price_line"])
    parts.append(f"👉 {_tracked(card.get('page_url', ''), 'status')}")
    return "\n".join(parts)


def compose_group_message(card: dict[str, Any], copy: dict[str, str], group_label: str = "") -> str:
    """Message destiné aux Groupes de vente WhatsApp (dynamique et rassurant)."""
    clean_grp = (group_label or "").strip()
    if clean_grp.lower() in ("groupe", "group", "whatsapp"):
        clean_grp = ""
    header = f"📢 *Offre spéciale {clean_grp}*" if clean_grp else "📢 *Offre du jour Baba Market*"

    shop_line = f" chez *{card['shop']}*" if card.get("shop") else ""
    product_line = f"🌟 *{card['name']}*{shop_line}"

    if copy.get("is_custom") and copy.get("custom_group_message"):
        body_text = _clean_body_text(copy["custom_group_message"])
    else:
        body_text = _clean_body_text(copy.get("group_message") or copy.get("message") or copy.get("status") or "")

    parts = [header, product_line]
    if body_text:
        parts.append(body_text)
    if card.get("price_line"):
        parts.append(card["price_line"])

    parts.append("🚚 Livraison rapide • 💵 Paiement à la livraison")
    parts.append(f"👉 Voir & Commander en 1 clic : {_tracked(card.get('page_url', ''), 'group')}")
    return "\n\n".join(parts)


def compose_message(card: dict[str, Any], copy: dict[str, str], label: str = "") -> str:
    """Message direct personnalisé 1-à-1 chaleureux, rassurant et sans blabla."""
    clean_label = (label or "").strip()
    if clean_label.lower() in ("admin", "test", "client", "destinataire", "user", "contact", "abonne", "inconnu"):
        clean_label = ""
    greeting = f"Bonjour {clean_label} 👋" if clean_label else "Bonjour 👋"

    if copy.get("is_custom") and copy.get("custom_direct_message"):
        body_text = _clean_body_text(copy["custom_direct_message"])
    else:
        body_text = _clean_body_text(copy.get("direct_message") or copy.get("message") or copy.get("status") or "")

    shop_name = card.get("shop")
    shop_line = f" chez *{shop_name}*" if shop_name else ""
    product_header = f"✨ *{card['name']}*{shop_line}"

    parts = [greeting, product_header]
    if body_text:
        parts.append(body_text)

    if card.get("price_line"):
        parts.append(card["price_line"])

    # Réassurance concrète pour le client marocain
    reassurance = [
        "✅ Qualité vérifiée & satisfaction garantie",
        "🚚 Livraison rapide à domicile",
        "💵 Paiement à la livraison",
    ]
    parts.append("\n".join(reassurance))

    # Lien court et clair sur sa propre ligne
    url = _tracked(card.get('page_url', ''), 'message')
    parts.append(f"👉 Commander en 1 clic ici :\n{url}")

    return "\n\n".join(parts)


def update_product_copy(
    product_id: int | str,
    status_caption: str | None = None,
    group_message: str | None = None,
    direct_message: str | None = None,
) -> dict[str, Any] | None:
    """Met à jour manuellement les textes générés pour un produit."""
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return None

    log = get_log() or {}
    last_gen = log.get("last_generated")
    if not last_gen or not isinstance(last_gen, dict):
        return None

    items = list(last_gen.get("items") or last_gen.get("products") or [])
    found = False
    for item in items:
        if item.get("id") == pid or item.get("product_id") == pid:
            if status_caption is not None:
                item["status_caption"] = status_caption.strip()
            if group_message is not None:
                item["group_message"] = group_message.strip()
                item["group_message_sample"] = group_message.strip()
            if direct_message is not None:
                item["direct_message"] = direct_message.strip()
            found = True
            break

    if not found:
        return None

    last_gen["items"] = items
    last_gen["products"] = items
    last_gen["manually_edited"] = True

    _record_run(
        summary=log.get("last_preview") or {},
        promoted_ids=[],
        sent_today=0,
        today=_today(),
        preview=True,
        last_generated=last_gen,
    )
    return last_gen


# ---------------------------------------------------------------------------
# Appels Passerelle Node.js Baileys
# ---------------------------------------------------------------------------
def _gateway_base_url() -> str:
    explicit = current_app.config.get("BABA_WHATSAPP_BASE_URL")
    if explicit:
        return str(explicit).rstrip("/")
    send_url = str(current_app.config.get("BABA_WHATSAPP_GATEWAY_URL") or "http://127.0.0.1:3002/api/send")
    return re.sub(r"/api/send/?$", "", send_url).rstrip("/")


def _gateway_post(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    key = str(current_app.config.get("BABA_WHATSAPP_API_KEY") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key
    timeout = int(current_app.config.get("BABA_WHATSAPP_MEDIA_TIMEOUT") or 45)
    try:
        response = requests.post(f"{_gateway_base_url()}{path}", json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return 0, {"error": type(exc).__name__}
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


def post_status(card: dict[str, Any], caption: str, audience: list[str]) -> tuple[bool, str]:
    code, body = _gateway_post("/api/promo/status", {
        "image_url": card["image_url"],
        "caption": caption,
        "status_jid_list": audience,
    })
    return code in (200, 201), str(body.get("error") or code)


def send_promo_media(target: str, card: dict[str, Any], text: str) -> tuple[str, str]:
    """Envoie une photo + texte vers un numéro client ou un groupe WhatsApp.
    Retourne (résultat, détail) : sent | opted_out | not_on_whatsapp | failed
    """
    payload = {
        "target": target,
        "phone": target,
        "image_url": card.get("image_url", ""),
        "caption": text,
    }
    code, body = _gateway_post("/api/promo/send-media", payload)
    if code in (200, 201):
        return "sent", "ok"
    err_msg = str(body.get("error") or code)
    current_app.logger.warning(
        "whatsapp_promo.send_promo_media_failed target=%s code=%s error=%s body=%s",
        target, code, err_msg, body
    )
    if code == 409:
        return "opted_out", err_msg
    if code == 404 and body.get("error") == "not_on_whatsapp":
        return "not_on_whatsapp", "not_on_whatsapp"
    return "failed", err_msg


# Pour rétro-compatibilité
def send_promo_message(phone: str, card: dict[str, Any], text: str) -> tuple[str, str]:
    return send_promo_media(phone, card, text)


MAX_SEND_ATTEMPTS = 3
RETRY_DELAY = 2.0


def post_status_with_retry(
    card: dict[str, Any],
    caption: str,
    audience: list[str],
    *,
    max_attempts: int = MAX_SEND_ATTEMPTS,
) -> tuple[bool, str, int]:
    """Publie un statut WhatsApp 24h avec tentatives automatiques et garde-fous."""
    last_reason = "unknown"
    for attempt in range(1, max_attempts + 1):
        ok, reason = post_status(card, caption, audience)
        if ok:
            return True, "ok", attempt
        last_reason = str(reason)
        if attempt < max_attempts:
            gw = get_whatsapp_gateway_status()
            if gw.get("status") != "connected":
                return False, f"passerelle_deconnectee: {reason}", attempt
            sleep(RETRY_DELAY * attempt + random.uniform(0.3, 1.0))
    return False, last_reason, max_attempts


def send_promo_media_with_retry(
    target: str,
    card: dict[str, Any],
    text: str,
    *,
    max_attempts: int = MAX_SEND_ATTEMPTS,
) -> tuple[str, str, int]:
    """Envoie une photo + texte avec tentatives automatiques et garde-fous stricts.
    Retourne (resultat, detail, tentatives).
    """
    last_reason = "unknown"
    for attempt in range(1, max_attempts + 1):
        result, reason = send_promo_media(target, card, text)
        if result == "sent":
            return "sent", "ok", attempt

        # GARDE-FOU STRICT : Jamais de relance pour désinscription ou numéro inexistant
        if result in ("opted_out", "not_on_whatsapp"):
            return result, reason, attempt

        # GARDE-FOU : Cible ou payload invalide
        if reason in ("invalid_target", "invalid_media_payload"):
            return "failed", reason, attempt

        last_reason = str(reason)
        if attempt < max_attempts:
            gw = get_whatsapp_gateway_status()
            if gw.get("status") != "connected":
                return "failed", f"passerelle_deconnectee: {reason}", attempt
            sleep(RETRY_DELAY * attempt + random.uniform(0.3, 1.0))

    return "failed", last_reason, max_attempts



# ---------------------------------------------------------------------------
# Exécution de l'automatisation
# ---------------------------------------------------------------------------
def _audience(settings: dict[str, Any]) -> list[dict[str, str]]:
    """Contacts individuels : Admin en 1er, puis opt-in actifs."""
    people: list[dict[str, str]] = []
    seen: set[str] = set()
    if settings["admin_phone"]:
        people.append({"phone": settings["admin_phone"], "label": "Admin"})
        seen.add(settings["admin_phone"])
    for item in settings["recipients"]:
        if item["phone"] in seen or item.get("opted_out") or item.get("invalid"):
            continue
        seen.add(item["phone"])
        people.append({"phone": item["phone"], "label": item.get("label", "")})
    return people


def _claim_daily_run(today: str, force: bool) -> bool:
    """Verrou journalier pour éviter les doubles envois intempestifs (non-bloquant)."""
    try:
        from ..models.runtime_state import RuntimeState
        row = RuntimeState.query.filter_by(state_key=LOG_KEY).first()
        now = datetime.utcnow()
        log = json.loads(row.value_json) if row and row.value_json else {}
        if log.get("last_run_date") == today and not force:
            return False
        log["last_run_date"] = today
        val_str = json.dumps(log, ensure_ascii=True, separators=(",", ":"))
        if row is None:
            row = RuntimeState(state_key=LOG_KEY, created_at=now, updated_at=now, value_json=val_str)
            db.session.add(row)
        else:
            row.value_json = val_str
            row.updated_at = now
        db.session.commit()
        return True
    except Exception:
        safe_session_rollback()
        return False


def _save_promo_log(log_data: dict[str, Any]) -> None:
    """Persiste l'état de log promo de manière directe et non-bloquante."""
    _persist_json_state(LOG_KEY, log_data)


def _record_run(
    summary: dict[str, Any],
    *,
    promoted_ids: list[int],
    sent_today: int,
    today: str,
    preview: bool,
    last_generated: dict[str, Any] | None = None,
    new_recent_logs: list[dict[str, Any]] | None = None,
) -> None:
    # 1. Mise à jour de l'objet de log en mémoire
    current_log = get_log() or {}
    if not isinstance(current_log, dict):
        current_log = {}

    if last_generated:
        current_log["last_generated"] = last_generated

    if new_recent_logs:
        existing_logs = list(current_log.get("recent_logs") or [])
        current_log["recent_logs"] = (new_recent_logs + existing_logs)[:MAX_RECENT_LOGS_KEPT]

    if preview:
        current_log["last_preview"] = summary
    else:
        runs = [summary] + list(current_log.get("runs") or [])
        current_log["runs"] = runs[:MAX_RUNS_KEPT]
        promoted = dict(current_log.get("promoted") or {})
        for pid in promoted_ids:
            promoted[str(pid)] = today
        cutoff = (_local_now().date() - timedelta(days=60)).isoformat()
        current_log["promoted"] = {pid: day for pid, day in promoted.items() if str(day) >= cutoff}
        sent_by_date = {day: n for day, n in dict(current_log.get("sent_by_date") or {}).items() if day >= cutoff}
        sent_by_date[today] = int(sent_by_date.get(today, 0)) + sent_today
        current_log["sent_by_date"] = sent_by_date

    _persist_json_state(LOG_KEY, current_log)


def run_daily_promo(
    *,
    force: bool = False,
    dry_run: bool | None = None,
    include_status: bool = True,
    include_groups: bool = True,
    include_messages: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    settings = get_settings()
    preview = settings["dry_run"] if dry_run is None else bool(dry_run)
    today = _today()

    # Prise en compte des canaux actifs (Statut et Groupes uniquement)
    run_status = include_status and settings.get("status_enabled", True)
    run_groups = include_groups and settings.get("groups_enabled", True)
    run_messages = False

    summary: dict[str, Any] = {
        "started_at": _local_now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "dry_run" if preview else "live",
        "copy_source": None,
        "products": [],
        "statuses_ok": 0,
        "statuses_failed": 0,
        "groups_ok": 0,
        "groups_failed": 0,
        "messages_ok": 0,
        "messages_failed": 0,
        "skipped": 0,
        "aborted": None,
        "details": [],
    }

    recent_events: list[dict[str, Any]] = []

    def finish(reason: str | None = None, promoted_ids: list[int] | None = None, last_gen: dict[str, Any] | None = None) -> dict[str, Any]:
        summary["aborted"] = reason
        summary["finished_at"] = _local_now().strftime("%Y-%m-%d %H:%M:%S")
        sent = summary["messages_ok"] + summary["groups_ok"]
        _record_run(
            summary,
            promoted_ids=promoted_ids or [],
            sent_today=sent,
            today=today,
            preview=preview,
            last_generated=last_gen,
            new_recent_logs=recent_events,
        )
        current_app.logger.info(
            "whatsapp_promo.run mode=%s statuts=%s/%s groupes=%s/%s direct=%s/%s aborted=%s",
            summary["mode"],
            summary["statuses_ok"], summary["statuses_failed"],
            summary["groups_ok"], summary["groups_failed"],
            summary["messages_ok"], summary["messages_failed"],
            reason,
        )
        return summary

    if not preview and not settings["enabled"]:
        summary["aborted"] = "disabled"
        return summary

    if not run_status and not run_groups:
        return finish("no_channel_enabled")

    if not preview and not _claim_daily_run(today, force):
        summary["aborted"] = "already_ran_today"
        return summary

    if not preview:
        gateway = get_whatsapp_gateway_status()
        if gateway.get("status") != "connected":
            return finish("gateway_not_connected")

    log = get_log()
    last_gen = log.get("last_generated") or {}
    saved_items = last_gen.get("items") or []

    # Envoi réel : si un aperçu validé existe aujourd'hui, on réutilise ses produits et textes exacts
    if not preview and saved_items and last_gen.get("date") == today:
        cards = []
        copies = {}
        base = _public_base_url()
        source = last_gen.get("copy_source") or "validated"
        for item in saved_items:
            cards.append({
                "id": item["id"],
                "name": item.get("title") or item.get("name") or "",
                "shop": item.get("shop_name") or item.get("shop") or "",
                "category": item.get("shop_city") or "",
                "price": item.get("price", 0),
                "old_price": item.get("old_price"),
                "price_line": item.get("price_line", ""),
                "image_url": item.get("image_url", ""),
                "page_url": f"{base}/p/{item['id']}",
            })
            raw_text = _clean_body_text(item.get("ai_message") or item.get("message") or item.get("direct_message") or "")
            raw_status = _clean_body_text(item.get("ai_status") or item.get("status") or item.get("status_caption") or "")
            is_custom = bool(item.get("is_custom"))
            copies[item["id"]] = {
                "is_custom": is_custom,
                "custom_caption": _clean_body_text(item.get("custom_caption") or "") if is_custom else "",
                "custom_group_message": _clean_body_text(item.get("custom_group_message") or "") if is_custom else "",
                "custom_direct_message": _clean_body_text(item.get("custom_direct_message") or "") if is_custom else "",
                "status": raw_status,
                "message": raw_text,
            }
        summary["copy_source"] = source
    else:
        products = select_products(
            settings["status_products"],
            cooldown_days=settings["cooldown_days"],
            promoted=log.get("promoted") or {},
            pinned_ids=settings.get("pinned_product_ids") or [],
        )
        if not products:
            return finish("no_eligible_product")

        promos = get_active_promos_for_products([p.id for p in products])
        cards = [build_product_card(p, promos.get(p.id)) for p in products]
        copies, source = generate_copy(cards)
        summary["copy_source"] = source


    # Construction du modèle d'aperçu pour l'interface admin
    items_data = [
        {
            "id": c["id"],
            "product_id": c["id"],
            "name": c["name"],
            "title": c["name"],
            "shop": c["shop"],
            "shop_name": c["shop"],
            "shop_city": c.get("category", "") or "",
            "price": c.get("price", 0),
            "price_dh": str(c.get("price", 0)),
            "old_price": c.get("old_price"),
            "old_price_dh": str(c.get("old_price")) if c.get("old_price") else "",
            "price_line": c["price_line"],
            "image_url": c["image_url"],
            "page_url": c["page_url"],
            "product_url": c["page_url"],
            "status_caption": compose_status_caption(c, copies[c["id"]]),
            "group_message": compose_group_message(c, copies[c["id"]]),
            "group_message_sample": compose_group_message(c, copies[c["id"]]),
            "ai_status": copies[c["id"]].get("status", ""),
            "ai_message": copies[c["id"]].get("message", ""),
            "is_custom": bool(copies[c["id"]].get("is_custom")),
            "direct_message": compose_message(c, copies[c["id"]], ""),
        }
        for c in cards
    ]
    last_generated_data = {
        "generated_at": f"{today} {_local_now().strftime('%H:%M:%S')}",
        "date": today,
        "time": _local_now().strftime("%H:%M:%S"),
        "source": source,
        "copy_source": source,
        "dry_run": preview,
        "items": items_data,
        "products": items_data,
    }
    summary["products"] = items_data
    summary["last_generated"] = last_generated_data

    def still_enabled() -> bool:
        return preview or get_settings()["enabled"]

    consecutive_failures = 0
    people = _audience(settings)
    groups = settings.get("groups", [])

    # 1. CANAL STATUT WHATSAPP (Story 24h)
    if run_status:
        audience_phones = [person["phone"] for person in people]
        for index, card in enumerate(cards):
            caption = compose_status_caption(card, copies[card["id"]])
            event = {
                "timestamp": f"{today} {_local_now().strftime('%H:%M:%S')}",
                "time": _local_now().strftime("%H:%M:%S"),
                "channel": "status",
                "channel_label": "Statut 24h",
                "product_id": card["id"],
                "product_name": card["name"],
                "product_title": card["name"],
                "target": "status",
                "target_desc": "Statut WhatsApp (Story)",
                "text": caption,
            }
            if preview:
                summary["statuses_ok"] += 1
                event["status"] = "ok"
                event["details"] = "Aperçu simulé"
                event["detail"] = event["details"]
                recent_events.append(event)
                summary["details"].append(event)
                continue

            if not still_enabled():
                return finish("stopped_by_admin", [c["id"] for c in cards[:index]], last_generated_data)

            ok, reason, attempts = post_status_with_retry(card, caption, audience_phones)
            summary["statuses_ok" if ok else "statuses_failed"] += 1
            event["attempts"] = attempts
            event["status"] = "ok" if ok else "failed"
            if ok:
                event["details"] = "Publié avec succès" if attempts == 1 else f"Publié (après {attempts} tentatives)"
                consecutive_failures = 0
            else:
                event["details"] = f"Échec après {attempts} tentatives: {reason}"
                consecutive_failures += 1

            event["detail"] = event["details"]
            recent_events.append(event)
            summary["details"].append(event)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                return finish("gateway_failures", [c["id"] for c in cards[:index + 1]], last_generated_data)

            if index < len(cards) - 1:
                sleep(random.uniform(*STATUS_DELAY_RANGE))

    # 2. CANAL GROUPES WHATSAPP
    if run_groups:
        if not groups:
            event = {
                "timestamp": f"{today} {_local_now().strftime('%H:%M:%S')}",
                "time": _local_now().strftime("%H:%M:%S"),
                "channel": "group",
                "channel_label": "Groupe WhatsApp",
                "product_id": cards[0]["id"] if cards else 0,
                "product_name": cards[0]["name"] if cards else "Offre",
                "product_title": cards[0]["name"] if cards else "Offre",
                "target": "groups",
                "target_desc": "Groupes WhatsApp",
                "text": "",
                "status": "skipped",
                "details": "Aucun groupe configuré dans vos réglages. Ouvrez « Gérer mes groupes » pour coller les liens de vos groupes de vente.",
                "detail": "Aucun groupe configuré dans vos réglages. Ouvrez « Gérer mes groupes » pour coller les liens de vos groupes de vente.",
                "attempts": 0,
            }
            recent_events.append(event)
            summary["details"].append(event)
        else:
            for grp in groups:
                group_label = grp.get("label") or grp["target"]
                for card_idx, card in enumerate(cards):
                    group_text = compose_group_message(card, copies[card["id"]], group_label)
                    event = {
                        "timestamp": f"{today} {_local_now().strftime('%H:%M:%S')}",
                        "time": _local_now().strftime("%H:%M:%S"),
                        "channel": "group",
                        "channel_label": "Groupe WhatsApp",
                        "product_id": card["id"],
                        "product_name": card["name"],
                        "product_title": card["name"],
                        "target": grp["target"],
                        "target_desc": group_label,
                        "text": group_text,
                    }
                    if preview:
                        summary["groups_ok"] += 1
                        event["status"] = "ok"
                        event["details"] = "Aperçu simulé"
                        event["detail"] = event["details"]
                        recent_events.append(event)
                        summary["details"].append(event)
                        continue

                    if not still_enabled():
                        return finish("stopped_by_admin", [c["id"] for c in cards], last_generated_data)

                    current_app.logger.info("whatsapp_promo.attempting_group_send target=%s label=%s card_id=%s", grp["target"], group_label, card["id"])
                    result, reason, attempts = send_promo_media_with_retry(grp["target"], card, group_text)
                    event["attempts"] = attempts
                    if result == "sent":
                        summary["groups_ok"] += 1
                        consecutive_failures = 0
                        event["status"] = "ok"
                        event["details"] = "Envoyé dans le groupe" if attempts == 1 else f"Envoyé dans le groupe (après {attempts} tentatives)"
                        current_app.logger.info("whatsapp_promo.group_sent_ok target=%s label=%s", grp["target"], group_label)
                    else:
                        summary["groups_failed"] += 1
                        consecutive_failures += 1
                        event["status"] = "failed"
                        event["details"] = f"Erreur après {attempts} tentatives: {reason}"
                        current_app.logger.warning("whatsapp_promo.group_send_failed target=%s label=%s reason=%s attempts=%s", grp["target"], group_label, reason, attempts)

                    event["detail"] = event["details"]
                    recent_events.append(event)
                    summary["details"].append(event)

                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        return finish("gateway_failures", [c["id"] for c in cards], last_generated_data)

                    sleep(random.uniform(settings["min_delay"], settings["max_delay"]))

    return finish(None, [] if preview else [c["id"] for c in cards], last_generated_data)


def run_in_background(app, **kwargs) -> None:
    """Lance une exécution réelle en tâche de fond pour ne pas bloquer l'UI."""
    import threading

    def _worker() -> None:
        with app.app_context():
            try:
                run_daily_promo(**kwargs)
            except Exception:
                db.session.rollback()
                app.logger.exception("whatsapp_promo.background_failed")
            finally:
                db.session.remove()

    threading.Thread(target=_worker, name="whatsapp-promo", daemon=True).start()


# ---------------------------------------------------------------------------
# Commandes CLI : flask whatsapp-promo run|status
# ---------------------------------------------------------------------------
def init_whatsapp_promo_cli(app) -> None:
    import click

    @app.cli.group("whatsapp-promo")
    def whatsapp_promo_group():
        """Commandes de promotion WhatsApp (Statuts, Groupes, Clients)."""

    @whatsapp_promo_group.command("run")
    @click.option("--dry-run/--live", "dry_run", default=None, help="Aperçu ou réel.")
    @click.option("--force", is_flag=True, help="Ignorer le verrou du jour.")
    @click.option("--status-only", is_flag=True, help="Uniquement Statuts.")
    @click.option("--groups-only", is_flag=True, help="Uniquement Groupes.")
    @click.option("--messages-only", is_flag=True, help="Uniquement Messages Privés.")
    def run_command(dry_run, force, status_only, groups_only, messages_only):
        inc_status = not (groups_only or messages_only)
        inc_groups = not (status_only or messages_only)
        inc_messages = not (status_only or groups_only)
        summary = run_daily_promo(
            force=force,
            dry_run=dry_run,
            include_status=inc_status,
            include_groups=inc_groups,
            include_messages=inc_messages,
        )
        click.echo(json.dumps({k: v for k, v in summary.items() if k != "details"}, ensure_ascii=False, indent=2))
        if summary.get("mode") == "dry_run":
            for d in summary.get("details", []):
                click.echo(f"\n--- [{d.get('channel')}] {d.get('target')} ---\n{d.get('text', '')}")

    @whatsapp_promo_group.command("status")
    def status_command():
        settings = get_settings()
        log = get_log()
        click.echo(json.dumps({
            "enabled": settings["enabled"],
            "dry_run": settings["dry_run"],
            "status_enabled": settings["status_enabled"],
            "groups_enabled": settings["groups_enabled"],
            "direct_messages_enabled": settings["direct_messages_enabled"],
            "admin_phone": settings["admin_phone"],
            "groups_count": len(settings.get("groups", [])),
            "recipients_count": len(_audience(settings)),
            "last_run_date": log.get("last_run_date"),
        }, ensure_ascii=False, indent=2))


def retry_failed_promos(*, force: bool = False) -> dict[str, Any]:
    """Relance les messages en échec ou en attente enregistrés aujourd'hui, avec garde-fous stricts."""
    today = _local_now().date().isoformat()
    log = get_log() or {}
    recent_logs = list(log.get("recent_logs") or [])
    settings = get_settings()

    # GARDE-FOU 1 : Vérifier la passerelle WhatsApp
    gw = get_whatsapp_gateway_status()
    if gw.get("status") != "connected":
        return {
            "success": False,
            "error": "gateway_not_connected",
            "message": "La passerelle WhatsApp n'est pas connectée. Vérifiez la connexion de votre téléphone.",
            "retried": 0,
            "ok": 0,
            "failed": 0,
        }

    # GARDE-FOU 2 : Contacts désinscrits (STOP) ou invalides exclus
    opted_out_targets = {
        r["phone"] for r in settings.get("recipients", []) if r.get("opted_out") or r.get("invalid")
    }

    to_retry = []
    for idx, item in enumerate(recent_logs):
        if item.get("status") in ("failed", "pending"):
            target = str(item.get("target") or "")
            if target in opted_out_targets:
                item["status"] = "skipped"
                item["detail"] = "Désinscrit (STOP) ou numéro invalide"
                item["details"] = item["detail"]
                continue
            to_retry.append((idx, item))

    if not to_retry:
        return {
            "success": True,
            "message": "Aucun message en attente ou en échec à relancer pour aujourd'hui.",
            "retried": 0,
            "ok": 0,
            "failed": 0,
        }

    # Données des produits
    last_gen = log.get("last_generated") or {}
    items_by_id = {
        item["id"]: item for item in (last_gen.get("items") or last_gen.get("products") or [])
    }

    retried_count = 0
    ok_count = 0
    failed_count = 0
    consecutive_failures = 0
    audience_phones = [p["phone"] for p in _audience(settings)]

    for idx, event in to_retry:
        if not settings.get("enabled") and not force:
            break

        channel = event.get("channel")
        target = event.get("target")
        text = event.get("text")
        pid = event.get("product_id")
        card = items_by_id.get(pid)

        if not card:
            prod = db.session.get(Product, pid)
            if prod:
                promos = get_active_promos_for_products([prod.id])
                card = build_product_card(prod, promos.get(prod.id))

        if not card or not target or not text:
            event["status"] = "failed"
            event["detail"] = "Données du produit introuvables pour relancer"
            event["details"] = event["detail"]
            failed_count += 1
            continue

        retried_count += 1

        if channel == "status":
            ok, reason, attempts = post_status_with_retry(card, text, audience_phones)
            if ok:
                ok_count += 1
                consecutive_failures = 0
                event["status"] = "ok"
                event["detail"] = "Statut publié avec succès (après relance)"
            else:
                failed_count += 1
                consecutive_failures += 1
                event["status"] = "failed"
                event["detail"] = f"Échec après relance: {reason}"
            event["attempts"] = event.get("attempts", 0) + attempts
        else:
            result, reason, attempts = send_promo_media_with_retry(target, card, text)
            if result == "sent":
                ok_count += 1
                consecutive_failures = 0
                event["status"] = "ok"
                event["detail"] = "Message remis avec succès (après relance)"
            elif result in ("opted_out", "not_on_whatsapp"):
                event["status"] = "skipped"
                event["detail"] = "Désinscrit (STOP)" if result == "opted_out" else "Pas de WhatsApp"
                _mark_recipient(target, "opted_out" if result == "opted_out" else "invalid")
            else:
                failed_count += 1
                consecutive_failures += 1
                event["status"] = "failed"
                event["detail"] = f"Échec après relance: {reason}"
            event["attempts"] = event.get("attempts", 0) + attempts

        event["details"] = event["detail"]
        event["timestamp"] = f"{today} {_local_now().strftime('%H:%M:%S')}"
        event["time"] = _local_now().strftime("%H:%M:%S")
        recent_logs[idx] = event

        # GARDE-FOU 3 : Déconnexion ou échecs consécutifs
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            break

        sleep(random.uniform(settings["min_delay"], settings["max_delay"]))

    # Sauvegarde des logs mis à jour
    log["recent_logs"] = recent_logs
    _save_promo_log(log)

    return {
        "success": True,
        "retried": retried_count,
        "ok": ok_count,
        "failed": failed_count,
        "message": f"Relance terminée : {ok_count} envoyé(s), {failed_count} échec(s).",
    }


def run_retry_in_background(app, **kwargs) -> None:
    """Lance la relance des messages non publiés en tâche de fond pour ne pas bloquer l'UI."""
    import threading

    def _worker() -> None:
        with app.app_context():
            try:
                retry_failed_promos(**kwargs)
            except Exception:
                safe_session_rollback()
                app.logger.exception("whatsapp_promo.retry_background_failed")
            finally:
                db.session.remove()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Suivi des Clics Réels sur les liens WhatsApp (/p/<id>)
# ---------------------------------------------------------------------------
def record_link_click(product_id: int) -> None:
    """Incrémente discrètement le compteur de clics pour ce produit et pour aujourd'hui."""
    today = _local_now().date().isoformat()
    def _apply(payloads: dict[str, Any]) -> None:
        log = payloads.get(LOG_KEY)
        if not isinstance(log, dict):
            log = {}
        clicks = dict(log.get("clicks_by_date") or {})
        day_stats = dict(clicks.get(today) or {})
        pid_key = str(product_id)
        day_stats[pid_key] = int(day_stats.get(pid_key, 0)) + 1
        day_stats["_total"] = int(day_stats.get("_total", 0)) + 1
        clicks[today] = day_stats
        log["clicks_by_date"] = clicks
        payloads[LOG_KEY] = log

    try:
        mutate_json_states({LOG_KEY: dict}, _apply)
    except Exception:
        safe_session_rollback()


def get_today_clicks() -> dict[str, int]:
    """Retourne les clics enregistrés aujourd'hui : {'_total': 12, '100': 5, ...}."""
    today = _local_now().date().isoformat()
    log = get_log() or {}
    clicks = dict(log.get("clicks_by_date") or {})
    return dict(clicks.get(today) or {})


# ---------------------------------------------------------------------------
# Envoi de Test Direct vers le WhatsApp de l'Administrateur
# ---------------------------------------------------------------------------
def send_test_to_admin(*, product_id: int | None = None) -> dict[str, Any]:
    """Envoie un aperçu réel (photo + texte) uniquement au WhatsApp de l'administrateur."""
    gw = get_whatsapp_gateway_status()
    if gw.get("status") != "connected":
        return {
            "success": False,
            "error": "gateway_not_connected",
            "message": "La passerelle WhatsApp n'est pas connectée. Veuillez connecter votre téléphone d'abord.",
        }

    settings = get_settings()
    admin_phone = settings.get("admin_phone") or gw.get("phone")
    if not admin_phone:
        return {
            "success": False,
            "error": "no_admin_phone",
            "message": "Aucun numéro d'administrateur configuré (indiquez votre numéro WhatsApp dans les réglages).",
        }

    log = get_log() or {}
    last_gen = log.get("last_generated") or {}
    items = list(last_gen.get("items") or last_gen.get("products") or [])

    card = None
    if product_id:
        for it in items:
            if it.get("id") == product_id or it.get("product_id") == product_id:
                card = it
                break

    if not card and items:
        card = items[0]

    # Si aucun aperçu généré, on en crée un à la volée
    if not card:
        prods = select_products(1, cooldown_days=0)
        if not prods:
            return {"success": False, "error": "no_product", "message": "Aucun produit disponible en stock."}
        promos = get_active_promos_for_products([prods[0].id])
        c = build_product_card(prods[0], promos.get(prods[0].id))
        copies, _ = generate_copy([c])
        card = c
        card["direct_message"] = compose_message(c, copies[c["id"]], "")

    text = (
        card.get("group_message")
        or card.get("group_message_sample")
        or card.get("status_caption")
        or card.get("direct_message")
        or compose_group_message(card, {"message": card.get("name", "")})
    )
    result, reason, attempts = send_promo_media_with_retry(admin_phone, card, text, max_attempts=2)

    today = _local_now().date().isoformat()
    now_time = _local_now().strftime("%H:%M:%S")

    test_event = {
        "timestamp": f"{today} {now_time}",
        "time": now_time,
        "channel": "direct",
        "channel_label": "Test Admin",
        "product_id": card["id"],
        "product_name": card.get("name") or card.get("title") or "",
        "product_title": card.get("name") or card.get("title") or "",
        "target": admin_phone,
        "target_desc": f"Mon WhatsApp ({admin_phone})",
        "text": text,
        "status": "ok" if result == "sent" else "failed",
        "detail": f"Test remis avec succès au {admin_phone}" if result == "sent" else f"Échec test: {reason}",
        "details": f"Test remis avec succès au {admin_phone}" if result == "sent" else f"Échec test: {reason}",
        "attempts": attempts,
    }

    recent_logs = [test_event] + list(log.get("recent_logs") or [])
    log["recent_logs"] = recent_logs[:MAX_RECENT_LOGS_KEPT]
    _save_promo_log(log)

    if result == "sent":
        return {
            "success": True,
            "phone": admin_phone,
            "message": f"Message test envoyé avec succès sur votre WhatsApp ({admin_phone}) !",
        }
    return {
        "success": False,
        "error": reason,
        "message": f"Échec de l'envoi test sur {admin_phone} : {reason}",
    }
