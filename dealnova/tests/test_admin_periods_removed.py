from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start : next_route if next_route != -1 else len(source)]


def test_admin_period_routes_and_models_are_removed():
    admin_source = _read("app/routes/admin.py")
    admin_users_source = _read("app/routes/admin_users.py")
    rentals_source = _read("app/routes/rentals.py")
    models_init = _read("app/models/__init__.py")

    combined = "\n".join([admin_source, admin_users_source, rentals_source, models_init])
    forbidden = [
        "OrderPeriod",
        "VendorPeriod",
        "order_period",
        "vendor_period",
        "order_periods",
        "order_period_create",
        "order_period_close",
        "finance_period_open",
        "finance_period_close",
        "finance_period_delete",
        "_period_selection_from_request",
        "_orders_query_for_period",
        "period_bounds",
        "period_id",
        "selected_period",
    ]
    for token in forbidden:
        assert token not in combined

    assert not (ROOT / "app/models/order_period.py").exists()
    assert not (ROOT / "app/models/vendor_period.py").exists()
    assert not (ROOT / "app/services/order_periods.py").exists()
    assert not (ROOT / "app/services/financial_periods.py").exists()


def test_admin_templates_use_date_filters_not_periods():
    template_paths = [
        "app/templates/admin/base.html",
        "app/templates/admin/dashboard.html",
        "app/templates/admin/deliveries.html",
        "app/templates/admin/deliveries_archives.html",
        "app/templates/admin/finance.html",
        "app/templates/admin/locations.html",
        "app/templates/admin/pricing.html",
        "app/templates/admin/product_contacts.html",
        "app/templates/admin/reconciliation.html",
    ]
    combined = "\n".join(_read(path) for path in template_paths)

    forbidden = [
        "Periodes",
        "Periode",
        "période",
        "periode",
        "period_id",
        "selected_period",
        "open_period",
        "closed_periods",
        "periods-section",
        "admin.order_periods",
        "admin.order_period_create",
        "admin.order_period_close",
        "admin.finance_period",
    ]
    for token in forbidden:
        assert token not in combined

    for label in ["Aujourd'hui", "Ce mois", "Cette annee", "Dates"]:
        assert label in combined
    assert 'name="range"' in combined
    assert 'value="today"' in combined
    assert 'value="month"' in combined
    assert 'value="year"' in combined
    assert 'value="custom"' in combined


def test_finance_records_without_open_period_requirement():
    service = _read("app/services/finance_entries.py")
    financial_model = _read("app/models/financial.py")

    assert "get_open_order_period" not in service
    assert "Aucune periode" not in service
    assert "period_id" not in service
    assert "FinancialPeriod" not in financial_model
    assert "period_id" not in financial_model


def test_finance_dashboard_contacts_subscriptions_locations_delivery_use_date_ranges():
    admin_source = _read("app/routes/admin.py")
    admin_users_source = _read("app/routes/admin_users.py")
    rentals_source = _read("app/routes/rentals.py")

    for function_name in ["product_contacts", "deliveries", "deliveries_live", "deliveries_archives", "finance"]:
        body = _function_body(admin_source, function_name)
        assert "resolve_date_filter" in body
        assert "date_filter.start_at" in body
        assert "date_filter.end_at" in body
        assert "period_id" not in body

    reconciliation_body = _function_body(admin_users_source, "reconciliation")
    assert "resolve_date_filter" in reconciliation_body
    assert "SubscriptionPayment" in reconciliation_body
    assert "date_filter.start_at" in reconciliation_body
    assert "period_id" not in reconciliation_body

    locations_body = _function_body(rentals_source, "admin_locations")
    assert "resolve_date_filter" in locations_body
    assert "RentalArchive" in locations_body
    assert "date_filter.start_at" in locations_body
    assert "period_id" not in locations_body


def test_migration_drops_admin_period_tables_and_columns():
    migration = _read("migrations/versions/d1e2f3a4b5c6_remove_admin_periods.py")

    assert 'drop_table("order_period")' in migration
    assert 'drop_table("vendor_period")' in migration
    assert 'drop_table("financial_period")' in migration
    assert '"period_id"' in migration
    assert '"order"' in migration
    assert '"vendor_receipt"' in migration
    assert '"financial_entry"' in migration
