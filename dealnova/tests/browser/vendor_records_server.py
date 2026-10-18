"""Loopback-only records fixture: synthetic money/orders, temporary SQLite/media."""

from datetime import datetime, timedelta
from pathlib import Path
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from flask import jsonify, request, send_from_directory, session
from werkzeug.serving import WSGIRequestHandler, make_server
from dealnova.tests.test_owner_location_modal import isolated_owner_application


class QuietPreviewHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        """Application exceptions remain visible; omit routine static access logs."""


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="babamarket-vendor-records-") as directory:
        with isolated_owner_application(Path(directory)) as fixture:
            from dealnova.app.models.order import Order, OrderItem
            from dealnova.app.models.product import Product
            from dealnova.app.models.rental import RentalArchive
            from dealnova.app.models.shop import Shop
            from dealnova.app.models.vendor_receipt import VendorReceipt

            app = fixture.app
            app.config["TEMPLATES_AUTO_RELOAD"] = True
            app.jinja_env.auto_reload = True
            owned_orders, owned_archives, amounts, baseline_receipts = [], [], {}, []
            target_order = target_archive = mixed_order = None
            now = datetime.utcnow()
            with app.app_context():
                shop = fixture.db.session.get(Shop, fixture.ids.shop)
                shop.name = "Boutique de test dossiers"
                shop.description = "Boutique synthetique de verification."
                shop.contact_email = "records@example.test"
                foreign_product = Product(name="SECRET_PRODUIT_AUTRE_VENDEUR", description="Confidentiel",
                                          kind="physical", price=888, stock=5, is_active=True,
                                          vendor_id=fixture.ids.foreign_owner, shop_id=fixture.ids.foreign_shop,
                                          category_id=fixture.ids.physical)
                own_service = Product(name="SERVICE_HORS_CAISSE", description="Prestation uniquement",
                                      kind="service", price=999, stock=0, is_active=True,
                                      vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                                      category_id=fixture.ids.service)
                fixture.db.session.add_all([foreign_product, own_service])
                fixture.db.session.flush()
                for index in range(40):
                    name = f"Article de caisse {index + 1:02d}"
                    if index == 0:
                        name += " NomTresLongSansEspace" * 6
                    elif index == 38:
                        name = "Safran dor\u00e9 \u00e9thiopien"
                    product = Product(name=name, description="Verification synthetique.", kind="physical",
                                      price=25 + index * 1.25, stock=10, is_active=True,
                                      vendor_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                                      category_id=fixture.ids.physical)
                    fixture.db.session.add(product)
                    fixture.db.session.flush()
                    quantity, price = (2 if index % 5 == 0 else 1), 2500 + index * 125
                    amount = quantity * price
                    created = now - timedelta(minutes=index + 1)
                    order = Order(full_name=f"Client synthetique {index + 1:02d}", phone="+212600000000",
                                  address="Adresse de test Rabat", city="Rabat", status="delivered",
                                  total=amount + 1234 + (188700 if index == 1 else 0),
                                  shipping=1234, created_at=created, delivered_at=created)
                    fixture.db.session.add(order)
                    fixture.db.session.flush()
                    fixture.db.session.add(OrderItem(order_id=order.id, product_id=product.id,
                                                     quantity=quantity, price=price))
                    if index == 1:
                        mixed_order = order.id
                        fixture.db.session.add_all([
                            OrderItem(order_id=order.id, product_id=foreign_product.id, quantity=1, price=88800),
                            OrderItem(order_id=order.id, product_id=own_service.id, quantity=1, price=99900),
                        ])
                    if index == 38:
                        target_order = order.id
                    if index % 4 == 0:
                        baseline_receipts.append(order.id)
                        fixture.db.session.add(VendorReceipt(vendor_id=fixture.ids.vendor, order_id=order.id,
                                                            note="Especes de demonstration", received_at=now))
                    owned_orders.append(order.id)
                    amounts[order.id] = amount
                    archive = RentalArchive(owner_id=fixture.ids.vendor, shop_id=fixture.ids.shop,
                                            title=("Appartement historique " + str(index + 1)) if index != 38 else
                                                  "Studio lumineux Agdal cible",
                                            slug=f"archive-synthetic-{index + 1}", city="Rabat" if index % 2 == 0 else "Sale",
                                            area="Agdal" if index == 38 else "Centre", listing_type="monthly",
                                            property_type="studio" if index == 38 else "apartment",
                                            rent_cents=250000 + index * 1000, deposit_cents=100000,
                                            owner_fee_cents=50000, owner_fee_text="Frais synthetiques",
                                            platform_commission_rate_bps=1250,
                                            platform_commission_amount_cents=6250,
                                            archived_view_count=3 + index,
                                            closed_reason=("taken", "expired", "deleted_by_owner", "deleted_by_admin")[index % 4],
                                            closed_at=now - timedelta(minutes=index + 1),
                                            created_at_original=now - timedelta(days=3),
                                            expires_at_original=now + timedelta(days=4),
                                            archive_delete_after=now + timedelta(days=30))
                    fixture.db.session.add(archive)
                    fixture.db.session.flush()
                    owned_archives.append(archive.id)
                    if index == 38:
                        target_archive = archive.id
                for product, label in ((foreign_product, "SECRET_COMMANDE_ETRANGERE"),
                                       (own_service, "SERVICE_SEUL_HORS_CAISSE")):
                    order = Order(full_name=label, phone="+212600000000", address="Test", city="Rabat",
                                  status="delivered", total=99999, created_at=now, delivered_at=now)
                    fixture.db.session.add(order)
                    fixture.db.session.flush()
                    fixture.db.session.add(OrderItem(order_id=order.id, product_id=product.id,
                                                     quantity=1, price=99999))
                foreign_archive = RentalArchive(owner_id=fixture.ids.foreign_owner, shop_id=fixture.ids.foreign_shop,
                                                title="SECRET_ARCHIVE_AUTRE_PROPRIETAIRE", city="Rabat", area="Centre",
                                                listing_type="monthly", property_type="apartment", rent_cents=900000,
                                                closed_reason="taken", closed_at=now)
                fixture.db.session.add(foreign_archive)
                fixture.db.session.commit()
                foreign_archive_id = foreign_archive.id

            def preview_static(filename):
                if filename.startswith("uploads/rentals/"):
                    return send_from_directory(str(fixture.static), filename)
                if filename.startswith("uploads/"):
                    return send_from_directory(str(fixture.uploads), filename[len("uploads/"):])
                return send_from_directory(str(fixture.source_static), filename)

            app.view_functions["static"] = preview_static

            def records_fixture():
                session["_user_id"] = str(fixture.ids.vendor)
                session["_fresh"] = True
                if request.args.get("reset", "1") == "1":
                    VendorReceipt.query.filter_by(vendor_id=fixture.ids.vendor).delete(synchronize_session=False)
                    for order_id in baseline_receipts:
                        fixture.db.session.add(VendorReceipt(vendor_id=fixture.ids.vendor, order_id=order_id,
                                                            note="Especes de demonstration", received_at=now))
                    fixture.db.session.commit()
                receipts = VendorReceipt.query.filter_by(vendor_id=fixture.ids.vendor).all()
                return jsonify(orders=owned_orders, archives=owned_archives, amounts=amounts,
                               confirmed=[item.order_id for item in receipts],
                               receiptNotes={item.order_id: item.note for item in receipts},
                               targetOrder=target_order, targetArchive=target_archive,
                               mixedOrder=mixed_order, foreignArchive=foreign_archive_id,
                               temporary=directory)

            # Fixture-only static namespace is exempt from both login setup and
            # vendor-private-mode guards; production application is untouched.
            app.add_url_rule("/__vendor_records_fixture__", "records_fixture.static", records_fixture)
            port = int(os.environ.get("VENDOR_RECORDS_PREVIEW_PORT", "5078"))
            with make_server("127.0.0.1", port, app, threaded=True, request_handler=QuietPreviewHandler) as server:
                print(f"VENDOR_RECORDS_READY http://127.0.0.1:{port} temporary={directory}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
