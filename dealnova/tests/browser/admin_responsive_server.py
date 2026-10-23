"""Loopback-only admin preview using disposable SQLite and synthetic data.

This server never imports run.py, loads the developer .env, or touches production
users. Keep its authentication endpoint bound to localhost only.
"""

from pathlib import Path
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from flask import jsonify, session
from werkzeug.serving import WSGIRequestHandler, make_server
from dealnova.tests.test_vendor_product_modal import isolated_vendor_application


class QuietPreviewHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        """Leave exceptions visible without logging every static asset."""


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="babamarket-admin-responsive-") as directory:
        with isolated_vendor_application(Path(directory)) as fixture:
            from dealnova.app.models.product import Product
            from dealnova.app.models.shop import Shop
            from dealnova.app.models.user import User

            app = fixture.app
            app.config["TEMPLATES_AUTO_RELOAD"] = True
            app.jinja_env.auto_reload = True
            with app.app_context():
                admin = User(username="admin-responsive", email="admin-responsive@example.test",
                             role="admin", is_active=True, password_hash="fixture-no-login")
                fixture.db.session.add(admin)
                shop = fixture.db.session.get(Shop, fixture.ids.shop)
                shop.name = "BoutiqueSansEspacePourVerifierLeResponsive" * 4
                vendor = fixture.db.session.get(User, fixture.ids.vendor)
                vendor.username = "VendeurSansEspacePourVerifierLeResponsive" * 3
                fixture.db.session.add(Product(
                    name="ProduitSansEspacePourVerifierLeResponsive" * 4,
                    kind="physical", price=25, stock=1, is_active=True,
                    vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                    category_id=fixture.ids.physical,
                ))
                fixture.db.session.commit()
                admin_id = admin.id

            metrics = {
                "available": True, "orders_per_hour": 0,
                "conversions": {"visitors": 239, "add_to_cart": 0, "orders": 0, "whatsapp": 0},
                "hourly_heatmap": [{"hour": f"{hour:02d}h", "count": 0} for hour in range(24)],
            }
            metrics.update(
                active_clients_5m=12, active_internal_5m=2, active_guests_5m=12,
                active_authenticated_5m=2, active_visitors_5m=14,
                peak_active_today=18, rpm=78, page_views_today=1234,
                unique_visitors_today=241, unique_clients_today=239,
                unique_internal_today=2,
                top_pages=[{"label": "/", "count": 44}, {
                    "label": "/" + "CheminSansEspaceTresLongPourVerifierLeResponsive" * 4,
                    "count": 12345,
                }],
                sessions_by_role=[{"label": "guest", "count": 239},
                                  {"label": "admin", "count": 2}],
                active_authenticated_users=[{
                    "label": "AdministrateurSansEspacePourVerifierLeResponsive" * 4,
                    "audience_scope": "interne", "role": "admin", "device": "mobile",
                    "city": "Rabat", "path": "/admin/audience", "last_seen_seconds_ago": 3,
                }],
            )

            def admin_fixture():
                session["_user_id"] = str(admin_id)
                session["_fresh"] = True
                return jsonify(ok=True, temporary=True)

            # A static namespace bypasses public onboarding redirects solely in
            # this disposable preview application.
            app.add_url_rule("/__admin_responsive_fixture__", "admin_fixture.static", admin_fixture)
            port = int(os.environ.get("ADMIN_RESPONSIVE_PREVIEW_PORT", "5084"))
            with patch("dealnova.app.services.traffic_stats._redis_client", return_value=None), \
                    patch("dealnova.app.routes.admin_users.get_live_traffic_metrics", return_value=metrics):
                with make_server("127.0.0.1", port, app, threaded=True,
                                 request_handler=QuietPreviewHandler) as server:
                    print(f"ADMIN_RESPONSIVE_READY http://127.0.0.1:{port} temporary={directory}", flush=True)
                    try:
                        server.serve_forever()
                    except KeyboardInterrupt:
                        pass
