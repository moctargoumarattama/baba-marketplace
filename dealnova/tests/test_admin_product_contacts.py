from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start: next_route if next_route != -1 else len(source)]


def test_product_contact_lead_model_exists_for_whatsapp_tracking():
    source = _read("app/models/product_contact_lead.py")

    assert "class ProductContactLead" in source
    assert "__tablename__ = \"product_contact_lead\"" in source
    assert "product_summary_json" in source
    assert "source" in source


def test_cart_checkout_records_product_contact_leads_without_orders_or_payouts():
    source = _read("app/routes/cart.py")
    body = _function_body(source, "whatsapp_checkout")

    assert "record_product_contact_leads(" in body
    assert "Order(" not in body
    assert "VendorPayout" not in body


def test_admin_has_read_only_product_contacts_page():
    source = _read("app/routes/admin.py")
    body = _function_body(source, "product_contacts")

    assert "@bp.route(\"/product-contacts\")" in source
    assert "ProductContactLead" in body
    assert "render_template(\"admin/product_contacts.html\"" in body
    assert "db.session.add" not in body
    assert "update(" not in body
    assert "delete(" not in body


def test_admin_menu_keeps_product_contacts_and_dedicated_deliveries_entry():
    template = _read("app/templates/admin/base.html")

    assert "url_for('admin.product_contacts')" in template
    assert "<span>Contacts produits</span>" in template
    assert "url_for('admin.all_orders')" not in template
    assert "<span>Commandes</span>" not in template
    assert "url_for('admin.deliveries')" in template
    assert "<span>Livraisons</span>" in template


def test_product_contacts_template_has_no_operational_actions():
    template = _read("app/templates/admin/product_contacts.html")

    assert "Contacts WhatsApp produits" in template
    assert "Confirmer" not in template
    assert "Assigner" not in template
    assert "Paiement vendeur" not in template
    assert "Payout" not in template
    assert "Commission produit" not in template


def test_legacy_product_order_pages_are_removed_instead_of_hidden():
    admin_source = _read("app/routes/admin.py")
    all_orders_body = _function_body(admin_source, "all_orders")

    assert not (ROOT / "app/templates/admin/all_orders.html").exists()
    assert "render_template" not in all_orders_body
    assert "Order." not in all_orders_body
    assert "admin.product_contacts" in all_orders_body
    assert "def orders_live(" not in admin_source
    assert "def orders_notifications(" not in admin_source
    assert 'url_for("admin.orders_notifications"' not in _read("app/templates/admin/base.html")
