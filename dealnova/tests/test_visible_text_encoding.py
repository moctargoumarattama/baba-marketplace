from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

VISIBLE_TEXT_ROOTS = [
    ROOT / "app/templates",
    ROOT / "app/static/js",
    ROOT / "app/static/i18n",
    ROOT / "app/routes",
    ROOT / "app/services",
]

MOJIBAKE_MARKERS = [
    "\u00c3",
    "\u00c2",
    "\u00e2\u20ac",
    "\u00e2\u20ac\u00a2",
    "\u00e2\u0153",
    "\u00f0\u0178",
    "\ufffd",
]


def _visible_text_files():
    for root in VISIBLE_TEXT_ROOTS:
        for path in root.rglob("*"):
            if path.suffix.lower() in {".html", ".js", ".json", ".py"}:
                yield path


def test_visible_text_files_do_not_contain_mojibake_markers():
    offenders = []
    for path in _visible_text_files():
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        markers = [marker for marker in MOJIBAKE_MARKERS if marker in text]
        if markers:
            offenders.append(f"{path.relative_to(ROOT)}: {', '.join(markers)}")

    assert offenders == []


def test_cart_user_messages_keep_french_accents():
    cart_route = (ROOT / "app/routes/cart.py").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    cart_js = (ROOT / "app/static/js/pages/cart_page.js").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    combined = "\n".join([cart_route, cart_js])

    forbidden = [
        "Ce service se reserve",
        "reservation.",
        "Produit ajoute",
        "Verifiez",
        "rserver",
        "Panier mis a jour",
        "Produit supprime",
        "Quantite maximale",
    ]
    for text in forbidden:
        assert text not in combined

    expected = [
        "Ce service se réserve",
        "réservation.",
        "Produit ajouté",
        "Vérifiez",
        "réserver",
        "Panier mis à jour",
        "Produit supprimé",
        "Quantité maximale",
    ]
    for text in expected:
        assert text in combined
