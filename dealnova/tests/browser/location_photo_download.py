"""Check the real rental gallery and watermarked downloads using temporary data.

Run with Python containing the application dependencies and Playwright.
No production application, database or uploaded media are used.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY))

from dealnova.tests.test_location_photo_download import isolated_location_photos


@contextmanager
def fixture_server():
    """Snapshot Flask responses on the main thread; browser threads use bytes only."""
    with TemporaryDirectory(prefix="baba-location-photo-browser-") as directory:
        with isolated_location_photos(Path(directory)) as photos:
            detail_url = f"/location/{photos.listing.slug}"
            downloads = [f"{detail_url}/photo/{media.id}/download"
                         for media in (photos.first, photos.second)]
            paths = [detail_url, *downloads,
                     "/static/uploads/rentals/first.jpg",
                     "/static/uploads/rentals/second.png"]
            responses = {}
            for path in paths:
                response = photos.client.get(path)
                try:
                    assert response.status_code == 200, (path, response.status_code)
                    responses[path] = (response.data, response.mimetype,
                                       response.headers.get("Content-Disposition"))
                finally:
                    response.close()
            css = "/static/css/pages/public_listings_refresh.css"
            responses[css] = ((REPOSITORY / "dealnova/app" / css.lstrip("/")).read_bytes(),
                              "text/css", None)
            filenames = [f"baba-market-location-{photos.listing.id}-photo-{media.id}.jpg"
                         for media in (photos.first, photos.second)]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                response = responses.get(urlsplit(self.path).path)
                if response is None:
                    self.send_error(404)
                    return
                body, content_type, disposition = response
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                if disposition:
                    self.send_header("Content-Disposition", disposition)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield (f"http://127.0.0.1:{server.server_port}", detail_url, downloads,
                       filenames, [responses[path][0] for path in downloads])
            finally:
                server.shutdown()
                thread.join()


def run(browser_type, viewport, fixture):
    origin, detail_url, downloads, filenames, expected_bytes = fixture
    browser = browser_type.launch(headless=True)
    try:
        page = browser.new_page(viewport=viewport, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin + detail_url)
        button = page.locator("#listingPhotoDownload")
        thumbs = page.locator(".js-gallery-thumbs .thumb-btn")
        expect(thumbs).to_have_count(3)
        expect(button).to_be_visible()
        expect(button).to_have_attribute("href", downloads[0])
        expect(thumbs.nth(0)).to_have_attribute("aria-pressed", "true")
        bounds = button.bounding_box()
        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= viewport["width"]

        for index in (0, 1):
            if index:
                page.locator(".js-gallery-next").click()
            expect(button).to_have_attribute("href", downloads[index])
            expect(thumbs.nth(index)).to_have_attribute("aria-pressed", "true")
            with page.expect_download() as event:
                button.click()
            download = event.value
            assert download.url == origin + downloads[index]
            assert download.suggested_filename == filenames[index]
            assert download.failure() is None
            assert Path(download.path()).read_bytes() == expected_bytes[index]

        thumbs.nth(2).click()
        expect(page.locator(".js-gallery")).to_have_class("gallery-main js-gallery is-video-active")
        expect(button).to_be_hidden()
        assert button.get_attribute("href") is None, "Video must clear the previous photo URL"
        thumbs.nth(0).click()
        expect(button).to_be_visible()
        expect(button).to_have_attribute("href", downloads[0])
        expect(thumbs.nth(0)).to_have_attribute("aria-pressed", "true")
        assert not errors, errors
        print(f"{browser_type.name} {viewport['width']}px: real gallery / two watermarked downloads / video / return to photo PASS")
    finally:
        browser.close()


if __name__ == "__main__":
    with fixture_server() as fixture, sync_playwright() as playwright:
        for engine in (playwright.chromium, playwright.webkit):
            for width, height in ((390, 844), (1440, 1000)):
                run(engine, {"width": width, "height": height}, fixture)
