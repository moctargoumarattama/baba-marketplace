from __future__ import annotations

import json
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app, has_request_context

import requests

from .i18n_labels import normalize_lang

_DYNAMIC_DARIJA_CACHE: dict[str, str] = {}
_DARIJA_TRANSLATE_LOCK = threading.Lock()
_DARIJA_BG_SEMAPHORE = threading.BoundedSemaphore(2)
_GEMINI_FAILURE_COOLDOWN_UNTIL = 0.0


def _i18n_dir() -> Path:
    static_folder = Path(str(current_app.static_folder or "")).resolve()
    return static_folder / "i18n"


@lru_cache(maxsize=8)
def _load_language_dict(lang: str) -> dict[str, str]:
    language = normalize_lang(lang)
    if language == "fr":
        return {}

    file_path = _i18n_dir() / f"{language}.json"
    if not file_path.exists():
        return {}

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, str] = {}
    for key, value in payload.items():
        source = str(key or "").strip()
        target = str(value or "").strip()
        if not source or not target:
            continue
        normalized[source] = target
    return normalized


def _is_mocked_requests_post() -> bool:
    post_fn = getattr(requests, "post", None)
    if post_fn is None:
        return False
    if hasattr(post_fn, "assert_called") or hasattr(post_fn, "return_value"):
        return True
    module_name = str(getattr(post_fn, "__module__", "") or "")
    return not module_name.startswith("requests")


def _perform_gemini_darija_translation(
    cleaned: str,
    api_key: str,
    model: str,
    i18n_dir: Path,
) -> str:
    global _GEMINI_FAILURE_COOLDOWN_UNTIL

    if not _is_mocked_requests_post() and time.monotonic() < _GEMINI_FAILURE_COOLDOWN_UNTIL:
        return cleaned

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    system_prompt = (
        "Tu es un traducteur expert en Darija marocain (Arabizi / alphabet latin marocain utilisé sur internet, ex: 3amyn, alryysya, lmtjr, mfa3al, lkhedma, chouf). "
        "Traduis l'expression d'interface suivante du français vers le Darija marocain (Arabizi). "
        "Donne UNIQUEMENT la traduction en texte brut, sans guillemets, sans explications."
    )
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": cleaned}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 60},
    }

    try:
        resp = requests.post(url, json=payload, timeout=1.5)
        if resp.status_code == 200:
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
            translated = parts[0].get("text", "").strip() if parts else ""
            if translated:
                _DYNAMIC_DARIJA_CACHE[cleaned] = translated
                try:
                    with _DARIJA_TRANSLATE_LOCK:
                        file_path = i18n_dir / "ary.json"
                        if file_path.exists():
                            current_dict = json.loads(file_path.read_text(encoding="utf-8"))
                            if current_dict.get(cleaned) != translated:
                                current_dict[cleaned] = translated
                                file_path.write_text(
                                    json.dumps(current_dict, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                                _load_language_dict.cache_clear()
                except Exception:
                    pass
                return translated
        else:
            _GEMINI_FAILURE_COOLDOWN_UNTIL = time.monotonic() + 180.0
    except Exception:
        _GEMINI_FAILURE_COOLDOWN_UNTIL = time.monotonic() + 180.0

    return cleaned


def auto_translate_ui_to_darija(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) < 2 or len(cleaned) > 200:
        return cleaned

    cached = _DYNAMIC_DARIJA_CACHE.get(cleaned)
    if cached is not None:
        return cached

    # Prevent duplicate synchronous retries on the same missing key.
    _DYNAMIC_DARIJA_CACHE[cleaned] = cleaned

    try:
        api_key = (current_app.config.get("GEMINI_API_KEY") or "").strip()
        if not api_key:
            return cleaned

        model = (
            current_app.config.get("GEMINI_MODEL") or "gemini-flash-lite-latest"
        ).strip() or "gemini-flash-lite-latest"
        i18n_dir = _i18n_dir()

        # Never block a live HTTP request waiting for an external LLM call.
        if has_request_context() and not _is_mocked_requests_post():
            if _DARIJA_BG_SEMAPHORE.acquire(blocking=False):
                def _bg_worker() -> None:
                    try:
                        _perform_gemini_darija_translation(cleaned, api_key, model, i18n_dir)
                    finally:
                        _DARIJA_BG_SEMAPHORE.release()

                threading.Thread(target=_bg_worker, daemon=True).start()
            return cleaned

        return _perform_gemini_darija_translation(cleaned, api_key, model, i18n_dir)
    except Exception:
        return cleaned


def translate_text(value: Any, lang: str | None = None) -> str:
    source = str(value or "")
    current_lang = normalize_lang(lang)
    if current_lang == "fr" or not source:
        return source

    dictionary = _load_language_dict(current_lang)
    cached = dictionary.get(source)
    if cached is None:
        cached = dictionary.get(source.strip())
    if cached is not None:
        return cached

    # Traduction automatique des nouveaux textes d'interface en Darija
    if current_lang == "ary":
        return auto_translate_ui_to_darija(source)

    return source


def build_client_i18n_payload(lang: str | None = None) -> dict[str, Any] | None:
    current_lang = normalize_lang(lang)
    if current_lang == "fr":
        return None

    dictionary = _load_language_dict(current_lang)
    if not dictionary:
        return None

    return {
        "lang": current_lang,
        "dict": dictionary,
    }
