from __future__ import annotations

from typing import Dict


SUPPORTED_LANGS = {"fr", "en", "ary"}
DELIVERY_STATUS_FALLBACK = {"fr": "En cours", "en": "In progress", "ary": "F ttriq"}

DELIVERY_STATUS_LABELS: Dict[str, Dict[str, str]] = {
    "fr": {
        "new": "Nouvelle livraison",
        "delivered": "Livrée",
        "canceled": "Annulée",
        "cancelled": "Annulée",
    },
    "en": {
        "new": "New delivery",
        "delivered": "Delivered",
        "canceled": "Canceled",
        "cancelled": "Canceled",
    },
    "ary": {
        "new": "Twssila jdida",
        "delivered": "Tssalmat",
        "canceled": "Tlat",
        "cancelled": "Tlat",
    },
}

ORDER_STATUS_LABELS: Dict[str, Dict[str, str]] = {
    "fr": {
        "new": "Nouveau",
        "draft": "Demande à confirmer",
        "pending": "Commande confirmée",
        "paid": "Payée",
        "processing": "En préparation",
        "shipping": "En expédition",
        "shipped": "Expédiée",
        "delivered": "Livrée",
        "canceled": "Annulée",
        "cancelled": "Annulée",
        "expired": "Demande expirée",
        "archived": "Archivée",
    },
    "en": {
        "new": "New",
        "draft": "Request to confirm",
        "pending": "Order confirmed",
        "paid": "Paid",
        "processing": "Processing",
        "shipping": "Shipping",
        "shipped": "Shipped",
        "delivered": "Delivered",
        "canceled": "Canceled",
        "cancelled": "Canceled",
        "expired": "Request expired",
        "archived": "Archived",
    },
    "ary": {
        "new": "Jdida",
        "draft": "Khas ttsdeq",
        "pending": "Ttsdeqat",
        "paid": "Tkhlsat",
        "processing": "Katwjjed",
        "shipping": "Mcha lttwsil",
        "shipped": "Mchrat",
        "delivered": "Tssalmat",
        "canceled": "Tlat",
        "cancelled": "Tlat",
        "expired": "Salat",
        "archived": "Makhzona",
    },
}

VENDOR_PAYOUT_STATUS_FALLBACK = {"fr": "En cours", "en": "In progress", "ary": "F ttriq"}
VENDOR_PAYOUT_STATUS_LABELS: Dict[str, Dict[str, str]] = {
    "fr": {
        "pending": "Paiement bloqué",
        "claimable": "Vendeur peut confirmer",
        "claimed": "Réception confirmée",
        "paid": "Vendeur payé",
        "cancelled": "Annulé",
    },
    "en": {
        "pending": "Payment locked",
        "claimable": "Vendor can confirm",
        "claimed": "Receipt confirmed",
        "paid": "Vendor paid",
        "cancelled": "Cancelled",
    },
    "ary": {
        "pending": "Khlas mazal m7bous",
        "claimable": "Lbay3 y9dr y2akked",
        "claimed": "T2akked lwsoul",
        "paid": "Lbay3 tkhlles",
        "cancelled": "Tlat",
    },
}

SOURCE_LABELS: Dict[str, Dict[str, str]] = {
    "fr": {"marketplace": "Marketplace", "special": "Spéciale"},
    "en": {"marketplace": "Marketplace", "special": "Special"},
    "ary": {"marketplace": "Marketplace", "special": "Khasa"},
}

LOCATION_STATUS_FALLBACK = {"fr": "En cours", "en": "In progress", "ary": "F ttriq"}
LOCATION_STATUS_LABELS: Dict[str, Dict[str, str]] = {
    "fr": {
        "active": "Active",
        "reserved": "Réservée",
        "taken": "Prise",
        "expired": "Expirée",
        "archived": "Archivée",
    },
    "en": {
        "active": "Active",
        "reserved": "Reserved",
        "taken": "Taken",
        "expired": "Expired",
        "archived": "Archived",
    },
    "ary": {
        "active": "Mfa3la",
        "reserved": "M7jooza",
        "taken": "Tkhlsat",
        "expired": "Salat",
        "archived": "Makhzona",
    },
}


def normalize_lang(lang: str | None) -> str:
    code = (lang or "fr").strip().lower()
    return code if code in SUPPORTED_LANGS else "fr"


def normalize_status(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_")


def label_delivery_status(status: str | None, lang: str | None = None) -> str:
    current_lang = normalize_lang(lang)
    key = normalize_status(status)
    labels = DELIVERY_STATUS_LABELS[current_lang]
    return labels.get(key) or DELIVERY_STATUS_FALLBACK[current_lang]


def label_order_status(status: str | None, lang: str | None = None) -> str:
    current_lang = normalize_lang(lang)
    key = normalize_status(status)
    labels = ORDER_STATUS_LABELS[current_lang]
    return labels.get(key) or DELIVERY_STATUS_FALLBACK[current_lang]


def label_vendor_payout_status(status: str | None, lang: str | None = None) -> str:
    current_lang = normalize_lang(lang)
    key = normalize_status(status)
    labels = VENDOR_PAYOUT_STATUS_LABELS[current_lang]
    return labels.get(key) or VENDOR_PAYOUT_STATUS_FALLBACK[current_lang]


def label_source(source: str | None, lang: str | None = None) -> str:
    current_lang = normalize_lang(lang)
    key = (source or "marketplace").strip().lower()
    return SOURCE_LABELS[current_lang].get(key, SOURCE_LABELS[current_lang]["marketplace"])


def label_location_status(status: str | None, lang: str | None = None) -> str:
    current_lang = normalize_lang(lang)
    key = normalize_status(status)
    labels = LOCATION_STATUS_LABELS[current_lang]
    return labels.get(key) or LOCATION_STATUS_FALLBACK[current_lang]


def delivery_status_labels_for_lang(lang: str | None = None) -> Dict[str, str]:
    current_lang = normalize_lang(lang)
    labels = dict(DELIVERY_STATUS_LABELS[current_lang])
    labels["_fallback"] = DELIVERY_STATUS_FALLBACK[current_lang]
    return labels
