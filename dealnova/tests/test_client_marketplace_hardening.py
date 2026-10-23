from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start : next_route if next_route != -1 else len(source)]


def test_global_search_is_instant_search_shell_without_unused_db_queries():
    source = _read("app/__init__.py")
    marker = "def global_search():"
    start = source.index(marker)
    end = source.find("\n    @", start)
    body = source[start : end if end != -1 else len(source)]

    assert "Product.query.filter" not in body
    assert "Shop.query.filter" not in body
    assert "Category.query.filter" not in body
    assert "RentalListing.query.filter" not in body
    assert "landing" in body
    assert 'open="search"' in body


def test_product_detail_uses_home_modal_and_opens_direct_product_links():
    route = _read("app/routes/shop.py")
    template = _read("app/templates/home.html")
    runtime = _read("app/static/js/ui_home_single_hub.js")

    assert '"home.html"' in route
    assert "data-initial-product-id" in template
    assert "document.body.dataset.initialProductId" in runtime


def test_promotions_uses_server_search_not_current_page_filtering():
    shop_routes = _read("app/routes/shop.py")

    assert "landing" in shop_routes
    assert "promotions" in shop_routes
    assert "filterCards" not in shop_routes
    assert "allCards" not in shop_routes


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
