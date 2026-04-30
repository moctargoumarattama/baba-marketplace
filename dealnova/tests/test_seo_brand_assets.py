from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_base_head_exposes_stable_large_brand_icons():
    base = _read("app/templates/base.html")

    icon_lines = [
        line.strip()
        for line in base.splitlines()
        if 'rel="icon"' in line and "android-chrome" in line
    ]

    assert any("android-chrome-192x192.png" in line for line in icon_lines)
    assert any("android-chrome-512x512.png" in line for line in icon_lines)
    assert any('sizes="192x192"' in line for line in icon_lines)
    assert any('sizes="512x512"' in line for line in icon_lines)
    assert all("app_static_version" not in line for line in icon_lines)


def test_home_structured_data_uses_valid_baba_market_logo_signals():
    home = _read("app/templates/home.html")

    assert "Baba Market" in home
    assert "BabaMarket" in home
    assert "android-chrome-512x512.png" in home
    assert "SITE_LOGO" not in home
    assert '"@type": "OnlineStore"' in home
    assert '"@type": "WebSite"' in home
    assert '"@type": "ImageObject"' in home
    assert '"width": 512' in home
    assert '"height": 512' in home
    assert '"alternateName": ["BabaMarket", "Baba Market Maroc"]' in home


def test_structured_logo_asset_is_a_real_large_png():
    logo_path = ROOT / "app/static/android-chrome-512x512.png"

    with Image.open(logo_path) as logo:
        assert logo.format == "PNG"
        assert logo.size == (512, 512)


def test_legacy_logo_png_matches_its_file_extension():
    logo_path = ROOT / "app/static/logo.png"

    with Image.open(logo_path) as logo:
        assert logo.format == "PNG"
        assert logo.size[0] == logo.size[1]
        assert logo.size[0] >= 512
