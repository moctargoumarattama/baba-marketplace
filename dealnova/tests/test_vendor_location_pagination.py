from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start : next_route if next_route != -1 else len(source)]


def test_public_locations_use_one_stable_pagination_strategy():
    source = _read("app/routes/rentals.py")
    body = _function_body(source, "locations_home")

    assert "CURATED_PAGE_LIMIT" not in body
    assert "build_location_feed" not in body
    assert "paginate_with_clamped_page(" in body
    assert "RentalListing.created_at.desc(), RentalListing.id.desc()" in body


def test_search_short_terms_do_not_trigger_wildcard_description_scans():
    rentals_body = _function_body(_read("app/routes/rentals.py"), "locations_home")
    catalog_body = _function_body(_read("app/routes/vendor.py"), "catalog")

    assert "search_q = q if len(q) >= 2 else \"\"" in rentals_body
    assert "description_search_q = q if len(q) >= 3 else \"\"" in rentals_body
    assert "if description_search_q:" in rentals_body

    assert "search_term_query = search_term if len(search_term) >= 2 else \"\"" in catalog_body
    assert "if search_term_query:" in catalog_body
    assert "Product.description.ilike(like_term)" in catalog_body


def test_owner_locations_total_card_uses_full_pagination_total():
    template = _read("app/templates/locations/owner_index.html")

    assert "{{ pagination.total }}" in template
    assert "{{ listings|length }}" not in template


def test_page_clamping_helper_is_used_by_large_vendor_and_location_lists():
    pagination_source = _read("app/services/pagination.py")
    rentals_source = _read("app/routes/rentals.py")
    vendor_source = _read("app/routes/vendor.py")

    assert "def paginate_with_clamped_page(" in pagination_source
    assert "paginate_with_clamped_page(" in rentals_source
    assert "query.order_by(RentalListing.created_at.desc(), RentalListing.id.desc())" in rentals_source
    assert "paginate_with_clamped_page(product_query" in vendor_source


def test_vendor_and_owner_performance_indexes_are_declared_and_migrated():
    product_model = _read("app/models/product.py")
    rental_model = _read("app/models/rental.py")
    migration_source = _read("app/services/migration.py")
    alembic_source = _read("../migrations/versions/c4d8e91f2a6b_add_admin_performance_indexes.py")

    expected_indexes = [
        "ix_product_vendor_created_id",
        "ix_product_vendor_active_created",
        "ix_product_vendor_kind_created",
        "ix_product_vendor_category_created",
        "ix_rental_archive_owner_closed",
        "ix_rental_archive_owner_reason_closed",
    ]
    for index_name in expected_indexes:
        assert index_name in product_model + rental_model
        assert index_name in migration_source
        assert index_name in alembic_source


def test_locations_placeholder_is_local_and_valid():
    template = _read("app/templates/partials/_locations_listing.html")

    assert "https://images.unsplash.com/photo-1560185007-cde436f6a4d0auto" not in template
    assert "img/placeholders/location.svg" in template
