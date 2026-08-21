from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _shops_css() -> str:
    return (ROOT / "app/static/css/pages/shops_page.css").read_text(encoding="utf-8-sig")


def _rule_block(css: str, selector: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(selector)}\s*\{{", css)
    assert match, f"Missing CSS rule for {selector}"
    open_brace = css.index("{", match.start())
    close_brace = css.index("}", open_brace)
    return css[open_brace + 1:close_brace]


def test_shop_cards_keep_visit_button_aligned_to_card_bottom():
    css = _shops_css()

    card_block = _rule_block(css, ".shop-card")
    content_block = _rule_block(css, ".shop-card-content")
    visit_block = _rule_block(css, ".shop-visit-btn")

    assert "display: flex;" in card_block
    assert "flex-direction: column;" in card_block
    assert "display: flex;" in content_block
    assert "flex-direction: column;" in content_block
    assert "flex: 1 1 auto;" in content_block
    assert "margin-top: auto;" in visit_block


def test_shop_stat_counts_stay_centered_in_responsive_columns():
    css = _shops_css()

    stats_block = _rule_block(css, ".shop-stats")
    stat_item_block = _rule_block(css, ".stat-item")
    stat_number_block = _rule_block(css, ".stat-number")
    stat_label_block = _rule_block(css, ".stat-label")

    assert "align-items: stretch;" in stats_block
    assert "grid-auto-rows: 1fr;" in stats_block
    assert ".shop-stats.cols-1 { grid-template-columns: minmax(0, 1fr); }" in css
    assert ".shop-stats.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in css
    assert ".shop-stats.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }" in css
    assert "display: flex;" in stat_item_block
    assert "flex-direction: column;" in stat_item_block
    assert "align-items: center;" in stat_item_block
    assert "justify-content: center;" in stat_item_block
    assert "min-width: 0;" in stat_item_block
    assert "font-variant-numeric: tabular-nums;" in stat_number_block
    assert "line-height: 1;" in stat_number_block
    assert "white-space: nowrap;" in stat_label_block
    assert "overflow: hidden;" in stat_label_block
    assert "text-overflow: ellipsis;" in stat_label_block

    compact_media = css[css.index("@media (max-width: 400px)"):]
    assert ".shop-stats.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }" in compact_media


def test_shop_name_zone_keeps_stable_height_with_long_titles():
    css = _shops_css()

    name_block = _rule_block(css, ".shop-name")
    name_link_block = _rule_block(css, ".shop-name a")

    assert "line-height: 1.25;" in name_block
    assert "min-height: 2.5em;" in name_block
    assert "max-height: 2.5em;" in name_block
    assert "overflow: hidden;" in name_block
    assert "display: -webkit-box;" in name_link_block
    assert "-webkit-line-clamp: 2;" in name_link_block
    assert "-webkit-box-orient: vertical;" in name_link_block
    assert "overflow-wrap: anywhere;" in name_link_block
