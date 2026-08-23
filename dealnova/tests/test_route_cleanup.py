from collections import defaultdict
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_registered_routes_do_not_overlap_exact_path_and_method():
    try:
        from dealnova.app import create_app
    except ModuleNotFoundError as exc:
        pytest.skip(f"create_app dependency missing: {exc}")

    app = create_app()
    overlaps = defaultdict(list)
    rules = list(app.url_map.iter_rules())

    for index, first in enumerate(rules):
        first_methods = first.methods - {"HEAD", "OPTIONS"}
        for second in rules[index + 1 :]:
            if first.rule != second.rule:
                continue
            common_methods = sorted(first_methods & (second.methods - {"HEAD", "OPTIONS"}))
            if common_methods:
                overlaps[(first.rule, tuple(common_methods))].append(
                    f"{first.endpoint} overlaps {second.endpoint}"
                )

    assert dict(overlaps) == {}


def test_admin_legacy_redirects_target_existing_dashboard_endpoint():
    source = _read("app/routes/admin_users.py")

    assert 'url_for("admin.dashboard")' not in source
    assert 'url_for("admin_users.admin_dashboard")' in source


def test_admin_delete_shop_deletes_vendor_account_when_last_shop():
    source = _read("app/routes/admin_users.py")
    start = source.index("def delete_shop(")
    next_route = source.find("\n\n@bp.route", start + 1)
    body = source[start: next_route if next_route != -1 else len(source)]

    assert "vendor_has_other_shops" in body
    assert "Shop.query.filter(Shop.vendor_id == vendor.id, Shop.id != shop.id).first()" in body
    assert "_cleanup_user_dependencies_for_delete(vendor, linked_shop=shop)" in body
    assert "db.session.delete(vendor)" in body
    assert "db.session.delete(shop)" in body
    assert "vendor_user_deleted" in body
    assert "Boutique {shop.name} et compte vendeur supprimés" in body
    assert "Boutique {shop.name} supprimée" in body


def test_dead_route_helpers_and_imports_are_removed():
    api_source = _read("app/routes/api.py")
    cart_source = _read("app/routes/cart.py")
    shop_source = _read("app/routes/shop.py")
    vendor_source = _read("app/routes/vendor.py")

    assert "def _legacy_active_promo_map(" not in api_source
    assert "def _legacy_cart_total(" not in api_source
    assert "from ..models.promo import Promo" not in api_source
    assert "prix_final," not in api_source

    assert "from functools import lru_cache" not in cart_source
    assert "from sqlalchemy.orm import load_only, selectinload" not in cart_source
    assert "def _phone_candidates(" not in cart_source
    assert "def _recent_checkout_url(" not in cart_source
    assert "def calculate_cart_total(" not in cart_source
    assert '"message": "Produit ajout' not in cart_source

    assert "location_featured_exists_expr" not in shop_source
    assert "product_featured_exists_expr" not in shop_source

    assert "SHOP_TYPE_ORDER" not in vendor_source
    assert "normalize_shop_type" not in vendor_source
    assert "from slugify import slugify" not in vendor_source
    assert "from sqlalchemy import or_, and_, case, text" not in vendor_source
    assert "def _product_delete_denied(" not in vendor_source
    assert "def _has_active_order_for_product(" not in vendor_source
