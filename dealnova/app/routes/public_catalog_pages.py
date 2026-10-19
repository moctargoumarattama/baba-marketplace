"""Public HTML entry points share the same catalogue query as the modal API."""
from urllib.parse import urlencode

from flask import Blueprint, redirect, request, url_for

from ..services.public_seo import render_public_catalog


bp = Blueprint("public_catalog_pages", __name__)


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
