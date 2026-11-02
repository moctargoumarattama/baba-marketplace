"""Public HTML entry points share the same catalogue query as the modal API."""
from urllib.parse import urlencode

from flask import Blueprint, abort, redirect, request, url_for

from ..services.public_seo import render_public_catalog


bp = Blueprint("public_catalog_pages", __name__)


MOROCCO_CITIES = {
    "casablanca": {"name": "Casablanca", "region": "Casablanca-Settat", "desc": "la capitale économique"},
    "rabat": {"name": "Rabat", "region": "Rabat-Salé-Kénitra", "desc": "la capitale administrative"},
    "marrakech": {"name": "Marrakech", "region": "Marrakech-Safi", "desc": "la ville ocre"},
    "tanger": {"name": "Tanger", "region": "Tanger-Tétouan-Al Hoceïma", "desc": "la porte du détroit"},
    "sale": {"name": "Salé", "region": "Rabat-Salé-Kénitra", "desc": "la cité jumelle de Rabat"},
    "kenitra": {"name": "Kénitra", "region": "Rabat-Salé-Kénitra", "desc": "le grand centre urbain du Gharb"},
    "temara": {"name": "Témara", "region": "Rabat-Salé-Kénitra", "desc": "la ville côtière dynamique"},
    "fes": {"name": "Fès", "region": "Fès-Meknès", "desc": "la capitale spirituelle et artisanale"},
    "meknes": {"name": "Meknès", "region": "Fès-Meknès", "desc": "la cité impériale"},
    "agadir": {"name": "Agadir", "region": "Souss-Massa", "desc": "la perle du Souss"},
    "oujda": {"name": "Oujda", "region": "Oriental", "desc": "la métropole de l'Oriental"},
    "tetouan": {"name": "Tétouan", "region": "Tanger-Tétouan-Al Hoceïma", "desc": "la colombe blanche"},
}

LOCAL_INTENTS = {
    "meubles-occasion": {
        "universe": "products",
        "query": "meuble",
        "title": "Meubles d'occasion à {city} pas cher | Baba Market",
        "heading": "Meubles d'occasion et mobilier à {city}",
        "desc": "Achetez et vendez vos meubles d'occasion à {city} : salons marocains, tables, lits, armoires et équipement en direct sans intermédiaire.",
    },
    "location-vacances": {
        "universe": "locations",
        "query": "",
        "title": "Location vacances et appartements à {city} | Baba Market",
        "heading": "Locations de vacances et hébergements à {city}",
        "desc": "Consultez les meilleures locations de vacances et appartements à {city}. Réservez et échangez directement avec les propriétaires sur WhatsApp.",
    },
    "services-domicile": {
        "universe": "services",
        "query": "",
        "title": "Services à domicile et artisans qualifiés à {city} | Baba Market",
        "heading": "Services à domicile et artisans à {city}",
        "desc": "Trouvez un artisan ou prestataire de confiance à {city} : plomberie, électricité, ménage, dépannage et rénovation recommandés par la communauté.",
    },
    "electromenager": {
        "universe": "products",
        "query": "electromenager",
        "title": "Électroménager à {city} au meilleur prix | Baba Market",
        "heading": "Électroménager neuf et occasion à {city}",
        "desc": "Découvrez notre sélection électroménager à {city} : réfrigérateurs, machines à laver, climatiseurs et fours avec livraison locale.",
    },
    "telephones": {
        "universe": "products",
        "query": "telephone",
        "title": "Smartphones et téléphones à {city} | Baba Market",
        "heading": "Smartphones et téléphones à {city}",
        "desc": "Boutiques et annonces de téléphones portables à {city} : iPhone, Samsung, Xiaomi et accessoires aux meilleurs prix.",
    },
}

UNIVERSE_SLUGS = {
    "produits": "products",
    "services": "services",
    "locations": "locations",
    "promotions": "promotions",
}


@bp.route("/produits")
def products():
    return render_public_catalog("products")


@bp.route("/products", strict_slashes=False)
def legacy_products():
    # Keep existing search-engine links and their filters on the canonical page.
    target = url_for(".products")
    query = urlencode(list(request.args.lists()), doseq=True)
    return redirect(target + ("?" + query if query else ""), code=301)


@bp.route("/services")
def services():
    return render_public_catalog("services")


@bp.route("/promotions")
def promotions():
    return render_public_catalog("promotions")


@bp.route("/recherche")
def search():
    return render_public_catalog("search")


@bp.route("/maroc/<city>")
def city_hub(city):
    city_slug = city.strip().lower()
    city_info = MOROCCO_CITIES.get(city_slug)
    if not city_info:
        abort(404)
    city_name = city_info["name"]
    custom_meta = {
        "title": f"Petites annonces, commerces et services à {city_name} | Baba Market",
        "heading": f"Toutes les offres à {city_name}",
        "desc": f"Explorez les commerces locaux, produits, repas, services et hébergements à {city_name} ({city_info['region']}). Contact direct des vendeurs sur WhatsApp.",
    }
    return render_public_catalog(
        "search",
        city=city_name,
        custom_meta=custom_meta,
        canonical_endpoint="public_catalog_pages.city_hub",
        canonical_kwargs={"city": city_slug},
    )


@bp.route("/maroc/<city>/<universe_or_intent>")
def city_landing(city, universe_or_intent):
    city_slug = city.strip().lower()
    city_info = MOROCCO_CITIES.get(city_slug)
    if not city_info:
        abort(404)
    city_name = city_info["name"]

    slug = universe_or_intent.strip().lower()
    if slug in UNIVERSE_SLUGS:
        universe = UNIVERSE_SLUGS[slug]
        universe_labels = {
            "products": "Produits et repas",
            "services": "Services",
            "locations": "Hébergements et locations",
            "promotions": "Promotions",
        }
        label = universe_labels.get(universe, "Offres")
        custom_meta = {
            "title": f"{label} à {city_name} | Baba Market",
            "heading": f"{label} disponibles à {city_name}",
            "desc": f"Découvrez les {label.lower()} proposés par les commerçants et professionnels de {city_name}. Commandes et échanges en direct sur WhatsApp.",
        }
        return render_public_catalog(
            universe,
            city=city_name,
            custom_meta=custom_meta,
            canonical_endpoint="public_catalog_pages.city_landing",
            canonical_kwargs={"city": city_slug, "universe_or_intent": slug},
        )

    if slug in LOCAL_INTENTS:
        intent = LOCAL_INTENTS[slug]
        custom_meta = {
            "title": intent["title"].format(city=city_name),
            "heading": intent["heading"].format(city=city_name),
            "desc": intent["desc"].format(city=city_name),
        }
        return render_public_catalog(
            intent["universe"],
            city=city_name,
            intent_q=intent["query"],
            custom_meta=custom_meta,
            canonical_endpoint="public_catalog_pages.city_landing",
            canonical_kwargs={"city": city_slug, "universe_or_intent": slug},
        )

    abort(404)
