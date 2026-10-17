"""Keep the offline shell synchronized with the active public interface."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "app/static/sw.js"


def _asset_lists():
    source = WORKER.read_text(encoding="utf-8-sig")
    precache = source.split("const PRECACHE_ASSETS = [", 1)[1].split("];", 1)[0]
    critical = source.split("const CRITICAL_STATIC_ASSETS = new Set([", 1)[1].split("]);", 1)[0]
    return [set(re.findall(r'"(/static/[^"?]+)"', block)) for block in (precache, critical)]


def test_every_precached_or_critical_static_asset_exists():
    precache, critical = _asset_lists()

    assert critical <= precache | {"/static/offline.html"}
    for asset in precache | critical:
        assert (ROOT / "app" / asset.lstrip("/")).is_file(), asset


def test_offline_shell_keeps_current_search_hero_and_catalogue_assets():
    precache, critical = _asset_lists()
    current_runtime = {
        "/static/js/home_refresh.js", "/static/js/home_hero.js",
        "/static/js/public_live_search.js", "/static/js/public_catalog.js",
        "/static/js/ui_home_single_hub.js", "/static/css/ui_home_single_hub.css",
        "/static/css/home_refresh.css", "/static/css/public_refresh.css",
        "/static/css/catalog_panel.css", "/static/css/ui_drawer_glass.css",
    }
    assert current_runtime <= precache & critical
    assert {
        "/static/images/logo-public.webp",
        "/static/images/home-refresh/hero.webp",
        "/static/images/home-refresh/categories.webp",
        "/static/images/home-refresh/services-multimetiers-v2.webp",
    } <= precache


def test_removed_home_assets_and_missing_drawer_css_are_not_cached():
    source = WORKER.read_text(encoding="utf-8-sig")
    for retired in ("home_shell", "ui_home_tabs", "/static/css/ui_drawer.css"):
        assert retired not in source
