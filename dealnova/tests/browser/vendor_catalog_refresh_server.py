"""Disposable catalogue browser fixture; never reads .env or developer data."""

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
    with tempfile.TemporaryDirectory(prefix="babamarket-catalog-refresh-") as directory:
        with isolated_owner_application(Path(directory)) as fixture:
            from PIL import Image
            from dealnova.app.models.category import Category
            from dealnova.app.models.product import Product
            from dealnova.app.models.promo import Promo
            from dealnova.app.models.shop import Shop

            app = fixture.app
            app.config["TEMPLATES_AUTO_RELOAD"] = True
            app.jinja_env.auto_reload = True
            with app.app_context():
                category = Category(name="DécorationMaisonEtAccessoires" * 3,
                                    slug="catalog-long-category", category_type="products")
                fixture.db.session.add(category)
                fixture.db.session.commit()
                long_category = category.id
            for filename in ("catalog-seed.webp", "catalog-seed_thumb.webp", "catalog-seed_medium.webp",
                             "catalog-seed_large.webp", "catalog-seed_300.webp", "catalog-seed_600.webp"):
                Image.new("RGB", (240, 180), "#d4e6dc").save(fixture.uploads / filename, "WEBP")

            def preview_static(filename):
                if filename.startswith("uploads/rentals/"):
                    return send_from_directory(str(fixture.static), filename)
                if filename.startswith("uploads/"):
                    return send_from_directory(str(fixture.uploads), filename[len("uploads/"):])
                return send_from_directory(str(fixture.source_static), filename)

            app.view_functions["static"] = preview_static

            def catalogue_fixture():
                session["_user_id"] = str(fixture.ids.vendor)
                session["_fresh"] = True
                variant = request.args.get("variant", "mixed")
                allowed = {"mixed": '["products","services","location"]',
                           "products": '["products"]', "services": '["services"]',
                           "empty": '["products","services"]'}
                if variant not in allowed:
                    return jsonify(error="Invalid synthetic variant"), 400
                shop = fixture.db.session.get(Shop, fixture.ids.shop)
                shop.primary_type = "services" if variant == "services" else "products"
                shop.allowed_types_json = allowed[variant]
                shop.name = "Boutique de test catalogue"
                if request.args.get("reset", "1") == "1":
                    fixture.db.session.query(Promo).delete(synchronize_session=False)
                    fixture.db.session.query(Product).delete(synchronize_session=False)
                    fixture.db.session.flush()
                    now = datetime.utcnow()
                    for index in range(60 if variant != "empty" else 0):
                        service = index % 3 == 1
                        name = f"Offre catalogue de test {index + 1:02d}"
                        description = "Description synthétique de démonstration."
                        if index == 52:
                            name = "Épices étoilées café noir"
                            description = "Poivre doux et épices pour le repas."
                        elif index == 51:
                            name = "Entretien canapé écologique"
                            description = "Nettoyage à domicile."
                        elif index == 59:
                            name = "NomTrèsLongSansEspace" * 7
                        fixture.db.session.add(Product(
                            name=name, description=description, kind="service" if service else "physical",
                            price=25 + index, stock=0 if service else 10, image_file="catalog-seed.webp",
                            vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                            category_id=fixture.ids.service if service else (long_category if index % 3 == 2 else fixture.ids.physical),
                            is_active=index != 3, created_at=now - timedelta(minutes=index + 1)))
                    fixture.db.session.add(Product(
                        name="Épices confidentielles propriétaire étranger", description="Ne doit jamais apparaître.",
                        kind="physical", price=10, stock=1, vendor_id=fixture.ids.foreign_owner,
                        shop_id=fixture.ids.foreign_shop, category_id=fixture.ids.physical))
                fixture.db.session.commit()
                owned = Product.query.filter_by(vendor_id=fixture.ids.vendor).order_by(Product.id).all()
                target = next((product for product in owned if product.name == "Épices étoilées café noir"), None)
                return jsonify(
                    physical=fixture.ids.physical, service=fixture.ids.service, longCategory=long_category,
                    shop=fixture.ids.shop, owned=[product.id for product in owned], target=target.id if target else None,
                    variant=variant, total=len(owned), temporary=directory)

            app.add_url_rule("/__catalog_refresh_fixture__", "catalogue_fixture", catalogue_fixture)
            port = int(os.environ.get("CATALOG_REFRESH_PREVIEW_PORT", "5076"))
            with make_server("127.0.0.1", port, app, threaded=True) as server:
                print(f"CATALOG_REFRESH_READY http://127.0.0.1:{port} temporary={directory}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
