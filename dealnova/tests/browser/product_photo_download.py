"""Browser regression using real gallery assets, synthetic HTML/data and no database.
Run with a Python environment containing Playwright; no production services are used.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit
from pathlib import Path
import re
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://photo-download.test"


def download_url(pid, index):
    return f"/shop/product/{pid}/photo/{index}/download"


def product(pid, *, images=None, video=False):
    images = images or []
    return dict(id=pid, name=f"Article {pid}", kind="physical", stock=2,
                price=25, final_price=20 if pid == 102 else 25, has_promo=pid == 102,
                promo_value=5, discount_amount=5, promo_type="fixed", description="Article de test",
                category="Test", shop=None, images=images,
                image_download_urls=[download_url(pid, i) for i in range(len(images))],
                video_url="/static/video.mp4" if video else "",
                whatsapp_order_url="https://wa.me/000", share_url=f"{ORIGIN}/shop/product/{pid}")


def modal_fixture():
    source = (ROOT / "app/templates/home.html").read_text(encoding="utf-8")
    source = source[source.index('<div class="u-modal-backdrop"'):]
    source = source[:source.index('<div class="u-modal-backdrop u-cart-backdrop"')]
    source = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", "", source, flags=re.S)
    return '<!doctype html><html><body data-page="landing">' + ''.join(
        f'<button id="open{pid}" data-open-product-detail="{pid}">Article {pid}</button>'
        for pid in (101, 102, 103)) + source + '</body></html>'


def run(browser_type, viewport):
    browser = browser_type.launch(headless=True)
    try:
        page = browser.new_page(viewport=viewport, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(ORIGIN + "/fixture")
        for stylesheet in ("ui_home_single_hub.css", "home_refresh.css", "catalog_panel.css", "promotion_highlight.css"):
            page.add_style_tag(content=(ROOT / "app/static/css" / stylesheet).read_text(encoding="utf-8"))
        page.add_script_tag(content=(ROOT / "app/static/js/ui_home_single_hub.js").read_text(encoding="utf-8"))
        page.locator("#open101").click()
        expect(page.locator("#pDetailContent")).to_be_visible()
        button = page.locator("#pDetailPhotoDownload")
        expect(button).to_be_hidden()
        assert button.get_attribute("href") is None, "video cannot download as photo"
        page.locator("#pDetailNavNext").click()
        expect(button).to_have_attribute("href", download_url(101, 0))
        expect(button).to_be_visible()
        expect(page.locator("#pDetailMainImg")).to_have_attribute("src", "/static/uploads/a.jpg")
        page.locator("#pDetailThumbs .u-pdetail-thumb").nth(2).click()
        expect(button).to_have_attribute("href", download_url(101, 1))
        with page.expect_download() as event:
            button.click()
        assert event.value.url == ORIGIN + download_url(101, 1)
        assert event.value.suggested_filename == "baba-market.jpg"
        assert event.value.failure() is None
        page.locator("#pDetailImgWrap").click()
        page.locator("#pDetailLightboxPrev").click()
        page.locator("#pDetailLightboxClose").click()
        expect(button).to_have_attribute("href", download_url(101, 0))
        expect(page.locator("#pDetailMainImg")).to_have_attribute("src", "/static/uploads/a.jpg")
        page.evaluate("document.querySelector('#open102').click()")
        expect(button).to_have_attribute("href", download_url(102, 0))
        expect(button).to_be_visible()
        promo = page.locator("#pDetailPromoBadge")
        expect(promo).to_be_visible()
        expect(promo).to_have_text("Promotion")
        assert promo.evaluate("element => getComputedStyle(element).color") == "rgb(237, 0, 40)"
        page.emulate_media(reduced_motion="no-preference")
        assert promo.evaluate("element => getComputedStyle(element).animationName") == "promotion-glow"
        page.emulate_media(reduced_motion="reduce")
        assert promo.evaluate("element => getComputedStyle(element).animationName") == "none"
        page.evaluate("document.querySelector('#open103').click()")
        expect(page.locator("#pDetailTitle")).to_have_text("Article 103")
        expect(button).to_be_hidden()
        assert button.get_attribute("href") is None, "placeholder cannot download previous product"
        assert not errors, errors
        print(f"{browser_type.name} {viewport['width']}px: modal / video / thumbnails / lightbox / download / product switching / promotion PASS")
    finally:
        browser.close()


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        content_type = "text/html; charset=utf-8"
        attachment = False
        if path.startswith("/api/product/"):
            pid = int(path.rsplit("/", 1)[1])
            fixtures = {101: product(101, images=["a.jpg", "b.jpg"], video=True),
                        102: product(102, images=["c.jpg"]), 103: product(103)}
            if pid == 102:
                fixtures[pid].pop("image_download_urls")  # Earlier API payloads must still show the button.
            body = json.dumps({"success": True, "product": fixtures[pid]}).encode()
            content_type = "application/json"
        elif path == "/cart/api/full":
            body = json.dumps({"success": True, "items": [], "shop_groups": [], "count": 0}).encode()
            content_type = "application/json"
        elif path.endswith("/download"):
            body = b"watermarked-test-file"
            content_type = "image/jpeg"
            attachment = True
        elif path.startswith("/static/js/"):
            body = (ROOT / "app" / path.lstrip("/")).read_bytes()
            content_type = "text/javascript"
        elif path.startswith("/static/"):
            body = b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="green"/></svg>'
            content_type = "image/svg+xml"
        else:
            body = modal_fixture().encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="baba-market.jpg"')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    with ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler) as server:
        ORIGIN = "http://127.0.0.1:" + str(server.server_port)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                run(playwright.chromium, {"width": 1440, "height": 1000})
                run(playwright.webkit, {"width": 390, "height": 844})
        finally:
            server.shutdown()
            thread.join()
