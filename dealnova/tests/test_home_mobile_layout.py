from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _home_css() -> str:
    return (ROOT / "app/static/css/home_shell.css").read_text(encoding="utf-8-sig")


def _mobile_home_block(css: str) -> str:
    start = css.index("@media (max-width: 768px)")
    next_media = css.index("@media (max-width: 480px)", start)
    return css[start:next_media]


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
