from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app

import requests

from .i18n_labels import normalize_lang

_DYNAMIC_DARIJA_CACHE: dict[str, str] = {}


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


def auto_translate_ui_to_darija(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) < 2 or len(cleaned) > 200:
        return cleaned

    if cleaned in _DYNAMIC_DARIJA_CACHE:
        return _DYNAMIC_DARIJA_CACHE[cleaned]

    try:
        api_key = (current_app.config.get("GEMINI_API_KEY") or "").strip()
        if not api_key:
            return cleaned

        model = (current_app.config.get("GEMINI_MODEL") or "gemini-flash-lite-latest").strip() or "gemini-flash-lite-latest"
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

        resp = requests.post(url, json=payload, timeout=4)
        if resp.status_code == 200:
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
            translated = parts[0].get("text", "").strip() if parts else ""
            if translated:
                _DYNAMIC_DARIJA_CACHE[cleaned] = translated
                try:
                    file_path = _i18n_dir() / "ary.json"
                    if file_path.exists():
                        current_dict = json.loads(file_path.read_text(encoding="utf-8"))
                        current_dict[cleaned] = translated
                        file_path.write_text(json.dumps(current_dict, ensure_ascii=False, indent=2), encoding="utf-8")
                        _load_language_dict.cache_clear()
                except Exception:
                    pass
                return translated
    except Exception:
        pass
    return cleaned


def translate_text(value: Any, lang: str | None = None) -> str:
    source = str(value or "")
    current_lang = normalize_lang(lang)
    if current_lang == "fr" or not source:
        return source

    dictionary = _load_language_dict(current_lang)
    cached = dictionary.get(source)
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
