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

import base64
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

SETTINGS_SCHEMA_VERSION = 3
PERSISTENCE_WINDOW_HOURS = 2
PERSISTENCE_WINDOW_SECONDS = PERSISTENCE_WINDOW_HOURS * 3600  # 2h max de persistance d'envoi

HARD_MAX_MESSAGES_PER_DAY = 200
MAX_STATUS_PRODUCTS = 24
MIN_DELAY_FLOOR = 20
MIN_INTER_GROUP_STEP = 15.0
MAX_DELAY_CEILING = 300
MAX_CONSECUTIVE_FAILURES = 3
STATUS_DELAY_RANGE = (15, 45)
MAX_RUNS_KEPT = 20
MAX_RECENT_LOGS_KEPT = 100
OPT_OUT_FOOTER = "Répondez STOP pour ne plus recevoir nos offres."

DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": SETTINGS_SCHEMA_VERSION,
    "enabled": False,
    "dry_run": True,
    "status_enabled": True,
    "groups_enabled": True,
    "direct_messages_enabled": False,
    "admin_phone": "",
    "schedule_time": "10:30",
    "schedule_time_2": "18:30",
    "pinned_product_ids": [],
    "groups": [],
    "recipients": [],
    "status_products": 12,
    "products_count": 5,
    "services_count": 3,
    "rentals_count": 2,
    "rental_max_age_hours": 24,
    "daily_message_limit": 50,
    "min_delay": 45,
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


def _clean_pinned_ids(raw: Any) -> list[int | str]:
    cleaned: list[int | str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        if s.isdigit():
            seen.add(s)
            cleaned.append(int(s))
        elif s.startswith("rental_") and s[7:].isdigit():
            seen.add(s)
            cleaned.append(s)
        if len(cleaned) >= 15:
            break
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
    sched1 = str(raw.get("schedule_time") or "10:30").strip()
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", sched1):
        sched1 = "10:30"
    sched2 = str(raw.get("schedule_time_2") or "18:30").strip()
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", sched2):
        sched2 = "18:30"
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "enabled": bool(raw.get("enabled", DEFAULT_SETTINGS["enabled"])),
        "dry_run": bool(raw.get("dry_run", DEFAULT_SETTINGS["dry_run"])),
        "status_enabled": bool(raw.get("status_enabled", DEFAULT_SETTINGS["status_enabled"])),
        "groups_enabled": bool(raw.get("groups_enabled", DEFAULT_SETTINGS["groups_enabled"])),
        "direct_messages_enabled": bool(raw.get("direct_messages_enabled", DEFAULT_SETTINGS["direct_messages_enabled"])),
        "admin_phone": normalize_whatsapp_number(raw.get("admin_phone")),
        "schedule_time": sched1,
        "schedule_time_2": sched2,
        "pinned_product_ids": _clean_pinned_ids(raw.get("pinned_product_ids")),
        "groups": _clean_groups(raw.get("groups")),
        "recipients": _clean_recipients(raw.get("recipients")),
        "status_products": _clamp_int(raw.get("status_products"), DEFAULT_SETTINGS["status_products"], 1, MAX_STATUS_PRODUCTS),
        "products_count": _clamp_int(raw.get("products_count"), DEFAULT_SETTINGS["products_count"], 0, 15),
        "services_count": _clamp_int(raw.get("services_count"), DEFAULT_SETTINGS["services_count"], 0, 15),
        "rentals_count": _clamp_int(raw.get("rentals_count"), DEFAULT_SETTINGS["rentals_count"], 0, 15),
        "rental_max_age_hours": _clamp_int(raw.get("rental_max_age_hours"), DEFAULT_SETTINGS["rental_max_age_hours"], 1, 168),
        "daily_message_limit": _clamp_int(raw.get("daily_message_limit"), DEFAULT_SETTINGS["daily_message_limit"], 0, HARD_MAX_MESSAGES_PER_DAY),
        "min_delay": min(min_delay, max_delay),
        "max_delay": max(min_delay, max_delay),
        "cooldown_days": _clamp_int(raw.get("cooldown_days"), DEFAULT_SETTINGS["cooldown_days"], 0, 60),
    }


def get_settings() -> dict[str, Any]:
    try:
        raw = get_json_state(SETTINGS_KEY, dict)
        if isinstance(raw, dict) and raw and int(raw.get("schema_version") or 1) < SETTINGS_SCHEMA_VERSION:
            prev_ver = int(raw.get("schema_version") or 1)
            if prev_ver < 2:
                upgraded = normalize_settings({
                    **raw,
                    "schema_version": SETTINGS_SCHEMA_VERSION,
                    "products_count": 5,
                    "services_count": 3,
                    "rentals_count": 2,
                    "status_products": 12,
                    "min_delay": 45,
                    "max_delay": max(_clamp_int(raw.get("max_delay"), 90, MIN_DELAY_FLOOR, MAX_DELAY_CEILING), 90),
                    "daily_message_limit": max(_clamp_int(raw.get("daily_message_limit"), 50, 0, HARD_MAX_MESSAGES_PER_DAY), 50),
                })
            else:
                cur_status = int(raw.get("status_products") or 10)
                upgraded = normalize_settings({
                    **raw,
                    "schema_version": SETTINGS_SCHEMA_VERSION,
                    "status_products": 12 if cur_status == 10 else cur_status,
                })
            _persist_json_state(SETTINGS_KEY, upgraded)
            return upgraded
        return normalize_settings(raw)
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


def _parse_local_timestamp(ts: Any, *, ref_now: datetime | None = None) -> datetime | None:
    """Convertit un horodatage local 'YYYY-MM-DD HH:MM(:SS)' en datetime timezone-aware."""
    val = str(ts or "").strip()
    if not val:
        return None
    ref = ref_now or _local_now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(val, fmt)
            return parsed.replace(tzinfo=ref.tzinfo)
        except ValueError:
            continue
    return None


def _is_within_persistence_window(
    ts: Any,
    *,
    now: datetime | None = None,
    max_seconds: int = PERSISTENCE_WINDOW_SECONDS,
) -> bool:
    """Vérifie qu'un message ou aperçu date de moins de 2 heures (et du jour même)."""
    current = now or _local_now()
    dt = _parse_local_timestamp(ts, ref_now=current)
    if dt is None or dt.date() != current.date():
        return False
    age_seconds = (current - dt).total_seconds()
    return -300 <= age_seconds <= max_seconds


def _clean_and_expire_log(
    log: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Applique deux garde-fous automatiques :
    1. Vidage quotidien à minuit de l'Historique & Suivi des Messages (recent_logs, runs, compteurs).
    2. Persistance stricte de 2h : tout message bloqué (failed / pending) vieux de > 2h est vidé.
    """
    if not isinstance(log, dict) or not log:
        return {}, False

    current = now or _local_now()
    today = current.date().isoformat()
    cleaned = dict(log)
    changed = False

    stored_date = str(cleaned.get("history_date") or "").strip()
    if not stored_date:
        last_gen_date = str((cleaned.get("last_generated") or {}).get("date") or "").strip()
        first_log_date = ""
        init_logs = cleaned.get("recent_logs")
        if isinstance(init_logs, list) and init_logs and isinstance(init_logs[0], dict):
            first_log_date = str(init_logs[0].get("timestamp") or "")[:10]
        stored_date = last_gen_date or first_log_date or str(cleaned.get("last_run_date") or "").strip()

    # 1. Remise à zéro quotidienne de l'Historique et Suivi des Messages
    if stored_date and stored_date != today:
        cleaned["recent_logs"] = []
        cleaned["runs"] = []
        cleaned["last_preview"] = {}
        cleaned["last_generated"] = {}
        for day_map_key in (
            "clicks_by_date",
            "sent_by_date",
            "statuses_by_date",
            "sent_ids_by_date",
            "attempted_slots_by_date",
            "completed_slots_by_date",
        ):
            existing_map = dict(cleaned.get(day_map_key) or {})
            cleaned[day_map_key] = {today: existing_map[today]} if today in existing_map else {}
        cleaned["history_date"] = today
        changed = True
    elif cleaned.get("history_date") != today:
        cleaned["history_date"] = today
        changed = True

    # 2. Fenêtre stricte de 2h : purge automatique des messages en attente / échec > 2h ou hors date du jour
    raw_recent = cleaned.get("recent_logs")
    if isinstance(raw_recent, list) and raw_recent:
        kept_recent: list[dict[str, Any]] = []
        for entry in raw_recent:
            if not isinstance(entry, dict):
                changed = True
                continue
            ts_str = str(entry.get("timestamp") or "").strip()
            if ts_str and not ts_str.startswith(today):
                changed = True
                continue
            status_val = str(entry.get("status") or "").lower()
            if status_val in ("failed", "pending", "waiting"):
                if not _is_within_persistence_window(ts_str, now=current):
                    changed = True
                    continue
            kept_recent.append(entry)
        if len(kept_recent) != len(raw_recent):
            cleaned["recent_logs"] = kept_recent
            changed = True

    # 3. Expiration des aperçus d'un autre jour (les offres préparées pour la vague du jour restent actives jusqu'à leur envoi)
    last_gen = cleaned.get("last_generated")
    if isinstance(last_gen, dict) and last_gen:
        gen_date = str(last_gen.get("date") or "").strip()
        if gen_date and gen_date != today:
            cleaned["last_generated"] = {}
            changed = True

    # 4. Expiration automatique d'un indicateur d'envoi actif bloqué depuis > 2h
    active_send = cleaned.get("active_send")
    if isinstance(active_send, dict) and active_send:
        started_ts = active_send.get("started_at")
        if not _is_within_persistence_window(started_ts, now=current):
            cleaned["active_send"] = None
            changed = True

    return cleaned, changed


def get_log() -> dict[str, Any]:
    try:
        log = get_json_state(LOG_KEY, dict)
    except Exception:
        safe_session_rollback()
        log = {}
    if not isinstance(log, dict):
        return {}
    cleaned, changed = _clean_and_expire_log(log)
    if changed:
        _persist_json_state(LOG_KEY, cleaned)
    return cleaned


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


def _resolved_upload_root() -> Path:
    root = current_app.config.get("UPLOAD_FOLDER") or str(Path(current_app.static_folder) / "uploads")
    return Path(root).resolve()


def _fast_image_exists(filename: str, root_path: Path | None = None) -> bool:
    if not filename or ".." in filename or filename.startswith(("/", "\\")):
        return False
    try:
        base = root_path or _resolved_upload_root()
        return (base / filename).is_file()
    except (OSError, ValueError):
        return False


def _image_exists(filename: str) -> bool:
    try:
        root_path = _resolved_upload_root()
        candidate = (root_path / filename).resolve()
        return candidate.is_relative_to(root_path) and candidate.is_file()
    except (OSError, ValueError):
        return False


def _product_static_thumb_url(first_img: str, root_path: Path | None = None) -> str:
    """URL statique légère servie directement par Nginx (sans filigrane CPU ni blocage Gunicorn)."""
    clean = str(first_img or "").strip().replace("\\", "/").lstrip("/")
    if not clean or ".." in clean:
        return ""
    if clean.startswith("static/"):
        clean = clean[7:]
    if clean.startswith("uploads/"):
        clean = clean[8:]
    base = root_path or _resolved_upload_root()
    try:
        from .image import image_variant
        thumb_rel = image_variant(clean, "thumb")
        if thumb_rel and (base / thumb_rel).is_file():
            return f"/static/uploads/{thumb_rel}"
    except Exception:
        pass
    return f"/static/uploads/{clean}"


def _rental_static_thumb_url(img_filename: str) -> str:
    clean = str(img_filename or "").strip().replace("\\", "/").lstrip("/")
    if not clean or ".." in clean:
        return ""
    if clean.startswith("static/"):
        clean = clean[7:]
    if clean.startswith("uploads/"):
        clean = clean[8:]
    if not clean.startswith("rentals/"):
        clean = f"rentals/{clean}"
    return f"/static/uploads/{clean}"


def _product_static_large_url(img_name: str, root_path: Path | None = None) -> str:
    """URL statique grand format (variant large si disponible, sinon fichier original) servie par Nginx."""
    clean = str(img_name or "").strip().replace("\\", "/").lstrip("/")
    if not clean or ".." in clean:
        return ""
    if clean.startswith("static/"):
        clean = clean[7:]
    if clean.startswith("uploads/"):
        clean = clean[8:]
    base = root_path or _resolved_upload_root()
    try:
        from .image import image_variant
        large_rel = image_variant(clean, "large")
        if large_rel and (base / large_rel).is_file():
            return f"/static/uploads/{large_rel}"
    except Exception:
        pass
    return f"/static/uploads/{clean}"


def _product_gallery_urls(product: Product | None, root_path: Path | None = None) -> list[str]:
    if not product:
        return []
    base = root_path or _resolved_upload_root()
    urls: list[str] = []
    seen: set[str] = set()
    for name in (product.image_file or "").split("|"):
        fn = name.strip()
        if not fn or not _fast_image_exists(fn, base):
            continue
        u = _product_static_large_url(fn, base)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def _product_static_video_url(raw_video: Any) -> str:
    """Normalise sécuritairement Product.video_file vers /static/uploads/product_videos/<nom>."""
    path = str(raw_video or "").strip().replace("\\", "/")
    if (
        not path
        or len(path) > 512
        or path.startswith("//")
        or any(ord(ch) < 32 for ch in path)
        or any(ch in path for ch in ":%?#")
        or any(part in ("", ".", "..") for part in path.lstrip("/").split("/"))
    ):
        return ""
    static_prefixed = path.startswith(("/static/", "static/"))
    if path.startswith("/static/"):
        path = path[8:]
    elif path.startswith("static/"):
        path = path[7:]
    elif path.startswith("/"):
        return ""
    if path.startswith("uploads/product_videos/"):
        filename = path[len("uploads/product_videos/"):]
    elif path.startswith("product_videos/"):
        filename = path[len("product_videos/"):]
    elif "/" not in path and not static_prefixed:
        filename = path
    else:
        return ""
    if not filename or "/" in filename:
        return ""
    return f"/static/uploads/product_videos/{filename}"


def _rental_gallery_urls(listing: Any) -> list[str]:
    if not listing:
        return []
    roots = _rental_upload_roots()
    urls: list[str] = []
    seen: set[str] = set()
    media_items = sorted(getattr(listing, "media", []) or [], key=lambda m: getattr(m, "id", 0))
    for m in media_items:
        if getattr(m, "kind", "") != "image" or not getattr(m, "file_path", ""):
            continue
        rel = (m.file_path or "").replace("\\", "/")
        prefix = "uploads/rentals/"
        filename = rel[len(prefix):] if rel.startswith(prefix) else rel
        exists_on_disk = False
        for upload_root in roots:
            try:
                cand = (upload_root / filename).resolve()
                if cand.is_relative_to(upload_root) and cand.is_file():
                    exists_on_disk = True
                    break
            except (OSError, ValueError):
                continue
        if exists_on_disk:
            u = _rental_static_thumb_url(filename)
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def _rental_static_video_url(listing: Any) -> str:
    if not listing:
        return ""
    media_items = sorted(getattr(listing, "media", []) or [], key=lambda m: getattr(m, "id", 0))
    for m in media_items:
        if getattr(m, "kind", "") == "video" and getattr(m, "file_path", ""):
            return _rental_static_thumb_url(m.file_path)
    return ""


def _get_product_image_base64(product: Product | None) -> str:
    """Génère l'image avec filigrane en base64 (calibrée 1280px WhatsApp) uniquement au moment de l'envoi."""
    if not product:
        return ""
    try:
        images = [name.strip() for name in (product.image_file or "").split("|") if name.strip()]
        if not images:
            return ""
        upload_root = current_app.config.get("UPLOAD_FOLDER") or (Path(current_app.static_folder) / "uploads")
        from .image_download import watermarked_photo
        try:
            buf = watermarked_photo(upload_root, images[0], max_edge=1280, optimize=False)
            raw_bytes = buf.getvalue()
        except Exception as exc:
            current_app.logger.debug("watermark_fallback_raw pid=%s: %s", getattr(product, "id", None), exc)
            root = Path(upload_root).resolve()
            src = (root / images[0]).resolve()
            if src.is_relative_to(root) and src.is_file():
                raw_bytes = src.read_bytes()
            else:
                return ""
        if raw_bytes:
            return base64.b64encode(raw_bytes).decode("ascii")
    except Exception as exc:
        current_app.logger.warning("whatsapp_promo.image_base64_failed pid=%s: %s", getattr(product, "id", None), exc)
    return ""



def _pick_fair_random_products(
    candidates: list[Product],
    needed: int,
    promos: dict[int, Any],
) -> list[Product]:
    """Sélection aléatoire équitable : mélange promotions actives et autres produits du catalogue."""
    if needed <= 0 or not candidates:
        return []
    with_promo = [p for p in candidates if p.id in promos]
    without_promo = [p for p in candidates if p.id not in promos]
    random.shuffle(with_promo)
    random.shuffle(without_promo)

    if with_promo and without_promo and needed >= 2:
        promo_quota = min(len(with_promo), needed // 2)
        picked_promo = with_promo[:promo_quota]
        rem_promo = with_promo[promo_quota:]
        reg_quota = min(len(without_promo), needed - len(picked_promo))
        picked = picked_promo + without_promo[:reg_quota]
        if len(picked) < needed:
            picked.extend(rem_promo[: needed - len(picked)])
    else:
        picked = (with_promo + without_promo)[:needed]

    random.shuffle(picked)
    return picked


def select_daily_offers(
    settings: dict[str, Any],
    *,
    promoted: dict[str, str] | None = None,
    sent_ids_today: list[str] | set[str] | None = None,
    include_base64: bool = False,
) -> list[dict[str, Any]]:
    """Sélectionne un panier équilibré d'offres (par défaut 5 produits, 3 services, 2 locations)
    avec rotation aléatoire sur tout le catalogue et interdiction absolue de répétition le même jour.
    """
    promoted = promoted or {}
    today_iso = _today()
    cooldown_days = settings.get("cooldown_days", 7)
    pinned_ids = settings.get("pinned_product_ids") or []

    # Exclusion stricte de tout ID déjà diffusé aujourd'hui (matin vs soir)
    excluded_today: set[str] = {str(x) for x in (sent_ids_today or [])}
    for k, day in promoted.items():
        if str(day) == today_iso:
            excluded_today.add(str(k))

    prod_target = settings.get("products_count", 5)
    serv_target = settings.get("services_count", 3)
    rent_target = settings.get("rentals_count", 2)
    rent_max_hours = settings.get("rental_max_age_hours", 24)

    selected_cards: list[dict[str, Any]] = []
    seen_product_ids: set[int] = set()
    cutoff_date = (_local_now().date() - timedelta(days=cooldown_days)).isoformat()
    recent_keys = {str(pid) for pid, day in promoted.items() if str(day) > cutoff_date}
    recent_pids = {int(pid) for pid in recent_keys if pid.isdigit()}

    seen_rental_ids: set[int] = set()
    # 1. Coups de cœur épinglés par l'administrateur (Produits, Services ou Locations, sans doublon le même jour)
    if pinned_ids:
        int_pinned = [int(x) for x in pinned_ids if str(x).isdigit()]
        rent_pinned = [int(str(x).split("_", 1)[1]) for x in pinned_ids if str(x).startswith("rental_") and str(x)[7:].isdigit()]
        pinned_prod_map: dict[int, Product] = {}
        promos_pinned: dict[int, Any] = {}
        pinned_rent_map: dict[int, Any] = {}
        try:
            if int_pinned:
                pinned_query = (
                    Product.query
                    .outerjoin(Shop, Shop.id == Product.shop_id)
                    .options(selectinload(Product.shop), selectinload(Product.category))
                    .filter(Product.id.in_(int_pinned), Product.is_active.is_(True))
                    .all()
                )
                pinned_prod_map = {p.id: p for p in pinned_query}
                promos_pinned = get_active_promos_for_products(list(pinned_prod_map.keys()))
            if rent_pinned:
                from ..models.rental import RentalListing
                r_query = (
                    RentalListing.query
                    .outerjoin(Shop, Shop.id == RentalListing.shop_id)
                    .options(selectinload(RentalListing.shop), selectinload(RentalListing.media))
                    .filter(RentalListing.id.in_(rent_pinned), RentalListing.is_active.is_(True), RentalListing.status == "active")
                    .all()
                )
                pinned_rent_map = {r.id: r for r in r_query}
            for raw_pin in pinned_ids:
                s_pin = str(raw_pin)
                if s_pin in excluded_today:
                    continue
                if s_pin.startswith("rental_") and s_pin[7:].isdigit():
                    rid = int(s_pin[7:])
                    r_obj = pinned_rent_map.get(rid)
                    cur_rent = sum(1 for c in selected_cards if c.get("item_type") == "rental")
                    if r_obj and rid not in seen_rental_ids and cur_rent < max(1, rent_target) and _first_rental_image(r_obj)[0] > 0:
                        selected_cards.append(build_rental_card(r_obj, include_base64=include_base64))
                        seen_rental_ids.add(rid)
                elif s_pin.isdigit():
                    pid = int(s_pin)
                    p = pinned_prod_map.get(pid)
                    if not p or p.id in seen_product_ids:
                        continue
                    if p.kind == "physical" and (p.stock or 0) <= 0:
                        continue
                    cur_phys = sum(1 for c in selected_cards if c.get("item_type") == "physical")
                    cur_serv = sum(1 for c in selected_cards if c.get("item_type") == "service")
                    if p.kind == "physical" and cur_phys >= max(1, prod_target):
                        continue
                    if p.kind == "service" and cur_serv >= max(1, serv_target):
                        continue
                    first_img = _first_image(p)
                    if first_img and _image_exists(first_img):
                        selected_cards.append(build_product_card(p, promos_pinned.get(p.id), include_base64=include_base64))
                        seen_product_ids.add(p.id)
        except Exception:
            safe_session_rollback()

    pinned_prod_count = sum(1 for c in selected_cards if c.get("item_type") == "physical")
    pinned_serv_count = sum(1 for c in selected_cards if c.get("item_type") == "service")

    needed_prods = max(0, prod_target - pinned_prod_count)
    needed_servs = max(0, serv_target - pinned_serv_count)

    up_root = _resolved_upload_root()

    # 2. Sélection Produits Physiques (rotation aléatoire équitable + zéro répétition le même jour)
    if needed_prods > 0:
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
                .limit(250)
                .all()
            )
            valid = [
                p for p in candidates
                if p.id not in seen_product_ids
                and str(p.id) not in excluded_today
                and _fast_image_exists(_first_image(p), up_root)
            ]
            promos = get_active_promos_for_products([p.id for p in valid])
            fresh = [p for p in valid if p.id not in recent_pids]
            picked = _pick_fair_random_products(fresh, needed_prods, promos)
            if len(picked) < needed_prods:
                picked_ids = {p.id for p in picked}
                fallback_pool = [p for p in valid if p.id not in picked_ids]
                picked.extend(_pick_fair_random_products(fallback_pool, needed_prods - len(picked), promos))
            for p in picked:
                card = build_product_card(p, promos.get(p.id), include_base64=include_base64)
                selected_cards.append(card)
                seen_product_ids.add(p.id)
        except Exception:
            safe_session_rollback()

    # 3. Sélection Services (rotation aléatoire équitable + zéro répétition le même jour)
    if needed_servs > 0:
        try:
            candidates = (
                Product.query
                .outerjoin(Shop, Shop.id == Product.shop_id)
                .options(selectinload(Product.shop), selectinload(Product.category))
                .filter(Product.is_active.is_(True))
                .filter(or_(Product.shop_id.is_(None), Shop.is_active.is_(True)))
                .filter(Product.kind == "service")
                .filter(Product.image_file.isnot(None), Product.image_file != "")
                .order_by(Product.created_at.desc())
                .limit(200)
                .all()
            )
            valid = [
                p for p in candidates
                if p.id not in seen_product_ids
                and str(p.id) not in excluded_today
                and _fast_image_exists(_first_image(p), up_root)
            ]
            promos = get_active_promos_for_products([p.id for p in valid])
            fresh = [p for p in valid if p.id not in recent_pids]
            picked = _pick_fair_random_products(fresh, needed_servs, promos)
            if len(picked) < needed_servs:
                picked_ids = {p.id for p in picked}
                fallback_pool = [p for p in valid if p.id not in picked_ids]
                picked.extend(_pick_fair_random_products(fallback_pool, needed_servs - len(picked), promos))
            for p in picked:
                card = build_product_card(p, promos.get(p.id), include_base64=include_base64)
                selected_cards.append(card)
                seen_product_ids.add(p.id)
        except Exception:
            safe_session_rollback()

    pinned_rent_count = sum(1 for c in selected_cards if c.get("item_type") == "rental")
    needed_rents = max(0, rent_target - pinned_rent_count)

    # 4. Sélection Locations Immobilières (<= 24h en priorité, repli sur locations actives plus anciennes, sans doublon le même jour)
    if needed_rents > 0:
        try:
            from ..models.rental import RentalListing
            time_cutoff = datetime.utcnow() - timedelta(hours=rent_max_hours)
            query = (
                RentalListing.query
                .outerjoin(Shop, Shop.id == RentalListing.shop_id)
                .options(selectinload(RentalListing.shop), selectinload(RentalListing.media))
                .filter(RentalListing.is_active.is_(True), RentalListing.status == "active")
                .filter(or_(RentalListing.shop_id.is_(None), Shop.is_active.is_(True)))
                .order_by(RentalListing.created_at.desc())
                .limit(200)
                .all()
            )
            with_photos = [
                r for r in query
                if r.id not in seen_rental_ids
                and _first_rental_image(r)[0] > 0
                and f"rental_{r.id}" not in excluded_today
            ]
            r_recent_fresh = [
                r for r in with_photos
                if r.created_at and r.created_at >= time_cutoff and f"rental_{r.id}" not in recent_keys
            ]
            r_recent_cooled = [
                r for r in with_photos
                if r.created_at and r.created_at >= time_cutoff and f"rental_{r.id}" in recent_keys
            ]
            r_older_fresh = [
                r for r in with_photos
                if not (r.created_at and r.created_at >= time_cutoff) and f"rental_{r.id}" not in recent_keys
            ]
            r_older_cooled = [
                r for r in with_photos
                if not (r.created_at and r.created_at >= time_cutoff) and f"rental_{r.id}" in recent_keys
            ]
            for bucket in (r_recent_fresh, r_recent_cooled, r_older_fresh, r_older_cooled):
                random.shuffle(bucket)
            picked_rentals = (r_recent_fresh + r_recent_cooled + r_older_fresh + r_older_cooled)[:needed_rents]
            for r in picked_rentals:
                selected_cards.append(build_rental_card(r, include_base64=include_base64))
                seen_rental_ids.add(r.id)
        except Exception as exc:
            safe_session_rollback()
            current_app.logger.warning("whatsapp_promo.select_rentals_failed: %s", exc)

    # 5. Complément automatique jusqu'au quota total (ex: 10 offres) si une catégorie a moins de stock actif
    total_target = prod_target + serv_target + rent_target
    shortfall = total_target - len(selected_cards)
    if shortfall > 0:
        try:
            extra_candidates = (
                Product.query
                .outerjoin(Shop, Shop.id == Product.shop_id)
                .options(selectinload(Product.shop), selectinload(Product.category))
                .filter(Product.is_active.is_(True))
                .filter(or_(Product.shop_id.is_(None), Shop.is_active.is_(True)))
                .filter(or_(Product.kind == "service", Product.stock > 0))
                .filter(Product.image_file.isnot(None), Product.image_file != "")
                .order_by(Product.created_at.desc())
                .limit(250)
                .all()
            )
            extra_valid = [
                p for p in extra_candidates
                if p.id not in seen_product_ids
                and str(p.id) not in excluded_today
                and _fast_image_exists(_first_image(p), up_root)
            ]
            if extra_valid:
                promos_extra = get_active_promos_for_products([p.id for p in extra_valid])
                fresh_extra = [p for p in extra_valid if p.id not in recent_pids]
                picked_extra = _pick_fair_random_products(fresh_extra, shortfall, promos_extra)
                if len(picked_extra) < shortfall:
                    picked_extra_ids = {p.id for p in picked_extra}
                    rem_pool = [p for p in extra_valid if p.id not in picked_extra_ids]
                    picked_extra.extend(_pick_fair_random_products(rem_pool, shortfall - len(picked_extra), promos_extra))
                for p in picked_extra:
                    selected_cards.append(build_product_card(p, promos_extra.get(p.id), include_base64=include_base64))
                    seen_product_ids.add(p.id)
        except Exception:
            safe_session_rollback()

    return selected_cards


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



def _rental_upload_roots() -> list[Path]:
    roots: list[Path] = []
    cfg_root = current_app.config.get("UPLOAD_FOLDER")
    if cfg_root:
        roots.append((Path(cfg_root) / "rentals").resolve())
    if current_app.static_folder:
        st_root = (Path(current_app.static_folder) / "uploads" / "rentals").resolve()
        if st_root not in roots:
            roots.append(st_root)
    return roots


def _first_rental_image_with_root(listing: Any) -> tuple[int, str, Path | None]:
    """Trouve le premier média image d'une location qui existe réellement sur disque."""
    roots = _rental_upload_roots()
    for m in getattr(listing, "media", []) or []:
        if getattr(m, "kind", "") == "image" and getattr(m, "file_path", ""):
            rel = (m.file_path or "").replace("\\", "/")
            prefix = "uploads/rentals/"
            filename = rel[len(prefix):] if rel.startswith(prefix) else rel
            for upload_root in roots:
                try:
                    candidate = (upload_root / filename).resolve()
                    if candidate.is_relative_to(upload_root) and candidate.is_file():
                        return m.id, filename, upload_root
                except (OSError, ValueError):
                    continue
    return 0, "", None


def _first_rental_image(listing: Any) -> tuple[int, str]:
    media_id, filename, _ = _first_rental_image_with_root(listing)
    return media_id, filename


def _get_rental_image_base64(listing: Any) -> str:
    """Génère l'image avec filigrane en base64 pour une location immobilière."""
    if not listing:
        return ""
    try:
        media_id, img_filename, upload_root = _first_rental_image_with_root(listing)
        if not media_id or not img_filename or upload_root is None:
            return ""
        from .image_download import watermarked_photo
        try:
            buf = watermarked_photo(upload_root, img_filename, max_edge=1280, optimize=False)
            raw_bytes = buf.getvalue()
        except Exception as exc:
            current_app.logger.debug("watermark_fallback_raw rental_id=%s: %s", getattr(listing, "id", None), exc)
            src = (upload_root / img_filename).resolve()
            if src.is_relative_to(upload_root) and src.is_file():
                raw_bytes = src.read_bytes()
            else:
                return ""
        if raw_bytes:
            return base64.b64encode(raw_bytes).decode("ascii")
    except Exception as exc:
        current_app.logger.warning("whatsapp_promo.rental_image_b64_failed id=%s: %s", getattr(listing, "id", None), exc)
    return ""


def build_rental_card(listing: Any, *, include_base64: bool = True) -> dict[str, Any]:
    base = _public_base_url()
    page = f"{base}/l/{listing.id}"
    rent_dh = float(getattr(listing, "rent_cents", 0) or 0) / 100.0
    period = "mois" if getattr(listing, "listing_type", "monthly") == "monthly" else "jour"
    price_line = f"💰 {_format_dh(rent_dh)} DH / {period}"

    media_id, img_filename = _first_rental_image(listing)
    has_image = bool(media_id and img_filename)
    image_url = f"{base}/location/{listing.slug}/photo/{media_id}/download" if has_image else ""
    thumb_url = _rental_static_thumb_url(img_filename) if has_image else ""
    gallery_urls = _rental_gallery_urls(listing)
    if not gallery_urls and thumb_url:
        gallery_urls = [thumb_url]
    video_url = _rental_static_video_url(listing)
    slug_val = getattr(listing, "slug", "") or ""
    public_url = f"/location/{slug_val}" if slug_val else f"/l/{listing.id}?preview=1"
    image_b64 = _get_rental_image_base64(listing) if (has_image and include_base64) else ""

    shop_name = getattr(getattr(listing, "shop", None), "name", "") or "Baba Market Immo"
    city = getattr(listing, "city", "") or ""
    area = getattr(listing, "area", "") or ""
    city_area = f"{city} - {area}" if (city and area) else (city or area or "Maroc")

    prop_type = getattr(listing, "property_type", "apartment")
    type_labels = {
        "apartment": "Appartement",
        "studio": "Studio",
        "room": "Chambre",
        "store": "Magasin / Local commercial",
    }
    cat_label = f"Location {type_labels.get(prop_type, str(prop_type).capitalize())}"

    return {
        "id": f"rental_{listing.id}",
        "raw_id": listing.id,
        "item_type": "rental",
        "name": listing.title,
        "description": " ".join(str(listing.description or "").split())[:300],
        "shop": shop_name,
        "category": cat_label,
        "city": city_area,
        "price": rent_dh,
        "old_price": None,
        "price_line": price_line,
        "page_url": page,
        "public_url": public_url,
        "image_url": image_url,
        "thumb_url": thumb_url,
        "gallery_urls": gallery_urls,
        "video_url": video_url,
        "has_video": bool(video_url),
        "image_base64": image_b64,
        "has_image": has_image,
    }


def build_product_card(product: Product, promo=None, *, include_base64: bool = True) -> dict[str, Any]:
    final = float(prix_final(product, promo))
    base_price = float(product.price or 0)
    base = _public_base_url()
    page = f"{base}/p/{product.id}"
    first_img = _first_image(product)
    up_root = _resolved_upload_root()
    has_image = bool(first_img and _fast_image_exists(first_img, up_root))
    image = f"{base}/shop/product/{product.id}/photo/0/download" if has_image else ""
    thumb_url = _product_static_thumb_url(first_img, up_root) if has_image else ""
    gallery_urls = _product_gallery_urls(product, up_root) if has_image else []
    if not gallery_urls and thumb_url:
        gallery_urls = [thumb_url]
    video_url = _product_static_video_url(getattr(product, "video_file", ""))
    public_url = f"/shop/product/{product.id}"
    image_b64 = _get_product_image_base64(product) if (has_image and include_base64) else ""
    shop_name = getattr(product.shop, "name", "") or ""
    category = getattr(getattr(product, "category", None), "name", "") or ""
    item_kind = getattr(product, "kind", "physical") or "physical"
    return {
        "id": product.id,
        "name": product.name,
        "item_type": item_kind,
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
        "public_url": public_url,
        "image_url": image,
        "thumb_url": thumb_url,
        "gallery_urls": gallery_urls,
        "video_url": video_url,
        "has_video": bool(video_url),
        "image_base64": image_b64,
        "has_image": has_image,
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
    item_type = card.get("item_type") or "physical"
    if item_type == "rental":
        city = f" à {card.get('city')}" if card.get("city") else ""
        return {
            "status": f"🏠 {card['name']}{city} disponible !",
            "message": f"Logement propre et bien situé{city}, disponible immédiatement pour visite.",
        }
    if item_type == "service":
        return {
            "status": f"🛠️ {card['name']}{shop} disponible !",
            "message": f"Service de qualité réalisé par des professionnels compétents et fiables.",
        }
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
            headers={"x-goog-api-key": api_key}, json=payload, timeout=(2.5, 8),
        )
        if response.status_code != 200:
            current_app.logger.info("whatsapp_promo.gemini_failed status=%s", response.status_code)
            return fallback, "fallback"
        parts = response.json()["candidates"][0]["content"]["parts"]
        parsed = json.loads("".join(part.get("text", "") for part in parts if not part.get("thought")))
        result = dict(fallback)
        for item in parsed.get("items", []) if isinstance(parsed, dict) else []:
            raw_id = item.get("id")
            matched_key = None
            for k in result.keys():
                if str(k) == str(raw_id):
                    matched_key = k
                    break
            if matched_key is None:
                continue
            status = _sanitize_copy(item.get("status"), 120)
            message = _sanitize_copy(item.get("message"), 400)
            result[matched_key] = {
                "status": status or fallback[matched_key]["status"],
                "message": message or fallback[matched_key]["message"],
            }
        return result, "gemini"
    except Exception as exc:
        current_app.logger.info("whatsapp_promo.gemini_fallback reason=%s", type(exc).__name__)
        return fallback, "fallback"


def compose_status_caption(card: dict[str, Any], copy: dict[str, str]) -> str:
    """Légende pour le Statut WhatsApp 24h."""
    if copy.get("custom_full_status_caption"):
        return str(copy["custom_full_status_caption"]).strip()
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
    """Message destiné aux Groupes de vente WhatsApp (dynamique, rassurant, SANS lien d'invitation)."""
    if copy.get("custom_full_group_message"):
        return str(copy["custom_full_group_message"]).strip()
    clean_grp = (group_label or "").strip()
    if (
        clean_grp.startswith("http://")
        or clean_grp.startswith("https://")
        or "whatsapp.com" in clean_grp.lower()
        or "@g.us" in clean_grp.lower()
        or clean_grp.lower() in ("groupe", "group", "whatsapp")
    ):
        clean_grp = ""

    item_type = card.get("item_type") or "physical"
    
    if item_type == "rental":
        header = f"🏠 *Nouveau Logement disponible {clean_grp}*".strip() if clean_grp else "🏠 *Nouveau Logement disponible*"
        city_part = f" à *{card.get('city', '')}*" if card.get("city") else ""
        item_line = f"✨ *{card['name']}*{city_part}"
        reassurance = "🏠 Logement vérifié • 📍 Quartier recherché"
        cta = f"👉 Voir les photos & Contacter : {_tracked(card.get('page_url', ''), 'group')}"
    elif item_type == "service":
        header = f"🛠️ *Service recommandé {clean_grp}*".strip() if clean_grp else "🛠️ *Service professionnel recommandé*"
        shop_part = f" chez *{card['shop']}*" if card.get("shop") else ""
        item_line = f"🌟 *{card['name']}*{shop_part}"
        reassurance = "🛠️ Prestataire vérifié • 🤝 Contact direct"
        cta = f"👉 Découvrir le service en 1 clic : {_tracked(card.get('page_url', ''), 'group')}"
    else:
        header = f"📢 *Offre spéciale {clean_grp}*".strip() if clean_grp else "📢 *Offre du jour Baba Market*"
        shop_part = f" chez *{card['shop']}*" if card.get("shop") else ""
        item_line = f"🌟 *{card['name']}*{shop_part}"
        reassurance = "🚚 Livraison rapide • 💵 Paiement à la livraison"
        cta = f"👉 Voir & Commander en 1 clic : {_tracked(card.get('page_url', ''), 'group')}"

    if copy.get("is_custom") and copy.get("custom_group_message"):
        body_text = _clean_body_text(copy["custom_group_message"])
    else:
        body_text = _clean_body_text(copy.get("group_message") or copy.get("message") or copy.get("status") or "")

    parts = [header, item_line]
    if body_text:
        parts.append(body_text)
    if card.get("price_line"):
        parts.append(card["price_line"])

    parts.append(reassurance)
    parts.append(cta)
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
    """Met à jour manuellement les textes générés pour un produit, un service ou une location."""
    target_pid = str(product_id or "").strip()
    if not target_pid:
        return None

    log = get_log() or {}
    last_gen = log.get("last_generated")
    if not last_gen or not isinstance(last_gen, dict):
        return None

    items = list(last_gen.get("items") or last_gen.get("products") or [])
    found = False
    for item in items:
        if str(item.get("id")) == target_pid or str(item.get("product_id")) == target_pid:
            if status_caption is not None:
                clean_st = status_caption.strip()
                item["status_caption"] = clean_st
                item["custom_full_status_caption"] = clean_st
                item["is_custom"] = True
                item["manually_edited"] = True
            if group_message is not None:
                clean_gr = group_message.strip()
                item["group_message"] = clean_gr
                item["group_message_sample"] = clean_gr
                item["custom_full_group_message"] = clean_gr
                item["is_custom"] = True
                item["manually_edited"] = True
            if direct_message is not None:
                item["direct_message"] = direct_message.strip()
            found = True
            break

    if not found:
        return None

    last_gen["items"] = items
    last_gen["products"] = items
    last_gen["manually_edited"] = True
    log["last_generated"] = last_gen
    _save_promo_log(log)
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


def _ensure_card_image_base64(card: dict[str, Any]) -> str:
    image_b64 = card.get("image_base64") or ""
    if image_b64:
        return image_b64
    if card.get("id"):
        try:
            cid = str(card["id"])
            if cid.startswith("rental_"):
                rid = int(cid.split("_", 1)[1])
                from ..models.rental import RentalListing
                listing = db.session.get(RentalListing, rid)
                if listing:
                    image_b64 = _get_rental_image_base64(listing)
            elif cid.isdigit():
                prod = db.session.get(Product, int(cid))
                if prod:
                    image_b64 = _get_product_image_base64(prod)
        except Exception:
            safe_session_rollback()
        if image_b64:
            card["image_base64"] = image_b64
    return image_b64


def post_status(card: dict[str, Any], caption: str, audience: list[str]) -> tuple[bool, str]:
    image_b64 = _ensure_card_image_base64(card)

    code, body = _gateway_post("/api/promo/status", {
        "image_url": card.get("image_url", ""),
        "image_base64": image_b64 or "",
        "has_image": bool(image_b64 or card.get("image_url")),
        "caption": caption,
        "status_jid_list": audience,
    })
    return code in (200, 201), str(body.get("error") or code)


def send_promo_media(target: str, card: dict[str, Any], text: str) -> tuple[str, str]:
    """Envoie une photo + texte vers un numéro client ou un groupe WhatsApp.
    Retourne (résultat, détail) : sent | opted_out | not_on_whatsapp | failed
    """
    image_b64 = _ensure_card_image_base64(card)

    payload = {
        "target": target,
        "phone": target,
        "image_url": card.get("image_url", ""),
        "image_base64": image_b64 or "",
        "has_image": bool(image_b64 or card.get("image_url")),
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


def _current_slot_key(today: str) -> str:
    current_hour = _local_now().hour
    slot_name = "matin" if current_hour < 14 else "soir"
    return f"{today}_{slot_name}"


def _is_daily_slot_claimed(today: str) -> bool:
    try:
        from ..models.runtime_state import RuntimeState
        row = RuntimeState.query.filter_by(state_key=LOG_KEY).first()
        log = json.loads(row.value_json) if row and row.value_json else {}
        return log.get("last_run_slot") == _current_slot_key(today)
    except Exception:
        safe_session_rollback()
        return False


def _claim_daily_run(today: str, force: bool) -> bool:
    """Verrou bi-quotidien (matin / soir) pour éviter les doubles envois sur le même créneau."""
    try:
        from ..models.runtime_state import RuntimeState
        row = RuntimeState.query.filter_by(state_key=LOG_KEY).first()
        now = datetime.utcnow()
        log = json.loads(row.value_json) if row and row.value_json else {}
        slot_key = _current_slot_key(today)
        if log.get("last_run_slot") == slot_key and not force:
            return False
        log["last_run_date"] = today
        log["last_run_slot"] = slot_key
        log["history_date"] = today
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
    promoted_ids: list[int | str],
    sent_today: int,
    today: str,
    preview: bool,
    last_generated: dict[str, Any] | None = None,
    new_recent_logs: list[dict[str, Any]] | None = None,
) -> None:
    current_log = get_log() or {}
    if not isinstance(current_log, dict):
        current_log = {}

    current_log["history_date"] = today

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

        sent_ids_map = {today: list((current_log.get("sent_ids_by_date") or {}).get(today) or [])}
        existing_sent = {str(x) for x in sent_ids_map[today]}
        for pid in promoted_ids:
            s_pid = str(pid)
            if s_pid not in existing_sent:
                sent_ids_map[today].append(s_pid)
                existing_sent.add(s_pid)
        current_log["sent_ids_by_date"] = sent_ids_map

        sent_by_date = {today: int((current_log.get("sent_by_date") or {}).get(today, 0)) + sent_today}
        current_log["sent_by_date"] = sent_by_date
        statuses_sent = int(summary.get("statuses_ok") or 0)
        statuses_by_date = {today: int((current_log.get("statuses_by_date") or {}).get(today, 0)) + statuses_sent}
        current_log["statuses_by_date"] = statuses_by_date

    cleaned, _ = _clean_and_expire_log(current_log)
    _persist_json_state(LOG_KEY, cleaned)


def _compute_group_step_delay_range(min_delay: int, max_delay: int, groups_count: int) -> tuple[float, float]:
    """Adapte le délai entre chaque envoi selon le nombre de groupes actifs :
    - 1 seul groupe : conserve intégralement [min_delay, max_delay] (ex: 45s à 90s).
    - Plusieurs groupes (alternance Round-Robin) : répartit le délai entre les groupes
      (ex: 3 groupes -> 15s à 30s entre chaque groupe, soit toujours 45s à 90s d'écart dans un même groupe),
      avec un plancher de sécurité de 15s entre deux groupes distincts.
    """
    n = max(1, int(groups_count or 1))
    if n == 1:
        return float(min_delay), float(max_delay)
    step_min = max(MIN_INTER_GROUP_STEP, float(min_delay) / n)
    step_max = max(step_min + 5.0, float(max_delay) / n)
    return step_min, step_max


def _select_balanced_status_cards(cards: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Sélectionne `limit` offres variées (Produits, Services, Locations) et les alterne pour la Story 24h."""
    if limit <= 0 or not cards:
        return []
    if len(cards) <= limit:
        return list(cards)

    buckets: list[list[dict[str, Any]]] = []
    for kind in ("physical", "service", "rental"):
        group = [c for c in cards if c.get("item_type") == kind]
        if group:
            buckets.append(group)
    other = [c for c in cards if c.get("item_type") not in ("physical", "service", "rental")]
    if other:
        buckets.append(other)

    if len(buckets) <= 1:
        return list(cards[:limit])

    total = len(cards)
    quotas = [0] * len(buckets)
    remainders: list[tuple[float, int]] = []
    for idx, b in enumerate(buckets):
        exact = (len(b) * limit) / total
        base = min(len(b), max(1, int(exact))) if limit >= len(buckets) else int(exact)
        quotas[idx] = base
        remainders.append((exact - int(exact), idx))

    while sum(quotas) > limit:
        # Réduire le bucket ayant le plus grand quota (> 1)
        idx_max = max(range(len(quotas)), key=lambda i: quotas[i])
        if quotas[idx_max] <= 1:
            break
        quotas[idx_max] -= 1

    remainders.sort(reverse=True)
    while sum(quotas) < limit:
        progressed = False
        for _, idx in remainders:
            if sum(quotas) >= limit:
                break
            if quotas[idx] < len(buckets[idx]):
                quotas[idx] += 1
                progressed = True
        if not progressed:
            break

    sliced_buckets = [buckets[i][: quotas[i]] for i in range(len(buckets)) if quotas[i] > 0]
    interleaved: list[dict[str, Any]] = []
    max_len = max((len(b) for b in sliced_buckets), default=0)
    for pos in range(max_len):
        for b in sliced_buckets:
            if pos < len(b):
                interleaved.append(b[pos])
    return interleaved[:limit]


def _offer_selection_signature(settings: dict[str, Any]) -> str:
    """Signature déterministe des paramètres de sélection (nombre d'offres, fraîcheur locations, épinglés)."""
    pinned = ",".join(str(x) for x in (settings.get("pinned_product_ids") or []))
    return (
        f"p={settings.get('products_count', 5)}|"
        f"s={settings.get('services_count', 3)}|"
        f"r={settings.get('rentals_count', 2)}|"
        f"age={settings.get('rental_max_age_hours', 24)}|"
        f"pin={pinned}"
    )


def _compute_per_wave_status_limit(
    settings: dict[str, Any],
    log: dict[str, Any],
    today: str,
    *,
    preview: bool,
) -> int:
    total_daily_status_target = int(settings.get("status_products", 12))
    if total_daily_status_target >= 4:
        half_quota = (total_daily_status_target + 1) // 2
        if preview:
            return half_quota
        already_posted_statuses = int((log.get("statuses_by_date") or {}).get(today, 0))
        remaining_daily_statuses = max(0, total_daily_status_target - already_posted_statuses)
        return min(half_quota, remaining_daily_statuses)
    return total_daily_status_target


def get_wave_info(
    settings: dict[str, Any] | None = None,
    log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Détermine l'état exact des vagues d'envoi du jour (Vague 1 Matin -> Vague 2 Soir)."""
    st = settings or get_settings()
    lg = log if log is not None else get_log()
    today = _today()
    runs = lg.get("runs") or []
    completed_runs_today = sum(
        1
        for r in runs
        if isinstance(r, dict)
        and r.get("mode") == "live"
        and str(r.get("started_at") or "").startswith(today)
        and (
            r.get("aborted") is None
            or (int(r.get("statuses_ok") or 0) + int(r.get("groups_ok") or 0)) > 0
        )
    )
    active_send = lg.get("active_send") if isinstance(lg.get("active_send"), dict) else None
    if active_send and not _is_within_persistence_window(active_send.get("started_at")):
        active_send = None

    sched1 = st.get("schedule_time", "10:30")
    sched2 = st.get("schedule_time_2", "18:30")
    if completed_runs_today == 0:
        wave_number = 1
        wave_code = "morning"
        wave_title = "Vague 1 — Matin"
        wave_icon = "☀️"
        scheduled_at = sched1
        all_waves_done = False
    elif completed_runs_today == 1:
        wave_number = 2
        wave_code = "evening"
        wave_title = "Vague 2 — Soir"
        wave_icon = "🌙"
        scheduled_at = sched2
        all_waves_done = False
    else:
        wave_number = completed_runs_today + 1
        wave_code = "extra"
        wave_title = "2/2 Vagues du jour diffusées (Aperçu bonus)"
        wave_icon = "✅"
        scheduled_at = sched2
        all_waves_done = True

    return {
        "today": today,
        "runs_today": completed_runs_today,
        "wave_number": wave_number,
        "wave_code": wave_code,
        "wave_title": wave_title,
        "wave_icon": wave_icon,
        "scheduled_at": scheduled_at,
        "schedule_time_1": sched1,
        "schedule_time_2": sched2,
        "all_waves_done": all_waves_done,
        "is_sending": bool(active_send),
        "active_send": active_send,
    }


def _build_wave_items_and_meta(
    cards: list[dict[str, Any]],
    copies: dict[Any, dict[str, Any]],
    source: str,
    settings: dict[str, Any],
    log: dict[str, Any],
    today: str,
    *,
    preview: bool,
    consumed: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    per_run_status_limit = _compute_per_wave_status_limit(settings, log, today, preview=preview)
    status_cards = _select_balanced_status_cards(cards, per_run_status_limit)
    status_id_set = {str(c["id"]) for c in status_cards}
    wave = get_wave_info(settings, log)

    items_data = []
    for idx, c in enumerate(cards):
        cid = c["id"]
        cp = copies.get(cid) or {}
        in_status = bool(settings.get("status_enabled", True) and str(cid) in status_id_set)
        items_data.append({
            "order_index": idx + 1,
            "id": cid,
            "raw_id": c.get("raw_id", cid),
            "product_id": cid,
            "item_type": c.get("item_type", "physical"),
            "name": c["name"],
            "title": c["name"],
            "shop": c["shop"],
            "shop_name": c["shop"],
            "category": c.get("category", "") or "",
            "city": c.get("city", "") or "",
            "shop_city": c.get("city") or c.get("category", "") or "",
            "price": c.get("price", 0),
            "price_dh": str(c.get("price", 0)),
            "old_price": c.get("old_price"),
            "old_price_dh": str(c.get("old_price")) if c.get("old_price") else "",
            "price_line": c["price_line"],
            "image_url": c["image_url"],
            "thumb_url": c.get("thumb_url") or "",
            "gallery_urls": list(c.get("gallery_urls") or ([c["thumb_url"]] if c.get("thumb_url") else [])),
            "video_url": c.get("video_url") or "",
            "has_video": bool(c.get("video_url")),
            "has_image": bool(c.get("has_image", bool(c.get("image_url")))),
            "page_url": c["page_url"],
            "public_url": c.get("public_url") or c["page_url"],
            "product_url": c["page_url"],
            "in_status": in_status,
            "in_groups": bool(settings.get("groups_enabled", True)),
            "status_caption": compose_status_caption(c, cp),
            "group_message": compose_group_message(c, cp),
            "group_message_sample": compose_group_message(c, cp),
            "ai_status": cp.get("status", ""),
            "ai_message": cp.get("message", ""),
            "is_custom": bool(cp.get("is_custom")),
            "manually_edited": bool(cp.get("manually_edited") or cp.get("is_custom")),
            "custom_full_status_caption": cp.get("custom_full_status_caption", ""),
            "custom_full_group_message": cp.get("custom_full_group_message", ""),
            "direct_message": compose_message(c, cp, ""),
        })

    last_generated_data = {
        "generated_at": f"{today} {_local_now().strftime('%H:%M:%S')}",
        "date": today,
        "time": _local_now().strftime("%H:%M:%S"),
        "source": source,
        "copy_source": source,
        "dry_run": preview,
        "consumed": consumed,
        "wave_number": wave["wave_number"],
        "wave_code": wave["wave_code"],
        "wave_title": wave["wave_title"],
        "wave_icon": wave["wave_icon"],
        "scheduled_at": wave["scheduled_at"],
        "selection_sig": _offer_selection_signature(settings),
        "status_count_planned": sum(1 for it in items_data if it["in_status"]),
        "items": items_data,
        "products": items_data,
    }
    return items_data, last_generated_data, status_cards


def _backfill_missing_thumb_urls(items: list[dict[str, Any]]) -> bool:
    """Complète instantanément thumb_url, gallery_urls, video_url et public_url sur les lots déjà en cache."""
    def _needs_enrich(entry: dict[str, Any]) -> bool:
        return (
            not entry.get("thumb_url")
            or "gallery_urls" not in entry
            or "video_url" not in entry
            or not entry.get("public_url")
        )

    missing_pids = [int(it["id"]) for it in items if _needs_enrich(it) and str(it.get("id", "")).isdigit()]
    missing_rids = [
        int(str(it["id"])[7:])
        for it in items
        if _needs_enrich(it) and str(it.get("id", "")).startswith("rental_") and str(it["id"])[7:].isdigit()
    ]
    if not missing_pids and not missing_rids:
        return False
    changed = False
    up_root = _resolved_upload_root()
    try:
        prod_map = {p.id: p for p in Product.query.filter(Product.id.in_(missing_pids)).all()} if missing_pids else {}
        rent_map: dict[int, Any] = {}
        if missing_rids:
            from ..models.rental import RentalListing
            rent_map = {
                r.id: r
                for r in RentalListing.query.options(selectinload(RentalListing.media)).filter(RentalListing.id.in_(missing_rids)).all()
            }
        for it in items:
            if not _needs_enrich(it):
                continue
            sid = str(it.get("id") or "")
            if sid.isdigit() and int(sid) in prod_map:
                prod_obj = prod_map[int(sid)]
                fn = _first_image(prod_obj)
                if fn and not it.get("thumb_url"):
                    it["thumb_url"] = _product_static_thumb_url(fn, up_root)
                gal = _product_gallery_urls(prod_obj, up_root)
                if not gal and it.get("thumb_url"):
                    gal = [it["thumb_url"]]
                it["gallery_urls"] = gal
                vid = _product_static_video_url(getattr(prod_obj, "video_file", ""))
                it["video_url"] = vid
                it["has_video"] = bool(vid)
                it["public_url"] = f"/shop/product/{prod_obj.id}"
                changed = True
            elif sid.startswith("rental_") and sid[7:].isdigit() and int(sid[7:]) in rent_map:
                rent_obj = rent_map[int(sid[7:])]
                _, r_fn = _first_rental_image(rent_obj)
                if r_fn and not it.get("thumb_url"):
                    it["thumb_url"] = _rental_static_thumb_url(r_fn)
                gal = _rental_gallery_urls(rent_obj)
                if not gal and it.get("thumb_url"):
                    gal = [it["thumb_url"]]
                it["gallery_urls"] = gal
                vid = _rental_static_video_url(rent_obj)
                it["video_url"] = vid
                it["has_video"] = bool(vid)
                slug_val = getattr(rent_obj, "slug", "") or ""
                it["public_url"] = f"/location/{slug_val}" if slug_val else f"/l/{rent_obj.id}?preview=1"
                changed = True
    except Exception:
        safe_session_rollback()
    return changed


def prepare_wave_preview(*, force: bool = False, use_ai: bool = True) -> dict[str, Any]:
    """Prépare silencieusement les offres de la vague courante (Matin ou Soir) dans last_generated
    sans polluer l'Historique des envois (recent_logs). Si use_ai=False, répond en <30ms sans appel réseau."""
    settings = get_settings()
    today = _today()
    log = get_log()
    sent_ids_today = list((log.get("sent_ids_by_date") or {}).get(today) or [])
    cards = select_daily_offers(
        settings,
        promoted=log.get("promoted") or {},
        sent_ids_today=sent_ids_today,
    )
    if not cards:
        return {}
    if use_ai:
        copies, source = generate_copy(cards)
    else:
        copies = {card["id"]: _fallback_copy(card) for card in cards}
        source = "fallback"
    _, last_generated_data, _ = _build_wave_items_and_meta(
        cards, copies, source, settings, log, today, preview=True, consumed=False
    )
    fresh_log = get_log()
    fresh_log["history_date"] = today
    fresh_log["last_generated"] = last_generated_data
    _save_promo_log(fresh_log)
    return last_generated_data


def enrich_wave_ai_in_background(app) -> None:
    """Enrichit en tâche de fond les textes IA Gemini du lot affiché sans jamais bloquer le chargement de la page."""
    if getattr(app, "testing", False) or app.config.get("TESTING"):
        return
    api_key = str(app.config.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return
    import threading

    def _worker() -> None:
        with app.app_context():
            try:
                log = get_log()
                lg = log.get("last_generated") or {}
                items = list(lg.get("items") or [])
                if not items or lg.get("consumed") or lg.get("source") == "gemini" or lg.get("manually_edited"):
                    return
                gen_stamp = lg.get("generated_at")
                cards_payload = [
                    {
                        "id": it["id"],
                        "name": it.get("name") or it.get("title") or "",
                        "item_type": it.get("item_type", "physical"),
                        "description": it.get("name") or "",
                        "shop": it.get("shop") or "",
                        "category": it.get("category") or "",
                        "city": it.get("city") or "",
                        "price_line": it.get("price_line") or "",
                        "page_url": it.get("page_url") or "",
                    }
                    for it in items
                ]
                copies, source = generate_copy(cards_payload)
                if source != "gemini":
                    return
                fresh = get_log()
                cur_lg = fresh.get("last_generated") or {}
                if cur_lg.get("generated_at") != gen_stamp or cur_lg.get("consumed") or cur_lg.get("manually_edited"):
                    return
                for it in cur_lg.get("items") or []:
                    if it.get("is_custom") or it.get("manually_edited"):
                        continue
                    cp = copies.get(it["id"])
                    if not cp:
                        continue
                    it["ai_status"] = cp.get("status", "")
                    it["ai_message"] = cp.get("message", "")
                    it["status_caption"] = compose_status_caption(it, cp)
                    it["group_message"] = compose_group_message(it, cp)
                    it["group_message_sample"] = it["group_message"]
                cur_lg["source"] = "gemini"
                cur_lg["copy_source"] = "gemini"
                cur_lg["products"] = cur_lg.get("items") or []
                fresh["last_generated"] = cur_lg
                _save_promo_log(fresh)
            except Exception:
                safe_session_rollback()
            finally:
                db.session.remove()

    threading.Thread(target=_worker, daemon=True).start()


def ensure_current_wave_preview(*, force_regenerate: bool = False, use_ai: bool = False) -> dict[str, Any]:
    """Garantit que la page admin affiche toujours instantanément la vague active (les 10 offres du Matin,
    puis automatiquement les 10 nouvelles offres du Soir dès que le Matin est parti, ou mises à jour
    dès qu'un quota de l'Étape 3 est modifié)."""
    settings = get_settings()
    today = _today()
    log = get_log()
    wave = get_wave_info(settings, log)
    last_gen = log.get("last_generated") or {}
    items = list(last_gen.get("items") or last_gen.get("products") or [])
    sent_today_set = {str(x) for x in ((log.get("sent_ids_by_date") or {}).get(today) or [])}
    expected_sig = _offer_selection_signature(settings)

    is_valid = (
        not force_regenerate
        and bool(items)
        and last_gen.get("date") == today
        and bool(last_gen.get("dry_run"))
        and not bool(last_gen.get("consumed"))
        and last_gen.get("selection_sig") == expected_sig
        and int(last_gen.get("wave_number") or 1) == wave["wave_number"]
        and all(str(it.get("id")) not in sent_today_set for it in items)
    )
    if is_valid:
        per_run_limit = _compute_per_wave_status_limit(settings, log, today, preview=True)
        pseudo_cards = [{"id": it["id"], "item_type": it.get("item_type", "physical")} for it in items]
        st_ids = {str(c["id"]) for c in _select_balanced_status_cards(pseudo_cards, per_run_limit)}
        updated_meta = _backfill_missing_thumb_urls(items)
        for it in items:
            want_st = bool(settings.get("status_enabled", True) and str(it["id"]) in st_ids)
            want_gr = bool(settings.get("groups_enabled", True))
            if it.get("in_status") != want_st or it.get("in_groups") != want_gr:
                it["in_status"] = want_st
                it["in_groups"] = want_gr
                updated_meta = True
        if last_gen.get("scheduled_at") != wave["scheduled_at"] or last_gen.get("wave_title") != wave["wave_title"]:
            last_gen["scheduled_at"] = wave["scheduled_at"]
            last_gen["wave_title"] = wave["wave_title"]
            last_gen["wave_icon"] = wave["wave_icon"]
            updated_meta = True
        if updated_meta:
            last_gen["status_count_planned"] = sum(1 for it in items if it.get("in_status"))
            last_gen["items"] = items
            last_gen["products"] = items
            log["last_generated"] = last_gen
            _save_promo_log(log)
        return last_gen

    return prepare_wave_preview(force=True, use_ai=use_ai)


def run_daily_promo(
    *,
    force: bool = False,
    dry_run: bool | None = None,
    include_status: bool = True,
    include_groups: bool = True,
    include_messages: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    started_mono = time.monotonic()
    settings = get_settings()
    preview = settings["dry_run"] if dry_run is None else bool(dry_run)
    today = _today()
    # Nettoyage automatique dès l'entrée (minuit + purge > 2h)
    get_log()

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

    def _clear_active_send() -> None:
        if preview:
            return
        cur = get_log()
        if cur.get("active_send"):
            cur["active_send"] = None
            _save_promo_log(cur)

    def finish(reason: str | None = None, promoted_ids: list[int | str] | None = None, last_gen: dict[str, Any] | None = None) -> dict[str, Any]:
        summary["aborted"] = reason
        summary["finished_at"] = _local_now().strftime("%Y-%m-%d %H:%M:%S")
        sent = summary["messages_ok"] + summary["groups_ok"]
        _clear_active_send()
        _record_run(
            summary,
            promoted_ids=promoted_ids or [],
            sent_today=sent,
            today=today,
            preview=preview,
            last_generated=last_gen,
            new_recent_logs=recent_events,
        )
        # Dès qu'une vague réelle est envoyée (ex: Vague 1 Matin), préparer aussitôt en place la Vague suivante (ex: Vague 2 Soir) !
        if not preview and (reason is None or bool(promoted_ids)):
            try:
                next_wave = get_wave_info(settings, get_log())
                if not next_wave.get("all_waves_done"):
                    prepare_wave_preview(force=True)
            except Exception as exc:
                current_app.logger.warning("whatsapp_promo.auto_prepare_next_wave_failed: %s", exc)
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

    if not preview and not force and _is_daily_slot_claimed(today):
        summary["aborted"] = "already_ran_today"
        return summary

    if not preview:
        gateway = get_whatsapp_gateway_status()
        if gateway.get("status") != "connected":
            return finish("gateway_not_connected")
        if not _claim_daily_run(today, force):
            summary["aborted"] = "already_ran_today"
            return summary

    log = get_log()
    last_gen = log.get("last_generated") or {}
    saved_items = last_gen.get("items") or []
    sent_ids_today = list((log.get("sent_ids_by_date") or {}).get(today) or [])
    sent_today_set = {str(x) for x in sent_ids_today}
    expected_sig = _offer_selection_signature(settings)

    # Envoi réel : réutiliser l'aperçu de la vague du jour (non consommé, quotas identiques, zéro doublon du jour)
    can_reuse_preview = (
        not preview
        and bool(saved_items)
        and last_gen.get("date") == today
        and bool(last_gen.get("dry_run"))
        and not bool(last_gen.get("consumed"))
        and (not last_gen.get("selection_sig") or last_gen.get("selection_sig") == expected_sig)
        and all(str(it.get("id")) not in sent_today_set for it in saved_items)
    )
    if can_reuse_preview:
        cards = []
        copies = {}
        base = _public_base_url()
        source = last_gen.get("copy_source") or "validated"
        for item in saved_items:
            item_t = item.get("item_type", "physical")
            raw_i = item.get("raw_id", item["id"])
            p_url = item.get("page_url") or (f"{base}/l/{raw_i}" if item_t == "rental" else f"{base}/p/{item['id']}")
            cards.append({
                "id": item["id"],
                "raw_id": raw_i,
                "item_type": item_t,
                "name": item.get("title") or item.get("name") or "",
                "shop": item.get("shop_name") or item.get("shop") or "",
                "category": item.get("category") or item.get("shop_city") or "",
                "city": item.get("city") or "",
                "price": item.get("price", 0),
                "old_price": item.get("old_price"),
                "price_line": item.get("price_line", ""),
                "image_url": item.get("image_url", ""),
                "has_image": bool(item.get("has_image", bool(item.get("image_url")))),
                "page_url": p_url,
            })
            raw_text = _clean_body_text(item.get("ai_message") or item.get("message") or item.get("direct_message") or "")
            raw_status = _clean_body_text(item.get("ai_status") or item.get("status") or item.get("status_caption") or "")
            is_custom = bool(item.get("is_custom"))
            copies[item["id"]] = {
                "is_custom": is_custom,
                "manually_edited": bool(item.get("manually_edited") or is_custom),
                "custom_full_status_caption": item.get("custom_full_status_caption") or "",
                "custom_full_group_message": item.get("custom_full_group_message") or "",
                "custom_caption": _clean_body_text(item.get("custom_caption") or "") if is_custom else "",
                "custom_group_message": _clean_body_text(item.get("custom_group_message") or "") if is_custom else "",
                "custom_direct_message": _clean_body_text(item.get("custom_direct_message") or "") if is_custom else "",
                "status": raw_status,
                "message": raw_text,
            }
        summary["copy_source"] = source
    else:
        cards = select_daily_offers(
            settings,
            promoted=log.get("promoted") or {},
            sent_ids_today=sent_ids_today,
        )
        if not cards:
            return finish("no_eligible_product")

        copies, source = generate_copy(cards)
        summary["copy_source"] = source

    items_data, last_generated_data, status_cards = _build_wave_items_and_meta(
        cards, copies, source, settings, log, today, preview=preview, consumed=not preview
    )
    summary["products"] = items_data
    summary["last_generated"] = last_generated_data

    def still_enabled() -> bool:
        return preview or get_settings()["enabled"]

    consecutive_failures = 0
    sent_card_ids: list[int | str] = []
    sent_card_set: set[str] = set()

    def _mark_card_sent(cid: int | str) -> None:
        key = str(cid)
        if key not in sent_card_set:
            sent_card_set.add(key)
            sent_card_ids.append(cid)

    people = _audience(settings)
    groups = settings.get("groups", [])

    if not preview:
        wave_now = get_wave_info(settings, log)
        total_ops = (len(status_cards) if run_status else 0) + (len(cards) * len(groups) if (run_groups and groups) else 0)
        log["active_send"] = {
            "started_at": f"{today} {_local_now().strftime('%H:%M:%S')}",
            "wave_title": wave_now["wave_title"],
            "offers_count": len(cards),
            "total_ops": total_ops,
        }
        _save_promo_log(log)

    # 1. CANAL STATUT WHATSAPP (Story 24h)
    if run_status:
        audience_phones = [person["phone"] for person in people]
        for index, card in enumerate(status_cards):
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

            if (time.monotonic() - started_mono) >= PERSISTENCE_WINDOW_SECONDS:
                return finish("expired_2h_window", sent_card_ids, last_generated_data)

            if not still_enabled():
                return finish("stopped_by_admin", sent_card_ids, last_generated_data)

            ok, reason, attempts = post_status_with_retry(card, caption, audience_phones)
            summary["statuses_ok" if ok else "statuses_failed"] += 1
            event["attempts"] = attempts
            event["status"] = "ok" if ok else "failed"
            if ok:
                _mark_card_sent(card["id"])
                event["details"] = "Publié avec succès" if attempts == 1 else f"Publié (après {attempts} tentatives)"
                consecutive_failures = 0
            else:
                event["details"] = f"Échec après {attempts} tentatives: {reason}"
                consecutive_failures += 1

            event["detail"] = event["details"]
            recent_events.append(event)
            summary["details"].append(event)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                return finish("gateway_failures", sent_card_ids, last_generated_data)

            if index < len(status_cards) - 1:
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
            total_group_sends = len(groups) * len(cards)
            step_min, step_max = _compute_group_step_delay_range(
                settings["min_delay"], settings["max_delay"], len(groups)
            )
            sent_group_idx = 0
            # Alternance Round-Robin : Offre 1 -> Grp 1, Grp 2, Grp 3 ; puis Offre 2 -> Grp 1, Grp 2, Grp 3...
            for card in cards:
                for grp in groups:
                    sent_group_idx += 1
                    group_label = grp.get("label") or grp["target"]
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

                    if (time.monotonic() - started_mono) >= PERSISTENCE_WINDOW_SECONDS:
                        return finish("expired_2h_window", sent_card_ids, last_generated_data)

                    if not still_enabled():
                        return finish("stopped_by_admin", sent_card_ids, last_generated_data)

                    current_app.logger.info(
                        "whatsapp_promo.attempting_group_send target=%s label=%s card_id=%s step_delay=%.0f-%.0fs",
                        grp["target"], group_label, card["id"], step_min, step_max,
                    )
                    result, reason, attempts = send_promo_media_with_retry(grp["target"], card, group_text)
                    event["attempts"] = attempts
                    if result == "sent":
                        _mark_card_sent(card["id"])
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
                        return finish("gateway_failures", sent_card_ids, last_generated_data)

                    if sent_group_idx < total_group_sends:
                        sleep(random.uniform(step_min, step_max))

    return finish(None, [] if preview else sent_card_ids, last_generated_data)


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
    @click.option("--scheduled", is_flag=True, help="Exécution planifiée (fenêtre stricte de 2h, sans rattrapage J+1).")
    @click.option("--status-only", is_flag=True, help="Uniquement Statuts.")
    @click.option("--groups-only", is_flag=True, help="Uniquement Groupes.")
    @click.option("--messages-only", is_flag=True, help="Uniquement Messages Privés.")
    def run_command(dry_run, force, scheduled, status_only, groups_only, messages_only):
        if scheduled:
            tick_result = run_scheduled_tick()
            click.echo(json.dumps(tick_result, ensure_ascii=False, indent=2))
            return
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


def run_scheduled_tick(*, sleep_fn: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Vérification périodique programmée (systemd toutes les 15 min) :
    - Purge l'historique quotidien à minuit et vide tout message bloqué vieux de plus de 2 heures.
    - Déclenche les créneaux programmés (schedule_time / schedule_time_2) UNIQUEMENT dans une fenêtre
      stricte de 2 heures (aucun envoi différé au lendemain ni au-delà de 2h).
    """
    now = _local_now()
    today = now.date().isoformat()
    log = get_log()
    settings = get_settings()

    if not settings.get("enabled"):
        return {"status": "disabled", "date": today}

    slots = [
        ("slot_1", settings.get("schedule_time") or "10:30"),
        ("slot_2", settings.get("schedule_time_2") or "18:30"),
    ]
    attempted = list((log.get("attempted_slots_by_date") or {}).get(today) or [])
    completed = list((log.get("completed_slots_by_date") or {}).get(today) or [])

    for slot_id, sched_str in slots:
        slot_key = f"{slot_id}:{sched_str}"
        sched_dt = _parse_local_timestamp(f"{today} {sched_str}:00", ref_now=now)
        if sched_dt is None:
            continue
        elapsed = (now - sched_dt).total_seconds()

        # Hors fenêtre [0, 2h] : soit pas encore l'heure, soit délai de 2h expiré -> ne rien envoyer
        if elapsed < 0 or elapsed > PERSISTENCE_WINDOW_SECONDS:
            continue

        if slot_key not in attempted:
            gw = get_whatsapp_gateway_status()
            if gw.get("status") != "connected":
                return {
                    "status": "waiting_gateway_within_2h",
                    "slot": slot_key,
                    "remaining_seconds": int(PERSISTENCE_WINDOW_SECONDS - elapsed),
                }
            run_kwargs: dict[str, Any] = {"force": True, "dry_run": False}
            if sleep_fn is not None:
                run_kwargs["sleep"] = sleep_fn
            summary = run_daily_promo(**run_kwargs)

            fresh_log = get_log()
            att_map = {today: list((fresh_log.get("attempted_slots_by_date") or {}).get(today) or [])}
            if slot_key not in att_map[today]:
                att_map[today].append(slot_key)
            fresh_log["attempted_slots_by_date"] = att_map

            has_pending = any(
                e.get("status") in ("failed", "pending")
                for e in (fresh_log.get("recent_logs") or [])
            )
            if not has_pending and summary.get("aborted") is None:
                comp_map = {today: list((fresh_log.get("completed_slots_by_date") or {}).get(today) or [])}
                if slot_key not in comp_map[today]:
                    comp_map[today].append(slot_key)
                fresh_log["completed_slots_by_date"] = comp_map
            _save_promo_log(fresh_log)
            return {
                "status": "executed",
                "slot": slot_key,
                "aborted": summary.get("aborted"),
                "statuses_ok": summary.get("statuses_ok", 0),
                "groups_ok": summary.get("groups_ok", 0),
            }

        if slot_key not in completed:
            has_retryable = any(
                e.get("status") in ("failed", "pending")
                and _is_within_persistence_window(e.get("timestamp"), now=now)
                for e in (log.get("recent_logs") or [])
            )
            if has_retryable:
                gw = get_whatsapp_gateway_status()
                if gw.get("status") != "connected":
                    return {
                        "status": "waiting_gateway_for_retry_within_2h",
                        "slot": slot_key,
                        "remaining_seconds": int(PERSISTENCE_WINDOW_SECONDS - elapsed),
                    }
                retry_res = retry_failed_promos(force=True, sleep_fn=sleep_fn)
                fresh_log = get_log()
                still_failing = any(
                    e.get("status") in ("failed", "pending")
                    for e in (fresh_log.get("recent_logs") or [])
                )
                if not still_failing:
                    comp_map = {today: list((fresh_log.get("completed_slots_by_date") or {}).get(today) or [])}
                    if slot_key not in comp_map[today]:
                        comp_map[today].append(slot_key)
                    fresh_log["completed_slots_by_date"] = comp_map
                    _save_promo_log(fresh_log)
                return {"status": "retried_within_2h", "slot": slot_key, "retry": retry_res}

    return {"status": "idle", "date": today, "time": now.strftime("%H:%M:%S")}


def retry_failed_promos(
    *,
    force: bool = False,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Relance uniquement les messages en échec/attente de moins de 2 heures aujourd'hui."""
    started_mono = time.monotonic()
    _sleep = sleep_fn or sleep
    today = _local_now().date().isoformat()
    log = get_log() or {}  # Vide déjà automatiquement tout échec > 2h ou de la veille
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

    to_retry: list[tuple[int, dict[str, Any]]] = []
    expired_indices: set[int] = set()
    for idx, item in enumerate(recent_logs):
        if item.get("status") in ("failed", "pending"):
            if not _is_within_persistence_window(item.get("timestamp")):
                expired_indices.add(idx)
                continue
            target = str(item.get("target") or "")
            if target in opted_out_targets:
                item["status"] = "skipped"
                item["detail"] = "Désinscrit (STOP) ou numéro invalide"
                item["details"] = item["detail"]
                continue
            to_retry.append((idx, item))

    if expired_indices:
        recent_logs = [it for i, it in enumerate(recent_logs) if i not in expired_indices]
        log["recent_logs"] = recent_logs
        _save_promo_log(log)
        to_retry = []
        for idx, item in enumerate(recent_logs):
            if item.get("status") in ("failed", "pending"):
                to_retry.append((idx, item))

    if not to_retry:
        return {
            "success": True,
            "message": "Aucun message récent (< 2h) en attente ou en échec à relancer.",
            "retried": 0,
            "ok": 0,
            "failed": 0,
        }

    # Données des produits
    last_gen = log.get("last_generated") or {}
    items_by_id = {
        str(item["id"]): item for item in (last_gen.get("items") or last_gen.get("products") or [])
    }

    retried_count = 0
    ok_count = 0
    retried_statuses_ok = 0
    failed_count = 0
    consecutive_failures = 0
    newly_sent_ids: list[str] = []
    audience_phones = [p["phone"] for p in _audience(settings)]

    for pos, (idx, event) in enumerate(to_retry):
        if not settings.get("enabled") and not force:
            break
        if (time.monotonic() - started_mono) >= PERSISTENCE_WINDOW_SECONDS:
            break
        if not _is_within_persistence_window(event.get("timestamp")):
            recent_logs[idx] = None  # Sera vidé à la sauvegarde
            continue

        channel = event.get("channel")
        target = event.get("target")
        msg_text = event.get("text")
        pid = event.get("product_id")
        card = items_by_id.get(str(pid)) if pid is not None else None

        if not card and pid is not None:
            pid_str = str(pid)
            if pid_str.startswith("rental_"):
                try:
                    from ..models.rental import RentalListing
                    rid = int(pid_str.split("_", 1)[1])
                    listing = db.session.get(RentalListing, rid)
                    if listing:
                        card = build_rental_card(listing)
                except Exception:
                    safe_session_rollback()
            elif pid_str.isdigit():
                prod = db.session.get(Product, int(pid_str))
                if prod:
                    promos = get_active_promos_for_products([prod.id])
                    card = build_product_card(prod, promos.get(prod.id))

        if not card or not target or not msg_text:
            event["status"] = "failed"
            event["detail"] = "Données du produit introuvables pour relancer"
            event["details"] = event["detail"]
            failed_count += 1
            continue

        retried_count += 1

        if channel == "status":
            ok, reason, attempts = post_status_with_retry(card, msg_text, audience_phones)
            if ok:
                ok_count += 1
                retried_statuses_ok += 1
                consecutive_failures = 0
                newly_sent_ids.append(str(pid))
                event["status"] = "ok"
                event["detail"] = "Statut publié avec succès (après relance)"
            else:
                failed_count += 1
                consecutive_failures += 1
                event["status"] = "failed"
                event["detail"] = f"Échec après relance: {reason}"
            event["attempts"] = event.get("attempts", 0) + attempts
        else:
            result, reason, attempts = send_promo_media_with_retry(target, card, msg_text)
            if result == "sent":
                ok_count += 1
                consecutive_failures = 0
                newly_sent_ids.append(str(pid))
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
        if event["status"] == "ok":
            event["timestamp"] = f"{today} {_local_now().strftime('%H:%M:%S')}"
            event["time"] = _local_now().strftime("%H:%M:%S")
        recent_logs[idx] = event

        # GARDE-FOU 3 : Déconnexion ou échecs consécutifs
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            break

        if pos < len(to_retry) - 1:
            distinct_grps = len({str(ev.get("target")) for _, ev in to_retry if ev.get("channel") == "group"}) or 1
            r_min, r_max = _compute_group_step_delay_range(settings["min_delay"], settings["max_delay"], distinct_grps)
            _sleep(random.uniform(r_min, r_max))

    # Sauvegarde des logs mis à jour (sans ceux expirés > 2h)
    log["recent_logs"] = [e for e in recent_logs if e is not None]
    if newly_sent_ids:
        promoted = dict(log.get("promoted") or {})
        sent_ids_map = {today: list((log.get("sent_ids_by_date") or {}).get(today) or [])}
        existing_sent = {str(x) for x in sent_ids_map[today]}
        for s_pid in newly_sent_ids:
            promoted[s_pid] = today
            if s_pid not in existing_sent:
                sent_ids_map[today].append(s_pid)
                existing_sent.add(s_pid)
        log["promoted"] = promoted
        log["sent_ids_by_date"] = sent_ids_map
    if retried_statuses_ok > 0:
        log["statuses_by_date"] = {
            today: int((log.get("statuses_by_date") or {}).get(today, 0)) + retried_statuses_ok
        }
    cleaned_log, _ = _clean_and_expire_log(log)
    _save_promo_log(cleaned_log)

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
def send_test_to_admin(*, product_id: int | str | None = None) -> dict[str, Any]:
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
    if product_id is not None and str(product_id).strip() != "":
        target_str = str(product_id).strip()
        for it in items:
            if str(it.get("id")) == target_str or str(it.get("product_id")) == target_str:
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
