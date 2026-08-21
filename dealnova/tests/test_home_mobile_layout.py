from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _home_css() -> str:
    return (ROOT / "app/static/css/home_shell.css").read_text(encoding="utf-8-sig")


def _mobile_home_block(css: str) -> str:
    start = css.index("@media (max-width: 768px)")
    next_media = css.index("@media (max-width: 480px)", start)
    return css[start:next_media]


def _home_template() -> str:
    return (ROOT / "app/templates/home.html").read_text(encoding="utf-8-sig")


def test_home_mobile_product_actions_keep_ctas_balanced():
    mobile_css = _mobile_home_block(_home_css())

    assert ".product-actions" in mobile_css
    assert "margin-top: 0.65rem;" in mobile_css
    assert "gap: 0.45rem;" in mobile_css
    assert ".product-actions .add-to-cart-form" in mobile_css
    assert "display: flex !important;" in mobile_css
    assert ".product-actions .btn-detail" in mobile_css
    assert ".product-actions .btn-cart" in mobile_css
    assert ".product-actions .btn-book" in mobile_css
    assert "flex: 0 0 auto;" in mobile_css
    assert "min-height: 44px;" in mobile_css


def test_home_product_actions_keep_cta_columns_uniform_across_item_types():
    css = _home_css()

    assert ".products-grid {" in css
    assert "align-items: stretch;" in css
    assert ".product-price-container {" in css
    assert "min-height: 2.35rem;" in css
    assert ".product-actions {" in css
    assert "align-items: stretch;" in css
    assert ".product-actions .add-to-cart-form {" in css
    assert "flex: 1 1 0;" in css
    assert ".product-actions .add-to-cart-form .btn-cart {" in css
    assert "width: 100%;" in css
    assert ".btn-book {" in css
    assert "border-radius: 14px;" in css


def test_home_universe_promotions_replaces_delivery_and_header_promo_cta_removed():
    template = _home_template()
    css = _home_css()

    assert "class=\"universe-card promotions reveal\"" in template
    assert "url_for('shop.promotions')" in template
    assert "Promotions du moment" not in template
    assert "url_for('shop.delivery_whatsapp_loader'" not in template
    assert ".universe-card.promotions .universe-icon" in css
    assert ".universe-card.delivery .universe-icon" not in css
