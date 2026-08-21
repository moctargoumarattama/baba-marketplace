from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_delivery_whatsapp_loader_uses_prefilled_message_link():
    source = _read("app/routes/shop.py")

    assert "def _delivery_whatsapp_prefill_message()" in source
    assert "DELIVERY_WHATSAPP_DEFAULT_MESSAGE" in source
    assert 'f"https://wa.me/{_delivery_whatsapp_number()}?text="' in source
    assert "quote(_delivery_whatsapp_prefill_message(), safe='')" in source


def test_delivery_whatsapp_default_message_configurable_in_single_config():
    config_source = _read("app/config.py")

    assert "DELIVERY_WHATSAPP_DEFAULT_MESSAGE" in config_source
    assert not (ROOT / "app" / "confprod.py").exists()
