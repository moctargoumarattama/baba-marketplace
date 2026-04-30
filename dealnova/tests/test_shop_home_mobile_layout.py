from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _shop_home_css() -> str:
    return (ROOT / "app/static/css/pages/shop_home_page.css").read_text(
        encoding="utf-8-sig"
    )


def _mobile_product_block(css: str) -> str:
    start = css.index("@media (max-width: 768px)")
    end = css.index("@media (max-width: 576px)", start)
    return css[start:end]


def test_mobile_product_actions_keep_view_and_cart_tightly_stacked():
    mobile_css = _mobile_product_block(_shop_home_css())

    assert ".product-actions-compact" in mobile_css
    assert "margin-top: 0.65rem;" in mobile_css
    assert "gap: 0.45rem;" in mobile_css
    assert ".product-actions-compact .add-to-cart-form" in mobile_css
    assert "display: flex !important;" in mobile_css
    assert "width: 100%;" in mobile_css
    assert "flex: 0 0 auto;" in mobile_css


def test_shop_home_mobile_keeps_only_one_floating_navigation_control():
    template = (ROOT / "app/templates/shop/home.html").read_text(
        encoding="utf-8-sig"
    )
    css = _shop_home_css()
    script = (ROOT / "app/static/js/pages/shop_home_page.js").read_text(
        encoding="utf-8-sig"
    )

    assert 'id="floatingPaginationNav"' in template
    assert 'id="mobileClearFloat"' not in template
    assert 'id="pageBadge"' not in template
    assert ".floating-pagination-nav" in css
    assert ".mobile-clear-float" not in css
    assert ".page-badge" not in css
    assert "mobileClearBtn" not in script
    assert "updatePageBadge" not in script
