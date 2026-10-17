"""Layout contracts for the current homepage, alongside browser/home_responsive.cjs."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", css)
    assert match, selector
    return match.group(1)


def _mobile_css() -> str:
    css = _read("app/static/css/home_refresh.css")
    return css.split("@media (max-width: 768px)", 1)[1].split("@media", 1)[0]


def test_current_home_uses_the_responsive_stylesheet_and_six_category_grid():
    template = _read("app/templates/home.html")
    css = _read("app/static/css/home_refresh.css")

    assert "filename='css/home_refresh.css'" in template
    assert "repeat(6, minmax(0, 1fr))" in _rule(css, ".hub-categories")
    assert "repeat(3, minmax(0, 1fr))" in _rule(_mobile_css(), ".hub-categories")
    assert "min-width: 0;" in _rule(css, ".hub-category")


def test_current_home_fills_desktop_without_a_fixed_minimum_width():
    css = _read("app/static/css/home_refresh.css")

    for selector in (".hub-header-inner", ".hub-desktop-nav", ".hub-page-content"):
        rule = _rule(css, selector)
        assert "width: 100%;" in rule
        assert "max-width: none;" in rule
        assert "min-width: 0;" in rule

    assert "minmax(0, 1fr)" in _rule(_mobile_css(), ".hub-header-inner")


def test_mobile_navigation_and_category_labels_keep_touch_targets_usable():
    css = _mobile_css()
    labels = _rule(css, ".hub-category-label")
    navigation = _rule(css, ".hub-bottom-nav")
    actions = _rule(css, ".hub-bottom-nav > :is(a, button)")

    assert "min-height: 44px;" in labels
    assert "position: fixed;" in navigation
    assert "repeat(4, 1fr)" in navigation
    assert "safe-area-inset-bottom" in navigation
    assert "min-height: 49px;" in actions
    assert "safe-area-inset-bottom" in css.split(".hub-header-inner", 1)[0]


def test_shared_layout_no_longer_loads_disabled_home_tabs():
    base = _read("app/templates/base.html")

    assert "home_tabs_enabled" not in base
    assert "ui_home_tabs" not in base
    assert "has-home-tabs" not in base
