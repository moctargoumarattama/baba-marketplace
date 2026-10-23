"""Conservative, offline interpretation of requests for the public catalogue.

Only specified filters are returned. ``None`` on a price means that the person
explicitly removed that limit; absent keys must not erase conversation state.
This module never grants access, queries inventory, or invents an answer.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation


_NUMBER = r"(?<![\d-])\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d{1,2})?(?:\s*k)?(?=\s*(?:dhs?|mad|dirhams?)(?!\w)|[^\w.,]|$)"
_AMOUNT = rf"({_NUMBER})(?:\s*(?:dh|dhs|mad|dirhams?))?"
_CITIES = {"rabat": "Rabat", "sale": "Salé", "kenitra": "Kénitra", "temara": "Témara",
           "casablanca": "Casablanca", "marrakech": "Marrakech", "tanger": "Tanger",
           "agadir": "Agadir", "fes": "Fès", "meknes": "Meknès", "oujda": "Oujda"}
_SPELLINGS = {"coifeur": "coiffeur", "coifeuse": "coiffeuse", "coiffuer": "coiffeur",
              "plonbier": "plombier", "plombierie": "plomberie", "reparaton": "reparation",
              "apartement": "appartement", "appartemen": "appartement",
              "telephon": "telephone", "telephonne": "telephone", "ordinatreur": "ordinateur",
              "restaurent": "restaurant", "livrason": "livraison", "boutiqe": "boutique",
              "produi": "produit", "produt": "produit", "servise": "service"}
_KEYWORDS = {"coiffeur": "coiffure", "coiffeuse": "coiffure", "coiffer": "coiffure",
             "plombier": "plomberie", "electricien": "électricité",
             "reparer": "réparation", "reparation": "réparation", "depanner": "dépannage",
             "telephone": "téléphone", "telephones": "téléphone", "ordi": "ordinateur",
             "vetements": "vêtements", "beaute": "beauté", "television": "télévision"}
_STOPWORDS = set("""bonjour bonsoir salut svp stp s il vous plait merci je j tu il elle on nous vous
ils elles me m moi mon ma mes ton ta tes son sa ses ce cet cette ces ca cela c est sont etre
ai as a ont y en de d du des le la les l un une et ou mais pour par avec sans sur sous dans
au aux ici pres proche chez vers tres bien peu plus moins pas tout tous toute toutes aussi
cherche chercher recherche rechercher trouver trouve veux veut voudrais souhaite besoin avez avezvous
avez-vous avez vous avezvous pourriez pouvez estce est-ce que qui quoi comment quelqu quelquun
personne quelquune plutot acheter achat voir montrer montre donne donnez proposer propose faites faire
produit produits article articles service services offre offres location locations boutique boutiques
max maximum mini minimum budget prix euros dirham dirhams dh dhs mad limite filtre filtres
cher chers chere cheres economique economie abordable nouveaute nouveautes recent recents
nouveau nouveaux nouvelle nouvelles disponible disponibles stock uniquement seulement juste maintenant
etait ce cherchez aider aide besoin veux voudrais souhaites voudrais souhaite entre partir jusqu
un endroit lieu appartement appartements chambre chambres studio studios appartement appart
mensuel mensuelle mois journalier journaliere jour jours nuit nuits louer loue loyers loyer
promotion promotions promo promos solde soldes reduction reductions envoie veux voudrais finalement
autre autres finalement sinon plutot bon bonnes bons bonne""".split())
_RENTAL_WORDS = set("appartement appartements appart chambre chambres studio studios mensuel mensuelle mois journalier journaliere jour jours nuit nuits".split())
_STOPWORDS.difference_update(_RENTAL_WORDS)


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(c))


def _has(text: str, pattern: str) -> bool:
    return re.search(r"(?<!\w)(?:" + pattern + r")(?!\w)", text) is not None


def _price(value: str) -> float | None:
    compact = re.sub(r"\s+", "", value).replace(",", ".")
    multiplier = 1000 if compact.endswith("k") else 1
    try:
        number = Decimal(compact.removesuffix("k")) * multiplier
        return float(number) if number.is_finite() and 0 <= number <= 1_000_000_000 else None
    except InvalidOperation:
        return None


def _action(text: str) -> str | None:
    if _has(text, r"(?:menu(?: principal)?|recommencer|accueil|bonjour|bonsoir|salut)") and len(text.split()) <= 2:
        return "start"
    if _has(text, r"(?:devenir|inscri\w*|creer|ouvrir)\s+(?:(?:un|une|mon|ma|compte|espace)\s+)*(?:vendeur|boutique)"):
        return "become_vendor"
    if text in {"support", "aide", "conseiller", "contact", "contact support"} or _has(
        text, r"(?:contacter|parler|joindre|appeler)\s+(?:(?:un|le|au|a|avec|une)\s+)*(?:conseiller|support|humain|equipe)|besoin d aide|probleme (?:avec|sur|de|pour) (?:ma|mon|une?|le|la) (?:commande|paiement|compte)"):
        return "handoff"
    if _has(text, r"(?:envoyer|expedier|livrer)\s+(?:(?:un|une|le|la|mon|ma|des)\s+)*(?:colis|paquet)|organiser (?:une )?livraison|(?:comment|prix|tarif|delai|cout|fonctionne).*(?:livraison|envoyer un colis)") or text in {"livraison", "livraison de colis"}:
        return "help_delivery"
    if _has(text, r"(?:comment|ou|suivre|suivi|commander|commande)") and _has(
        text, r"(?:commander|commande|commandes)") and _has(text, r"comment|ou|suivre|suivi|ma commande|mes commandes"):
        return "faq_order"
    if _has(text, r"(?:comment|peut on|puis je|possible|moyens? de|modes? de).*(?:payer|paiement|regler)|(?:payer|paiement) (?:comment|en ligne|a la livraison|par carte)|acceptez.*(?:carte|especes)"):
        return "faq_payment"
    if _has(text, r"(?:faut il|dois je|obligatoire|besoin|creer|avoir|sans|invite).*(?:compte|inscription)|compte client|mode invite"):
        return "faq_guest"
    if _has(text, r"panier") and _has(text, r"comment|ou|voir|vider|modifier|retirer|ajouter|mon panier"):
        return "faq_cart"
    if _has(text, r"comment|peut on|puis je|possible") and _has(text, r"reserver|reservation|prendre rendez vous"):
        return "faq_booking"
    if _has(text, r"comment|peut on|puis je|conditions") and _has(text, r"louer|location|loyer"):
        return "faq_rental"
    return None


def parse_public_request(text: str, *, context: dict | None = None) -> dict:
    """Extract explicit intent/filters without network access or inherited values.

    ``explicit_kind`` distinguishes a new universe from an ordinary refinement.
    ``refinement`` means the existing keywords should be retained by the caller.
    ``needs_ai`` requests optional semantic assistance, never an invented result.
    """
    source = " ".join(unicodedata.normalize("NFKC", str(text or "")).replace("\x00", "").split())[:1000]
    preferred = {_fold(token): token.casefold() for token in re.findall(r"[^\W\d_]+", source)}
    folded = _fold(source).replace("’", "'")
    folded = re.sub(r"(?<!\d)-(?!\d)|'", " ", folded)
    folded = re.sub(r"\b\w+\b", lambda m: _SPELLINGS.get(m.group(), m.group()), folded)
    folded = " ".join(folded.split()).strip(" ?!.,")
    if not folded:
        return {}
    action = _action(folded)
    if action:
        return {"action": action}

    context = context if isinstance(context, dict) else {}
    # Conversation controls are not catalogue keywords, even during a search.
    if _has(folded, r"reponds? (?:moi )?(?:correctement|bien|a ma question)|tu (?:ne )?comprends? (?:pas|rien)|mauvaise reponse|pas (?:ce que|ca que) (?:je|j) (?:veux|ai demande)|tu (?:te )?repetes?"):
        return {"conversation": "repair", "needs_ai": True}
    if re.fullmatch(r"(?:et |alors )?(?:il y a quoi|y a quoi|vous avez quoi|quoi|qu est ce qui est|qu est ce que vous avez)(?: de)?(?: disponible| disponibles| en stock)?(?: maintenant| ici)?", folded):
        return {"conversation": "browse", "query": "", "stock": True}
    result: dict = {}
    remaining = folded
    # Extract numbers before words so that prices never pollute catalogue search.
    price_spans = []
    range_match = re.search(rf"(?:entre|de)\s+{_AMOUNT}\s+(?:et|a)\s+{_AMOUNT}", folded)
    if range_match:
        lower, upper = _price(range_match[1]), _price(range_match[2])
        if lower is not None and upper is not None and lower <= upper:
            result.update(min_price=lower, max_price=upper)
            price_spans.append(range_match.span())
    for key, pattern in (
        ("max_price", rf"(?:moins de|en dessous de|pas plus de|jusqu a|max(?:imum)?|budget(?: de)?|pour)\s*{_AMOUNT}"),
        ("min_price", rf"(?:plus de|au dessus de|a partir de|min(?:imum)?)\s*{_AMOUNT}"),
    ):
        match = re.search(pattern, folded)
        if match and not any(a <= match.start() < b for a, b in price_spans):
            amount = _price(match[1])
            if amount is not None:
                result[key] = amount
                price_spans.append(match.span())
    if not price_spans:
        match = re.search(rf"({_NUMBER})\s*(?:dh|dhs|mad|dirhams?)(?!\w)", folded)
        if not match and context.get("kind"):
            match = re.fullmatch(rf"(?:et\s+)?(?:a\s+)?{_AMOUNT}", folded)
        if match:
            amount = _price(match[1])
            if amount is not None:
                result["max_price"] = amount
                price_spans.append(match.span())
    for start, end in sorted(price_spans, reverse=True):
        remaining = remaining[:start] + " " + remaining[end:]
    if _has(folded, r"sans (?:limite(?: de prix)?|budget)|pas de (?:limite|budget)"):
        result.update(min_price=None, max_price=None)
    cheap_pattern = r"moins cher|pas (?:trop )?(?:cher|eleve[ers]?|elevee?s?|haut)|prix (?:croissant|bas)|petit prix|economique|abordable"
    if _has(folded, cheap_pattern):
        result["sort"] = "low"
        remaining = re.sub(cheap_pattern, " ", remaining)
    elif _has(folded, r"plus cher|prix decroissant"):
        result["sort"] = "high"
    elif _has(folded, r"nouveautes?|plus recents?|nouveaux|nouvelles"):
        result["sort"] = "new"
    if _has(folded, r"sans (?:promo(?:tion)?s?|reduction)|hors promo|pas (?:de|en) promo(?:tion)?"):
        result["promo"] = False
    elif _has(folded, r"promo(?:tion)?s?|soldes?|reductions?"):
        result["promo"] = True
    if _has(folded, r"en stock|disponibles? uniquement|uniquement disponibles?"):
        result["stock"] = True
    elif _has(folded, r"meme (?:en rupture|indisponibles?)|sans filtre (?:de )?stock"):
        result["stock"] = False
    for city_key, city in _CITIES.items():
        if _has(folded, re.escape(city_key)):
            # "Poisson salé" is food, while "à Salé" specifies a city.
            if city_key == "sale" and folded != "sale" and not _has(
                folded, r"(?:a|sur|de|vers|ville) sale"):
                continue
            result["city"] = city
            remaining = re.sub(r"(?<!\w)" + city_key + r"(?!\w)", " ", remaining)
            break

    property_type = None
    for pattern, value in ((r"studios?", "studio"), (r"appartements?|apparts?", "apartment"),
                           (r"chambres?", "room"), (r"local commercial|magasin a louer", "store")):
        if _has(folded, pattern):
            property_type = value
            break
    rental_intent = _has(folded, r"locations?|louer|loyer|hebergements?|appartements?|apparts?|studios?|chambres?|local commercial|villa a louer|maison a louer")
    service_intent = _has(folded, r"services?|coiffeur|coiffeuse|coiffure|plombier|plomberie|electricien|menage|reparer|reparation|depanner|mecanicien|massage")
    product_intent = _has(folded, r"produits?|articles?|acheter|achat|repas|plats?|manger|nourriture")
    entity = re.search(r"\b(?:produits?|articles?|services?|locations?|boutiques?|magasins?|commercants?|restaurants?|repas|plats?)\b", folded)
    requested_shop = bool(entity and _has(entity.group(), r"boutiques?|magasins?|commercants?|restaurants?"))
    if requested_shop and not _has(folded, r"a louer"):
        # "Boutique de produits" asks for a shop, "produits de boutique" does not.
        result.update(kind="shops", explicit_kind=True)
    elif rental_intent and not product_intent:
        result.update(kind="locations", explicit_kind=True)
    elif _has(folded, r"boutiques?|magasins?|commercants?|restaurants?") and not _has(folded, r"produits?|articles?|repas|plat|manger"):
        # The requested entity wins over its speciality: a hair salon is a shop.
        result.update(kind="shops", explicit_kind=True)
    elif service_intent and not _has(folded, r"produits?|articles?|acheter|achat|appareils? (?:de|pour)"):
        result.update(kind="services", explicit_kind=True)
    elif product_intent:
        result.update(kind="products", explicit_kind=True)
    elif result.get("promo") is True and not context.get("kind"):
        result.update(kind="promotions", explicit_kind=True)
    elif _has(folded, r"toutes les offres|tout le catalogue"):
        result.update(kind="search", explicit_kind=True)
    if property_type and (result.get("kind") == "locations" or context.get("kind") == "locations"):
        result["property_type"] = property_type
    if result.get("kind") == "locations" or context.get("kind") == "locations":
        if _has(folded, r"par jour|a la journee|par nuit|journalier|journaliere|courte duree"):
            result["listing_type"] = "daily"
            remaining = re.sub(r"a la journee|courte duree", " ", remaining)
        elif _has(folded, r"par mois|mensuel|mensuelle|longue duree"):
            result["listing_type"] = "monthly"
            remaining = remaining.replace("longue duree", " ")

    stopwords = _STOPWORDS
    if result.get("kind", context.get("kind")) == "locations":
        stopwords = _STOPWORDS | _RENTAL_WORDS
        if property_type == "store":
            remaining = remaining.replace("local commercial", " ").replace("magasin a louer", " ")
    words = re.findall(r"[^\W_]+", remaining)
    vague_words = {"truc", "trucs", "chose", "choses", "quelque", "simple", "simples", "qqch"}
    keywords = [_KEYWORDS.get(word, preferred.get(word, word)) for word in words
                if word not in stopwords and word not in vague_words]
    query = " ".join(dict.fromkeys(keywords))[:160]
    if not query and not result.get("explicit_kind") and any(word in vague_words for word in words):
        result.update(conversation="clarify", needs_ai=True)
    if query or result.get("explicit_kind"):
        result["query"] = query
    if context.get("kind") and not result.get("explicit_kind") and not query and result:
        result["refinement"] = True
    if _has(folded, r"quelqu un pour|j ai faim|j ai soif|(?:besoin d un|offrir un|cherche un) cadeau|cadeau pour|ne marche plus|en panne|mal au|besoin de conseils?|je ne sais pas"):
        result["needs_ai"] = True
    return result
