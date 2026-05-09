from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start : next_route if next_route != -1 else len(source)]


def test_search_apis_enforce_server_side_minimum_query_lengths():
    source = _read("app/routes/api.py")

    assert "PRODUCT_SEARCH_MIN_CHARS = 2" in source
    assert "SECONDARY_SEARCH_MIN_CHARS = 3" in source

    for function_name, payload_key, min_constant in [
        ("search_products", "products", "PRODUCT_SEARCH_MIN_CHARS"),
        ("search_shops", "shops", "SECONDARY_SEARCH_MIN_CHARS"),
        ("search_locations", "locations", "SECONDARY_SEARCH_MIN_CHARS"),
        ("search_categories", "categories", "SECONDARY_SEARCH_MIN_CHARS"),
    ]:
        body = _function_body(source, function_name)
        assert f"len(q) < {min_constant}" in body
        assert f'jsonify({{"{payload_key}": []}})' in body


def test_global_search_is_instant_search_shell_without_unused_db_queries():
    source = _read("app/__init__.py")
    body = _function_body(source, "global_search")

    assert "Product.query.filter" not in body
    assert "Shop.query.filter" not in body
    assert "Category.query.filter" not in body
    assert "RentalListing.query.filter" not in body
    assert "results=results" in body
    assert '"products": []' in body


def test_product_detail_loads_ajax_runtime_for_ajax_forms():
    template = _read("app/templates/shop/product_detail.html")

    assert 'data-ajax="true"' in template
    assert "js/core/core_live.js" in template
    assert "js/pages/product_detail_page.js" in template


def test_promotions_uses_server_search_not_current_page_filtering():
    template = _read("app/templates/shop/promotions.html")

    assert 'method="get" action="{{ url_for(\'shop.promotions\') }}"' in template
    assert "filterCards" not in template
    assert "allCards" not in template
    assert 'name="page"' not in template


def test_shop_detail_products_use_clamped_stable_pagination_and_min_search():
    source = _read("app/routes/shops.py")
    body = _function_body(source, "shop_detail")

    assert "paginate_with_clamped_page" in source
    assert "search_q = q if len(q) >= 2 else \"\"" in body
    assert "Product.id.desc()" in body
    assert "query.paginate(" not in body
    assert "paginate_with_clamped_page(" in body


def test_checkout_get_does_not_record_product_contact_leads():
    source = _read("app/routes/cart.py")
    checkout_body = _function_body(source, "checkout")
    whatsapp_body = _function_body(source, "whatsapp_checkout")
    contact_body = _function_body(source, "record_whatsapp_contact")

    assert "request.method == \"GET\"" in checkout_body
    assert "record_product_contact_leads" not in checkout_body
    assert "record_product_contact_leads" not in whatsapp_body
    assert "record_product_contact_leads" in contact_body
    assert "_checkout_contact_session_key" in contact_body
