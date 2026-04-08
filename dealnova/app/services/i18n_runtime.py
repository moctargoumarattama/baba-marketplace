from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app

from .i18n_labels import normalize_lang


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


def translate_text(value: Any, lang: str | None = None) -> str:
    source = str(value or "")
    current_lang = normalize_lang(lang)
    if current_lang == "fr" or not source:
        return source
    return _load_language_dict(current_lang).get(source, source)


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
