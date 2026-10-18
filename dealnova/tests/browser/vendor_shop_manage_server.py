"""Disposable shop-management browser fixture; no developer .env/database/media."""

from pathlib import Path
import json
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from flask import jsonify, request, send_from_directory, session
from werkzeug.serving import WSGIRequestHandler, make_server
from dealnova.tests.test_owner_location_modal import isolated_owner_application


class QuietPreviewHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        """Keep fixture output focused on app errors and the startup marker."""


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="babamarket-shop-manage-") as directory:
        with isolated_owner_application(Path(directory)) as fixture:
            from PIL import Image
            from dealnova.app.models.shop import Shop
            from dealnova.app.models.vendor_change_request import VendorChangeRequest

            app = fixture.app
            app.config["TEMPLATES_AUTO_RELOAD"] = True
            app.jinja_env.auto_reload = True
            for filename in ("shop-seed.webp", "shop-seed_thumb.webp", "shop-seed_medium.webp"):
                Image.new("RGB", (240, 180), "#d4e6dc").save(fixture.uploads / filename, "WEBP")

            def preview_static(filename):
                if filename.startswith("uploads/rentals/"):
                    return send_from_directory(str(fixture.static), filename)
                if filename.startswith("uploads/"):
                    return send_from_directory(str(fixture.uploads), filename[len("uploads/"):])
                return send_from_directory(str(fixture.source_static), filename)

            app.view_functions["static"] = preview_static

            def shop_fixture():
                session["_user_id"] = str(fixture.ids.vendor)
                session["_fresh"] = True
                variant = request.args.get("variant", "mixed")
                allowed = {"mixed": ["products", "services", "location"],
                           "products": ["products"], "services": ["services"],
                           "location": ["location"]}
                if variant not in allowed:
                    return jsonify(error="Invalid synthetic variant"), 400
                shop = fixture.db.session.get(Shop, fixture.ids.shop)
                if request.args.get("reset", "1") == "1":
                    for filename in ("shop-seed.webp", "shop-seed_thumb.webp", "shop-seed_medium.webp"):
                        if not (fixture.uploads / filename).is_file():
                            Image.new("RGB", (240, 180), "#d4e6dc").save(fixture.uploads / filename, "WEBP")
                    fixture.db.session.query(VendorChangeRequest).delete(synchronize_session=False)
                    shop.primary_type = allowed[variant][0]
                    shop.allowed_types_json = json.dumps(allowed[variant])
                    shop.name = "Boutique Moctar Express"
                    shop.description = "\u00c9picerie africaine et plats maison."
                    shop.logo = "shop-seed.webp"
                    shop.contact_phone = "+212612345678"
                    shop.contact_email = "boutique@example.test"
                    shop.address = "Hay Riad, Rabat"
                    shop.service_location_note = "En face de la pharmacie"
                    shop.service_latitude = 33.9564
                    shop.service_longitude = -6.8699
                    shop.is_active = True
                    shop.is_open = True
                    fixture.db.session.commit()
                return jsonify(shop=shop.id, name=shop.name, description=shop.description,
                               contact_phone=shop.contact_phone, contact_email=shop.contact_email,
                               address=shop.address, note=shop.service_location_note,
                               latitude=shop.service_latitude, longitude=shop.service_longitude,
                               logo=shop.logo, is_active=shop.is_active, is_open=shop.is_open,
                               requests=VendorChangeRequest.query.filter_by(shop_id=shop.id).count(),
                               variant=variant, temporary=directory)

            # A fixture-only namespace exempt from both real vendor login and
            # private-mode guards, allowing setup and state reads alike.
            app.add_url_rule("/__shop_manage_fixture__", "shop_fixture.static", shop_fixture)
            port = int(os.environ.get("SHOP_MANAGE_PREVIEW_PORT", "5077"))
            with make_server("127.0.0.1", port, app, threaded=True, request_handler=QuietPreviewHandler) as server:
                print(f"SHOP_MANAGE_READY http://127.0.0.1:{port} temporary={directory}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
