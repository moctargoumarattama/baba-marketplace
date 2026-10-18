#!/usr/bin/env python3
"""
Enrichit dealnova/app/static/i18n/ary.json avec les traductions en Darija marocain (Arabizi)
pour toutes les clés d'interface manquantes présentes dans en.json.
Utilise Gemini Flash-Lite pour une traduction naturelle et authentique.
"""

import json
import os
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
ARY_PATH = ROOT / "app/static/i18n/ary.json"
EN_PATH = ROOT / "app/static/i18n/en.json"
ENV_PATH = ROOT / ".env"


def get_api_key():
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("GEMINI_API_KEY", "").strip()


def translate_batch(phrases: list[str], api_key: str, model: str = "gemini-flash-lite-latest") -> dict[str, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    system_prompt = (
        "Tu es un traducteur expert en Darija marocain (Arabizi / alphabet latin marocain utilisé sur le web au Maroc, "
        "exemples : 3amyn, alryysya, lmtjr, mfa3al, lkhedma, chouf, bghit, dyal, dialk, marhba, tswq, lpanier).\n"
        "Traduis chaque expression d'interface française en Darija marocain (Arabizi).\n"
        "Réponds UNIQUEMENT en JSON strict : un objet où chaque clé est l'expression française exacte de la liste "
        "et la valeur est la traduction naturelle en Darija (Arabizi).\n"
        "Garde les symboles spéciaux, pourcentages, chiffres et variables intacts."
    )

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(phrases, ensure_ascii=False)}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1},
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(raw_text)
        elif resp.status_code == 429:
            print("  [Rate limited 429] Pause de 8 secondes...")
            time.sleep(8)
            # Re-tentative
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return json.loads(raw_text)
            else:
                print(f"  [Erreur retry {resp.status_code}]: {resp.text[:120]}")
                return {}
        else:
            print(f"  [Erreur {resp.status_code}]: {resp.text[:120]}")
            return {}
    except Exception as exc:
        print(f"  [Exception]: {exc}")
        return {}


def main():
    print("=== ENRICHISSEMENT DU DICTIONNAIRE DARIJA (ary.json) ===")
    api_key = get_api_key()
    if not api_key:
        print("Erreur: Clé GEMINI_API_KEY introuvable.")
        return 1

    ary_dict = json.loads(ARY_PATH.read_text(encoding="utf-8"))
    en_dict = json.loads(EN_PATH.read_text(encoding="utf-8"))

    missing_keys = [k for k in en_dict.keys() if k not in ary_dict and k.strip()]
    print(f"Clés Darija actuelles: {len(ary_dict)}")
    print(f"Clés d'interface manquantes: {len(missing_keys)}")

    if not missing_keys:
        print("Toutes les clés sont déjà traduites en Darija !")
        return 0

    batch_size = 40
    batches = [missing_keys[i : i + batch_size] for i in range(0, len(missing_keys), batch_size)]
    total_batches = len(batches)
    print(f"Traduction de {len(missing_keys)} expressions en {total_batches} lots de {batch_size}...")

    added = 0
    for idx, batch in enumerate(batches, 1):
        print(f"-> Traitement du lot {idx}/{total_batches} ({len(batch)} expressions)...")
        translated_map = translate_batch(batch, api_key)
        for key in batch:
            val = translated_map.get(key)
            if val and isinstance(val, str) and val.strip():
                ary_dict[key] = val.strip()
                added += 1

        # Sauvegarde intermédiaire sécurisée
        ARY_PATH.write_text(json.dumps(ary_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(1.8)

    print(f"\nTerminé avec succès ! {added} nouvelles expressions traduites en Darija.")
    print(f"Total des clés dans ary.json : {len(ary_dict)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

