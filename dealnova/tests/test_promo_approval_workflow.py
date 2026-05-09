from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _function_body(source: str, function_name: str) -> str:
    marker = f"def {function_name}("
    start = source.index(marker)
    next_route = source.find("\n@bp.route", start + len(marker))
    return source[start : next_route if next_route != -1 else len(source)]


def test_promo_model_has_approval_status_and_audit_fields():
    source = _read("app/models/promo.py")

    assert "STATUS_PENDING = \"pending\"" in source
    assert "STATUS_APPROVED = \"approved\"" in source
    assert "status = db.Column" in source
    assert "review_note = db.Column" in source
    assert "reviewed_by_id = db.Column" in source
    assert "created_at = db.Column" in source
    assert "is_publicly_active" in source


def test_public_pricing_only_uses_approved_promos():
    pricing = _read("app/services/pricing.py")
    feed = _read("app/services/marketplace_feed.py")
    api = _read("app/routes/api.py")
    shops = _read("app/routes/shops.py")

    assert "Promo.status == Promo.STATUS_APPROVED" in pricing
    assert "Promo.status == Promo.STATUS_APPROVED" in feed
    assert "Promo.status == Promo.STATUS_APPROVED" in api
    assert "Promo.status == Promo.STATUS_APPROVED" in shops


def test_vendor_promo_submit_creates_pending_unless_shop_is_trusted():
    source = _read("app/routes/vendor.py")
    body = _function_body(source, "product_promotion")

    assert "PROMO_MAX_ACTIVE_PER_SHOP = 5" in source
    assert "PROMO_MAX_DURATION_DAYS = 14" in source
    assert "PROMO_MIN_PERCENT = 5" in source
    assert "shop.promo_trusted" in body
    assert "Promo.STATUS_APPROVED if shop.promo_trusted else Promo.STATUS_PENDING" in body
    assert "promotion envoyée à l'admin" in body.lower()


def test_admin_has_promo_review_routes_and_menu_entry():
    admin_source = _read("app/routes/admin.py")
    admin_menu = _read("app/templates/admin/base.html")
    template = _read("app/templates/admin/promo_reviews.html")

    assert "@bp.route(\"/promotions\")" in admin_source
    assert "def promo_reviews(" in admin_source
    assert "def promo_approve(" in admin_source
    assert "def promo_reject(" in admin_source
    assert "Promo.STATUS_PENDING" in admin_source
    assert "Shop.promo_trusted" in admin_source
    assert "url_for('admin.promo_reviews')" in admin_menu
    assert "Promotions" in template


def test_admin_promo_review_page_uses_plain_french_guidance():
    template = _read("app/templates/admin/promo_reviews.html")

    assert "A faire maintenant" in template
    assert "Regardez la remise, la boutique et la date de fin" in template
    assert "A traiter" in template
    assert "Accepter la promotion" in template
    assert "Faire confiance a cette boutique" in template
    assert "{{ promo.status }}" not in template


def test_runtime_migration_adds_promo_workflow_columns():
    source = _read("app/services/migration.py")
    app_source = _read("app/__init__.py")

    assert "ensure_promo_workflow_columns" in source
    assert "ALTER TABLE \"promo\" ADD COLUMN status" in source
    assert "ALTER TABLE \"shop\" ADD COLUMN promo_trusted" in source
    assert "ensure_promo_workflow_columns()" in app_source
