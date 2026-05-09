from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start : next_route if next_route != -1 else len(source)]


def test_admin_locations_ajax_uses_targeted_fragments_instead_of_full_page():
    route_source = _read("app/routes/rentals.py")
    js_source = _read("app/static/js/pages/admin_locations_page.js")

    assert "section = _normalize_admin_locations_section" in route_source
    assert "admin/partials/_locations_fragment.html" in route_source
    assert 'params.set("section", section)' in js_source
    assert 'section: "listings"' in js_source
    assert 'section: "archives"' in js_source
    assert 'section: "both"' in js_source


def test_admin_locations_fragments_update_counts_when_filters_change():
    template = _read("app/templates/admin/locations.html")
    stats_partial = _read("app/templates/admin/partials/_locations_stats.html")
    fragment = _read("app/templates/admin/partials/_locations_fragment.html")
    js_source = _read("app/static/js/pages/admin_locations_page.js")

    assert 'include "admin/partials/_locations_stats.html"' in template
    assert 'id="locationsStats"' in stats_partial
    assert 'include "admin/partials/_locations_stats.html"' in fragment
    assert 'doc.getElementById("locationsStats")' in js_source
    assert "locationsStats.innerHTML = nextStats.innerHTML" in js_source


def test_admin_locations_indexes_are_declared_and_migrated():
    rental_model = _read("app/models/rental.py")
    lead_model = _read("app/models/product_contact_lead.py")
    migration_source = _read("app/services/migration.py")

    expected_indexes = [
        "ix_rental_listing_created_id",
        "ix_rental_listing_status_created",
        "ix_rental_listing_owner_created",
        "ix_rental_archive_closed_id",
        "ix_rental_archive_reason_closed",
        "ix_product_contact_lead_source_created",
    ]
    for index_name in expected_indexes:
        assert index_name in rental_model + lead_model
        assert index_name in migration_source

    assert "ensure_admin_performance_indexes" in _read("app/__init__.py")


def test_highlights_history_is_paginated_without_loading_every_featured_item():
    admin_source = _read("app/routes/admin.py")
    body = _function_body(admin_source, "_build_featured_items_context")

    assert "history_page = page_from_args" in body
    assert "history_pagination" in body
    assert "history_query.paginate" in body
    assert "latest_rows_query.all()" not in body


def test_rental_archiving_keeps_media_deletion_policy():
    service_source = _read("app/services/rentals.py")
    body = _function_body(service_source, "archive_and_remove_listing")

    assert "_delete_media_rows(media_rows)" in body
    assert "db.session.delete(listing)" in body
    assert "archive.media" not in service_source
