"""Canonical public catalogue URLs and server-rendered listing context."""
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from flask import current_app, render_template, request, url_for
from werkzeug.datastructures import MultiDict

from .public_catalog import build_public_catalog, parse_catalog_filters


CATALOG_ENDPOINTS = {
    "products": "public_catalog_pages.products",
    "services": "public_catalog_pages.services",
    "locations": "rentals.locations_home",
    "shops": "shops.list_shops",
    "promotions": "public_catalog_pages.promotions",
    "search": "public_catalog_pages.search",
}

_COPY = {
    "products": (
        "Produits et repas | Baba Market",
        "Produits et repas",
        "Découvrez les produits, repas, articles du quotidien et équipements proposés par les boutiques de Baba Market à Rabat, Salé, Kénitra et Témara.",
    ),
    "services": (
        "Services | Baba Market",
        "Services",
        "Découvrez les services des professionnels de Baba Market à Rabat, Salé, Kénitra et Témara : entretien, beauté, dépannage et bien plus.",
    ),
    "locations": (
        "Hébergements et locations | Baba Market",
        "Hébergements et locations",
        "Consultez les annonces de chambres, studios, appartements et locaux à louer sur Baba Market et contactez les propriétaires.",
    ),
    "promotions": (
        "Promotions | Baba Market",
        "Promotions",
        "Découvrez les promotions en cours sur les produits et repas des boutiques Baba Market.",
    ),
    "search": (
        "Rechercher une offre | Baba Market",
        "Toutes les offres",
        "Recherchez les produits, services, locations et boutiques disponibles sur Baba Market.",
    ),
}


def public_url(endpoint, **values):
    """Use the configured public origin when available, including behind proxies."""
    path = url_for(endpoint, **values)
    origin = str(current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return origin + path
    return url_for(endpoint, _external=True, **values)


def catalog_urls():
    return {universe: url_for(endpoint) for universe, endpoint in CATALOG_ENDPOINTS.items()}


def _filter_parameters(filters):
    """One normalized URL shape; discard modal state and tracking parameters."""
    values = {}
    for key in ("q", "cat", "shop", "city", "listing_type", "property_type", "min_price", "max_price"):
        value = filters.get(key)
        if value is not None and value != "":
            values[key] = value
    for key in ("stock", "promo", "smart"):
        if filters.get(key):
            values[key] = "1"
    if filters.get("sort") not in (None, "", "new"):
        values["sort"] = filters["sort"]
    if filters.get("page", 1) > 1:
        values["page"] = filters["page"]
    if filters.get("per_page", 12) != 12:
        values["per_page"] = filters["per_page"]
    return values


def render_public_catalog(universe):
    args = MultiDict(request.args)
    args.setlist("universe", [universe])
    error_message = ""
    status = 200
    try:
        filters = parse_catalog_filters(args)
        catalog = build_public_catalog(filters)
    except ValueError as exc:
        # Invalid filters should remain a useful HTML page, rather than a 500.
        error_message = str(exc)
        status = 400
        filters = parse_catalog_filters(MultiDict({"universe": universe}))
        catalog = {
            "success": False, "items": [],
            "facets": {"categories": [], "shops": [], "cities": []},
            "pagination": {"page": 1, "pages": 0, "total": 0, "per_page": 12,
                           "has_next": False, "has_prev": False},
            "filters": vars(filters),
        }

    endpoint = CATALOG_ENDPOINTS[universe]
    values = _filter_parameters(catalog["filters"])
    title, heading, description = _COPY[universe]
    page = catalog["pagination"]["page"]
    if page > 1:
        title = f"{heading} – Page {page} | Baba Market"
    filtered = any(key not in {"page"} for key in values)
    seo = {
        "title": title, "heading": heading, "description": description,
        "canonical_url": public_url(endpoint, **values),
        "robots": "noindex,follow" if status != 200 or universe == "search" or filtered else "index,follow",
        "universe": universe,
    }

    def page_url(number):
        page_values = {key: value for key, value in values.items() if key != "page"}
        if number > 1:
            page_values["page"] = number
        return url_for(endpoint, **page_values)

    return render_template(
        "catalog/public.html", catalog=catalog, seo=seo,
        catalog_urls=catalog_urls(), error_message=error_message,
        previous_url=page_url(page - 1) if catalog["pagination"]["has_prev"] else None,
        next_url=page_url(page + 1) if catalog["pagination"]["has_next"] else None,
    ), status


def build_public_sitemap():
    """List only canonical pages that satisfy the public visibility queries."""
    from ..models.product import Product
    from ..models.rental import RentalListing
    from ..models.shop import Shop
    from .marketplace_feed import _base_product_query, _public_location_query
    from .shop_access import RESERVED_ROOT_SHOP_SLUGS, is_safe_public_shop_slug

    entries = []
    seen = set()

    def add(endpoint, *, modified=None, **values):
        address = public_url(endpoint, **values)
        if address in seen:
            return
        seen.add(address)
        # Product has no modification timestamp; created_at would misrepresent
        # subsequent edits, so those entries intentionally have no lastmod.
        lastmod = modified.date().isoformat() if modified else None
        entries.append((address, lastmod))

    add("landing")
    for universe in ("products", "services", "locations", "shops", "promotions"):
        add(CATALOG_ENDPOINTS[universe])

    for shop in (Shop.query.filter(Shop.is_active.is_(True))
                 .order_by(Shop.id.asc()).limit(2000).all()):
        if is_safe_public_shop_slug(shop.slug, reserved=RESERVED_ROOT_SHOP_SLUGS):
            add("shops.shop_detail", shop_slug=shop.slug, modified=shop.updated_at)

    query, _, _, _, _ = _base_product_query(
        search_q="", category_id=None, kind="", min_price=None, max_price=None,
        promo_only="0", in_stock="0", shop_id=None,
    )
    products = (query.enable_eagerloads(False).filter(Product.kind.in_(("physical", "service")))
                .with_entities(Product.id).order_by(Product.id.asc()).limit(5000).all())
    for (product_id,) in products:
        add("shop.product_detail", pid=product_id)

    locations = (_public_location_query(search_q="", min_price=None, max_price=None, shop_id=None)
                 .with_entities(RentalListing.slug, RentalListing.updated_at)
                 .order_by(RentalListing.id.asc()).limit(2000).all())
    for slug, modified in locations:
        if slug:
            add("rentals.location_detail", slug=slug, modified=modified)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for address, lastmod in entries:
        lines.extend(["<url>", f"<loc>{escape(address)}</loc>"])
        if lastmod:
            lines.append(f"<lastmod>{lastmod}</lastmod>")
        lines.append("</url>")
    lines.append("</urlset>")
    return "\n".join(lines)
