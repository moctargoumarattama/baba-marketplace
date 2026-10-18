"""Synthetic multi-type vendor preview, with rental writes isolated from real static.

From repository root:
  python dealnova/tests/browser/owner_location_modal_server.py
"""

from pathlib import Path
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from flask import jsonify, send_from_directory, session
from werkzeug.serving import make_server
from dealnova.tests.test_owner_location_modal import isolated_owner_application


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="babamarket-owner-modal-") as directory:
        with isolated_owner_application(Path(directory), seed=True) as fixture:
            app = fixture.app
            app.config["TEMPLATES_AUTO_RELOAD"] = True
            app.jinja_env.auto_reload = True

            def preview_static(filename):
                # Source files are served read-only. Every upload path resolves to
                # this preview's temporary media, including subsequent products.
                if filename.startswith("uploads/rentals/"):
                    return send_from_directory(str(fixture.static), filename)
                if filename.startswith("uploads/"):
                    return send_from_directory(str(fixture.uploads), filename[len("uploads/"):])
                return send_from_directory(str(fixture.source_static), filename)

            app.view_functions["static"] = preview_static

            def owner_modal_fixture():
                session["_user_id"] = str(fixture.ids.vendor)
                session["_fresh"] = True
                return jsonify(physical=fixture.ids.physical, service=fixture.ids.service,
                               shop=fixture.ids.shop, seeded=25)

            app.add_url_rule("/__owner_modal_fixture__", "owner_modal_fixture", owner_modal_fixture)
            app.add_url_rule("/__vendor_modal_fixture__", "vendor_modal_fixture", owner_modal_fixture)

            port = int(os.environ.get("OWNER_MODAL_PREVIEW_PORT", "5073"))
            with make_server("127.0.0.1", port, app, threaded=True) as server:
                print(f"OWNER_MODAL_PREVIEW_READY http://127.0.0.1:{port} temporary={directory}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
