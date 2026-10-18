"""Local preview with synthetic data; never starts the developer's run.py.

From repository root:
  python dealnova/tests/browser/vendor_product_modal_server.py
"""

from pathlib import Path
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from flask import jsonify, session
from werkzeug.serving import make_server
from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="babamarket-vendor-modal-") as directory:
        with isolated_vendor_application(Path(directory)) as fixture:
            app = fixture.app

            @app.get("/__vendor_modal_fixture__")
            def vendor_modal_fixture():
                session["_user_id"] = str(fixture.ids.vendor)
                session["_fresh"] = True
                return jsonify(physical=fixture.ids.physical, service=fixture.ids.service)

            port = int(os.environ.get("VENDOR_MODAL_PREVIEW_PORT", "5071"))
            with make_server("127.0.0.1", port, app, threaded=True) as server:
                print("VENDOR_MODAL_PREVIEW_READY http://127.0.0.1:" + str(port), flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
