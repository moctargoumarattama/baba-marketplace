from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start: next_route if next_route != -1 else len(source)]


def test_admin_confirm_order_route_is_removed():
    source = _read("app/routes/admin.py")

    assert "def confirm_order(" not in source
    assert '"/orders/<int:order_id>/confirm"' not in source
    assert "def set_order_claimable(" not in source
    assert '"/orders/<int:order_id>/set-claimable"' not in source


def test_vendor_earnings_no_longer_depends_on_vendor_payouts():
    source = _read("app/routes/vendor.py")
    body = _function_body(source, "earnings")

    assert "VendorPayout.query" not in body
    assert "payout_map" not in body


def test_vendor_earnings_template_tracks_direct_receipts_not_payout_claims():
    template = _read("app/templates/vendor/earnings.html")

    assert "vendor.claim_payout" not in template
    assert "vendor.confirm_receipt" in template
    assert "En attente admin" not in template


def test_vendor_periods_and_security_removed_from_vendor_interface():
    base_template = _read("app/templates/base.html")
    dashboard_template = _read("app/templates/vendor/dashboard.html")
    earnings_template = _read("app/templates/vendor/earnings.html")
    page_loader = _read("app/static/js/core/page_loader_client.js")

    assert not (ROOT / "app/templates/vendor/periods.html").exists()
    assert not (ROOT / "app/templates/vendor/security.html").exists()
    assert not (ROOT / "app/templates/vendor/period_close_confirm.html").exists()
    assert "vendor.periods" not in base_template
    assert "vendor.security" not in base_template
    assert "vendor.periods" not in dashboard_template
    assert "vendor.periods" not in earnings_template
    assert "vendor.security" not in earnings_template
    assert "vendor.periods" not in page_loader
    assert "vendor.security" not in page_loader


def test_vendor_earnings_no_longer_requires_open_period():
    source = _read("app/routes/vendor.py")
    body = _function_body(source, "earnings")
    confirm_body = _function_body(source, "confirm_receipt")

    assert "_require_open_sales_period" not in body
    assert "_get_open_period" not in body
    assert "VendorPeriod.query" not in body
    assert "selected_period" not in body
    assert 'url_for("vendor.periods")' not in body
    assert 'url_for("vendor.periods")' not in confirm_body
    assert "period_id" not in confirm_body


def test_vendor_earnings_has_day_month_year_filters():
    template = _read("app/templates/vendor/earnings.html")
    source = _read("app/routes/vendor.py")
    body = _function_body(source, "earnings")

    assert 'name="range"' in template
    assert 'value="today"' in template
    assert 'value="month"' in template
    assert 'value="year"' in template
    assert "Aujourd'hui" in template
    assert "Ce mois" in template
    assert "Cette année" in template
    assert "range_filter" in body


def test_vendor_earnings_paginates_with_sql_instead_of_memory_lists():
    source = _read("app/routes/vendor.py")
    body = _function_body(source, "earnings")
    before_paginate = body.split("pagination = ", 1)[0]

    assert ".all()" not in before_paginate
    assert "order_amounts_subquery" in body
    assert "receipt_order_subquery" in body
    assert ".outerjoin(receipt_order_subquery" in body
    assert ".paginate(page=page, per_page=30" in body
    assert "order_ids = list(order_amount_map.keys())" not in body
    assert "Order.id.in_(list_ids" not in body


def test_admin_order_detail_hides_vendor_payout_block_for_product_orders():
    template = _read("app/templates/admin/order_detail.html")

    assert "Paiements vendeurs" not in template
    assert "Débloquer paiement vendeur" not in template


def test_finance_labels_distinguish_subscriptions_location_and_other_revenue():
    finance_template = _read("app/templates/admin/finance.html")
    admin_source = _read("app/routes/admin.py")

    assert "Abonnements" in finance_template
    assert "Commission location" in finance_template
    assert "Livraison express" in finance_template
    assert "Commission produit" not in finance_template
    assert "Commission service" not in finance_template
    assert "Livraison (Part Baba)" not in admin_source


def test_admin_reconciliation_no_longer_exposes_vendor_payout_actions():
    source = _read("app/routes/admin_users.py")
    template = _read("app/templates/admin/reconciliation.html")

    assert "VendorPayout" not in source
    assert "def mark_vendor_paid(" not in source
    assert "mark-paid/<int:payout_id>" not in source
    assert "admin_users.mark_vendor_paid" not in template
