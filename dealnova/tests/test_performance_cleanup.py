from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start : next_route if next_route != -1 else len(source)]


def test_service_worker_does_not_cache_uploaded_videos_as_images():
    source = _read("app/static/sw.js")

    assert "UPLOAD_IMAGE_EXT_RE" in source
    assert "pathname.startsWith(\"/static/uploads/\") && UPLOAD_IMAGE_EXT_RE.test(pathname)" in source
    assert "return pathname.startsWith(\"/static/uploads/\");" not in source


def test_admin_page_loader_has_no_heavy_default_stack_for_every_admin_page():
    source = _read("app/static/js/core/page_loader.js")

    assert "var ADMIN_STACK = [" in source
    assert "deliveries: ADMIN_STACK" in source
    assert '"admin.deliveries_live": ADMIN_STACK' not in source
    assert '"admin.order_archives": ADMIN_STACK' not in source
    assert "if (!list.length && ctx.isAdmin)" not in source
    assert "admin.finance" not in source


def test_pricing_page_no_longer_embeds_delivery_archives():
    template = _read("app/templates/admin/pricing.html")
    admin_source = _read("app/routes/admin.py")
    pricing_body = _function_body(admin_source, "pricing_settings")

    assert "archives-section" not in template
    assert "Archives livraison express" not in template
    assert "section='archives'" not in template
    assert "_archived_orders_context" not in admin_source
    assert "archives_context" not in pricing_body


def test_product_detail_does_not_query_unused_reviews_collection():
    source = _read("app/routes/shop.py")
    body = _function_body(source, "product_detail")

    assert "Review.query" not in body
    assert "reviews=reviews" not in body
    assert "avg=avg" not in body


def test_static_assets_override_flask_no_cache_header_for_versioned_urls():
    source = _read("app/__init__.py")

    assert 'response.headers["Cache-Control"] = cache_control' in source
    assert 'response.headers.setdefault("Cache-Control"' not in source
    assert 'versioned = bool(request.args.get("v"))' in source
    assert '"STATIC_UNVERSIONED_CACHE_MAX_AGE"' in source
    assert 'cache_control += ", immutable"' in source
