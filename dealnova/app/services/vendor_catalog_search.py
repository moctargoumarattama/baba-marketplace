"""Catalogue search stays in SQL, before ordering and pagination."""

import unicodedata

from sqlalchemy import String, cast, false, func, or_

from ..extensions import db
from ..models.category import Category
from ..models.product import Product


def _fold(value):
    text = str(value or "").casefold().replace("œ", "oe").replace("æ", "ae")
    return "".join(char for char in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(char))


def _search_column(column):
    dialect = db.session.get_bind().dialect.name
    column = func.coalesce(column, "")
    if dialect == "sqlite":
        # Register on the checked-out connection: no extension or schema change.
        connection = db.session.connection().connection.driver_connection
        connection.create_function("bm_catalog_fold", 1, _fold, deterministic=True)
        return func.bm_catalog_fold(column)
    if dialect in {"mysql", "mariadb"}:
        return cast(column, String).collate("utf8mb4_unicode_ci")
    if dialect == "postgresql":
        # PostgreSQL translate is built in, unlike the optional unaccent extension.
        pairs = [(chr(code), _fold(chr(code))) for code in range(192, 592)]
        simple = [(source, target) for source, target in pairs
                  if len(target) == 1 and source != target]
        source, target = ("".join(pair[index] for pair in simple) for index in (0, 1))
        # Translate drops trailing source characters that have no target character.
        source += "".join(chr(code) for code in range(768, 880) if unicodedata.combining(chr(code)))
        result = func.translate(func.lower(column), source, target)
        for original, replacement in pairs:
            if len(replacement) > 1:
                result = func.replace(result, original.lower(), replacement)
        return result
    return func.lower(column)


def apply_vendor_catalog_search(query, search_term):
    """Every word may match a different field; LIKE metacharacters stay literal."""
    tokens = _fold(search_term).split()
    if not tokens:
        return query
    query = query.outerjoin(Category, Product.category_id == Category.id)
    searchable = _search_column(
        func.coalesce(Product.name, "") + " "
        + func.coalesce(Product.description, "") + " "
        + func.coalesce(Category.name, "")
    )
    for token in tokens:
        reference = token.removeprefix("#")
        is_reference = reference.isascii() and reference.isdigit()
        reference_filter = (Product.id == int(reference)) if is_reference and len(reference) <= 10 else false()
        if token.startswith("#") and is_reference:
            query = query.filter(reference_filter)
            continue
        escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        contains = searchable.like(f"%{escaped}%", escape="\\")
        query = query.filter(or_(contains, reference_filter) if is_reference else contains)
    return query
