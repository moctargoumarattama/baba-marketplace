"""Presentation of shop descriptions without changing merchants' stored text."""

import re


# Exact placeholder values reviewed in the local catalogue. Do not broaden this
# list into a general rule for short, repeated or supposedly generated text.
_REVIEWED_SHOP_PLACEHOLDERS = frozenset({
    "css",
    "xccccccccccccccc",
    "sssssssssssss",
    "ssssssssssssss",
})

_LEGACY_SHOP_DESCRIPTION = re.compile(
    r"Boutique officielle de\s+"
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?)+",
    re.IGNORECASE,
)


def clean_shop_description(value: str | None) -> str:
    """Hide reviewed placeholders; preserve every other description verbatim."""
    if value is None:
        return ""
    candidate = value.strip()
    if candidate.casefold() in _REVIEWED_SHOP_PLACEHOLDERS:
        return ""
    if _LEGACY_SHOP_DESCRIPTION.fullmatch(candidate):
        return ""
    return value
