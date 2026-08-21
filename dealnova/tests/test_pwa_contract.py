import ast
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def _png_size(relative_path: str) -> tuple[int, int]:
    raw = (ROOT / relative_path).read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", raw[16:24])


def _load_html_prefix_normalizer():
    source = _read("app/__init__.py")
    tree = ast.parse(source)
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_HTML_DOCUMENT_PREFIX_RE"
            for target in node.targets
        ):
            selected.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "_normalize_html_document_prefix":
            selected.append(node)

    namespace = {"re": re}
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(module, "app/__init__.py", "exec"), namespace)
    return namespace["_normalize_html_document_prefix"]


class _FakeResponse:
    def __init__(self, body: str, mimetype: str = "text/html"):
        self.body = body
        self.mimetype = mimetype
        self.direct_passthrough = False
        self.headers = {"Content-Length": str(len(body.encode("utf-8")))}

    def get_data(self, as_text=False):
        return self.body if as_text else self.body.encode("utf-8")

    def set_data(self, body):
        self.body = body


def test_html_response_removes_all_markers_before_doctype():
    normalize = _load_html_prefix_normalizer()
    response = _FakeResponse("\ufeff\ufeff\r\n  <!doctype html><html><head></head></html>")

    normalized = normalize(response)

    assert normalized.body.startswith("<!doctype html>")
    assert "Content-Length" not in normalized.headers


def test_html_response_normalizer_does_not_rewrite_fragments():
    normalize = _load_html_prefix_normalizer()
    response = _FakeResponse("\ufeff<div>Fragment AJAX</div>")

    normalized = normalize(response)

    assert normalized.body == "\ufeff<div>Fragment AJAX</div>"


def test_manifest_keeps_baba_market_brand_and_standalone_mode():
    manifest = json.loads(_read("app/static/manifest.json"))

    assert manifest["name"] == "Baba Market"
    assert manifest["short_name"] == "Baba Market"
    assert manifest["id"] == "/"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert "standalone" in manifest["display_override"]
    assert manifest["prefer_related_applications"] is False


def test_manifest_and_apple_icons_have_required_png_sizes():
    manifest = json.loads(_read("app/static/manifest.json"))
    icon_contract = {
        (icon["sizes"], icon["purpose"])
        for icon in manifest["icons"]
    }

    assert ("192x192", "any") in icon_contract
    assert ("512x512", "any") in icon_contract
    assert ("192x192", "maskable") in icon_contract
    assert ("512x512", "maskable") in icon_contract
    assert _png_size("app/static/android-chrome-192x192.png") == (192, 192)
    assert _png_size("app/static/android-chrome-512x512.png") == (512, 512)
    assert _png_size("app/static/apple-touch-icon.png") == (180, 180)


def test_public_layout_keeps_pwa_metadata_inside_head():
    template = _read("app/templates/base.html")
    head = template.split("<head>", 1)[1].split("</head>", 1)[0]

    assert "url_for('web_app_manifest')" in head
    assert 'name="application-name" content="Baba Market"' in head
    assert 'name="apple-mobile-web-app-capable" content="yes"' in head
    assert 'name="apple-mobile-web-app-title" content="Baba Market"' in head
    assert "url_for('apple_touch_icon')" in head


def test_install_button_only_uses_a_real_browser_prompt():
    script = _read("app/static/js/ui_shell.js")
    ui_block = script.split("function showSoftInstallUI()", 1)[1].split(
        "async function handleInstallClick()", 1
    )[0]
    unavailable_block = ui_block.split("if (!deferredInstallPrompt)", 1)[1].split("return;", 1)[0]
    click_block = script.split("async function handleInstallClick()", 1)[1].split(
        "function collectOnlineRequiredNodes()", 1
    )[0]

    assert "showPwaModal()" not in unavailable_block
    assert "closePwaBanner()" in unavailable_block
    assert "const installPrompt = deferredInstallPrompt" in click_block
    assert "await installPrompt.prompt()" in click_block
    assert "await installPrompt.userChoice" in click_block


def test_service_worker_fetches_manifest_from_network_and_owns_root_scope():
    worker = _read("app/static/sw.js")
    shell = _read("app/static/js/ui_shell.js")
    app_factory = _read("app/__init__.py")

    assert 'url.pathname === "/manifest.json"' in worker
    assert '.register(swUrl, { scope: "/", updateViaCache: "none" })' in shell
    assert 'response.headers["Service-Worker-Allowed"] = "/"' in app_factory
    assert 'response.mimetype = "application/manifest+json"' in app_factory
