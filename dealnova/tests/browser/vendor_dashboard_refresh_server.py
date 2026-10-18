"""Disposable dashboard preview, never imports the developer run.py or .env."""

from datetime import datetime, timedelta
from pathlib import Path
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from flask import jsonify, request, send_from_directory, session
from werkzeug.serving import make_server
from dealnova.tests.test_owner_location_modal import isolated_owner_application


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="babamarket-dashboard-refresh-") as directory:
        with isolated_owner_application(Path(directory), seed=True) as fixture:
            from dealnova.app.models.booking import Booking
            from dealnova.app.models.order import Order, OrderItem
            from dealnova.app.models.product import Product
            from dealnova.app.models.shop import Shop
            from dealnova.app.routes.vendor import _DASHBOARD_ORDERS_LIVE_CACHE

            app = fixture.app
            app.config["TEMPLATES_AUTO_RELOAD"] = True
            app.jinja_env.auto_reload = True
            with app.app_context():
                product = Product(name="Produit de demonstration uniquement", kind="physical", price=25,
                                  stock=2, vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                                  category_id=fixture.ids.physical)
                service = Product(name="Service de demonstration uniquement", kind="service", price=120,
                                  stock=0, vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                                  category_id=fixture.ids.service)
                app_db = fixture.db
                app_db.session.add_all([product, service])
                app_db.session.flush()
                now = datetime.utcnow()
                for index in range(4):
                    order = Order(full_name=f"Client test {index + 1}", phone="0600000000", address="Rabat test",
                                  city="Rabat", status="pending", total=2500,
                                  created_at=now - (timedelta(days=62) if index == 0 else timedelta(minutes=index)))
                    app_db.session.add(order)
                    app_db.session.flush()
                    app_db.session.add(OrderItem(order_id=order.id, product_id=product.id, price=2500, quantity=1))
                app_db.session.add(Booking(product_id=service.id, shop_id=fixture.ids.shop,
                                           full_name="Rendez-vous de test", phone="0600000000",
                                           scheduled_for=now.replace(hour=14, minute=30), status="confirmed"))
                app_db.session.commit()

            def preview_static(filename):
                if filename.startswith("uploads/rentals/"):
                    return send_from_directory(str(fixture.static), filename)
                if filename.startswith("uploads/"):
                    return send_from_directory(str(fixture.uploads), filename[len("uploads/"):])
                return send_from_directory(str(fixture.source_static), filename)

            app.view_functions["static"] = preview_static

            def dashboard_fixture():
                session["_user_id"] = str(fixture.ids.vendor)
                session["_fresh"] = True
                variant = request.args.get("variant", "mixed")
                types = {"products": '["products"]', "services": '["services"]',
                         "mixed": '["products","services","location"]'}
                if variant not in types:
                    return jsonify(error="Invalid synthetic variant"), 400
                shop = fixture.db.session.get(Shop, fixture.ids.shop)
                shop.primary_type = "services" if variant == "services" else "products"
                shop.allowed_types_json = types[variant]
                shop.name = ("BoutiqueTresLongueSansEspace" * 3) if request.args.get("long") == "1" else "Boutique de test"
                shop.is_open = True
                shop.closed_until = None
                shop.closed_note = None
                fixture.db.session.commit()
                _DASHBOARD_ORDERS_LIVE_CACHE.clear()
                return jsonify(physical=fixture.ids.physical, service=fixture.ids.service, shop=fixture.ids.shop,
                               variant=variant, temporary=directory)

            app.add_url_rule("/__dashboard_refresh_fixture__", "dashboard_refresh_fixture", dashboard_fixture)
            port = int(os.environ.get("DASHBOARD_REFRESH_PREVIEW_PORT", "5075"))
            with make_server("127.0.0.1", port, app, threaded=True) as server:
                print(f"DASHBOARD_REFRESH_READY http://127.0.0.1:{port} temporary={directory}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
