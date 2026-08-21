"""Legacy runtime migration helpers.

Deprecated for production. Database schema changes must run through Alembic only.
"""

import json
from datetime import datetime
from slugify import slugify
from sqlalchemy import inspect, text

from ..extensions import db
from ..models.user import User
from ..models.shop import Shop, normalize_allowed_shop_types, normalize_shop_type
from ..models.product import Product


def migrate_vendors_to_shops():
    """Migre automatiquement les vendeurs existants vers le systeme de boutiques"""
    print("?? Migration des vendeurs vers le systeme de boutiques...")

    try:
        inspector = inspect(db.engine)
        if "shop" not in inspector.get_table_names():
            print("?? Table 'shop' non trouvee, migration ignoree")
            return

        vendors = User.query.filter_by(role="vendor").all()
        migrated_count = 0

        for vendor in vendors:
            existing_shop = Shop.query.filter_by(vendor_id=vendor.id).first()
            if existing_shop:
                continue

            shop_name = f"Boutique de {vendor.username}"
            slug = slugify(shop_name)

            counter = 1
            original_slug = slug
            while Shop.query.filter_by(slug=slug).first():
                slug = f"{original_slug}-{counter}"
                counter += 1

            shop = Shop(
                vendor_id=vendor.id,
                name=shop_name,
                slug=slug,
                description=f"Boutique officielle de {vendor.username}",
                contact_phone=vendor.phone if vendor.phone else None,
                contact_email=vendor.email,
                address=vendor.address if vendor.address else None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            db.session.add(shop)
            db.session.flush()

            products = Product.query.filter_by(vendor_id=vendor.id).all()
            for product in products:
                product.shop_id = shop.id

            migrated_count += 1

        if migrated_count > 0:
            db.session.commit()
            print(f"? Migration terminee : {migrated_count} vendeurs migres")
        else:
            print("?? Aucun vendeur a migrer")

    except Exception as e:
        db.session.rollback()
        print(f"? Erreur lors de la migration : {e}")


def ensure_user_last_login_column():
    """Ajoute la colonne user.last_login si elle n'existe pas."""
    print("?? Verification de la colonne user.last_login...")
    try:
        inspector = inspect(db.engine)
        if "user" not in inspector.get_table_names():
            print("?? Table 'user' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("user")]
        if "last_login" in columns:
            print("?? Colonne user.last_login deja presente")
            return

        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN last_login DATETIME'))
        print("? Colonne user.last_login ajoutee")
    except Exception as e:
        print(f"? Erreur lors de l'ajout de la colonne last_login : {e}")


def ensure_user_subscription_columns():
    """Ajoute les colonnes abonnement vendeur si elles n'existent pas."""
    print("?? Verification des colonnes user.subscription_* ...")
    try:
        inspector = inspect(db.engine)
        if "user" not in inspector.get_table_names():
            print("?? Table 'user' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("user")]
        to_add = []

        if "subscription_expires_at" not in columns:
            to_add.append('ALTER TABLE "user" ADD COLUMN subscription_expires_at DATETIME')
        if "subscription_last_paid_at" not in columns:
            to_add.append('ALTER TABLE "user" ADD COLUMN subscription_last_paid_at DATETIME')
        if "subscription_note" not in columns:
            to_add.append('ALTER TABLE "user" ADD COLUMN subscription_note TEXT')
        if "subscription_free_until" not in columns:
            to_add.append('ALTER TABLE "user" ADD COLUMN subscription_free_until DATETIME')

        if not to_add:
            print("?? Colonnes abonnement deja presentes")
            return

        with db.engine.begin() as conn:
            for stmt in to_add:
                conn.execute(text(stmt))
        print(f"? Colonnes abonnement ajoutees : {len(to_add)}")
    except Exception as e:
        print(f"? Erreur lors de l'ajout des colonnes abonnement : {e}")


def ensure_order_payout_columns():
    """Ajoute les colonnes payout si elles n'existent pas."""
    print("?? Verification des colonnes order.* pour reconciliation...")
    try:
        inspector = inspect(db.engine)
        if "order" not in inspector.get_table_names():
            print("?? Table 'order' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("order")]
        to_add = []

        if "vendor_paid" not in columns:
            to_add.append('ALTER TABLE "order" ADD COLUMN vendor_paid BOOLEAN DEFAULT 0')
        if "vendor_paid_at" not in columns:
            to_add.append('ALTER TABLE "order" ADD COLUMN vendor_paid_at DATETIME')
        if "vendor_paid_note" not in columns:
            to_add.append('ALTER TABLE "order" ADD COLUMN vendor_paid_note TEXT')
        if "vendor_paid_by_id" not in columns:
            to_add.append('ALTER TABLE "order" ADD COLUMN vendor_paid_by_id INTEGER')
        if "order_ip" not in columns:
            to_add.append('ALTER TABLE "order" ADD COLUMN order_ip VARCHAR(45)')

        if not to_add:
            print("?? Colonnes payout deja presentes")
            return

        with db.engine.begin() as conn:
            for stmt in to_add:
                conn.execute(text(stmt))
        print(f"? Colonnes payout ajoutees : {len(to_add)}")
    except Exception as e:
        print(f"? Erreur lors de l'ajout des colonnes payout : {e}")


def ensure_vendor_payout_table():
    # Cree la table vendor_payout si absente.
    print("?? Verification de la table vendor_payout...")
    try:
        from ..models.vendor_payout import VendorPayout
        VendorPayout.__table__.create(db.engine, checkfirst=True)
        print("? Table vendor_payout verifiee")
    except Exception as e:
        print(f"? Erreur vendor_payout: {e}")


def ensure_platform_settings_columns():
    """Ajoute les colonnes platform_settings manquantes."""
    print("?? Verification des colonnes platform_settings...")
    try:
        inspector = inspect(db.engine)
        if "platform_settings" not in inspector.get_table_names():
            print("?? Table 'platform_settings' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("platform_settings")]
        to_add = []

        if "low_stock_threshold" not in columns:
            to_add.append('ALTER TABLE "platform_settings" ADD COLUMN low_stock_threshold INTEGER DEFAULT 5')
        if "vendor_subscription_monthly_cents" not in columns:
            to_add.append('ALTER TABLE "platform_settings" ADD COLUMN vendor_subscription_monthly_cents INTEGER DEFAULT 0')
        if "vendor_free_until" not in columns:
            to_add.append('ALTER TABLE "platform_settings" ADD COLUMN vendor_free_until DATETIME')
        if "rental_success_commission_mode" not in columns:
            to_add.append('ALTER TABLE "platform_settings" ADD COLUMN rental_success_commission_mode VARCHAR(20) NOT NULL DEFAULT \'percent\'')
        if "rental_success_commission_bps" not in columns:
            to_add.append('ALTER TABLE "platform_settings" ADD COLUMN rental_success_commission_bps INTEGER NOT NULL DEFAULT 500')
        if "rental_success_commission_fixed_cents" not in columns:
            to_add.append('ALTER TABLE "platform_settings" ADD COLUMN rental_success_commission_fixed_cents INTEGER NOT NULL DEFAULT 0')
        if "rental_monthly_duration_days" not in columns:
            to_add.append('ALTER TABLE "platform_settings" ADD COLUMN rental_monthly_duration_days INTEGER NOT NULL DEFAULT 14')
        if "rental_daily_duration_days" not in columns:
            to_add.append('ALTER TABLE "platform_settings" ADD COLUMN rental_daily_duration_days INTEGER NOT NULL DEFAULT 14')

        if not to_add:
            print("?? Colonnes platform_settings deja presentes")
            return

        with db.engine.begin() as conn:
            for stmt in to_add:
                conn.execute(text(stmt))
        print(f"? Colonnes platform_settings ajoutees : {len(to_add)}")
    except Exception as e:
        print(f"? Erreur platform_settings: {e}")


def ensure_booking_table():
    """Cree la table booking si absente."""
    print("?? Verification de la table booking...")
    try:
        from ..models.booking import Booking
        Booking.__table__.create(db.engine, checkfirst=True)
        print("? Table booking verifiee")
    except Exception as e:
        print(f"? Erreur booking: {e}")


def ensure_product_kind_column():
    """Ajoute la colonne product.kind (physical|service) si elle n'existe pas."""
    print("?? Verification de la colonne product.kind...")
    try:
        inspector = inspect(db.engine)
        if "product" not in inspector.get_table_names():
            print("?? Table 'product' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("product")]
        if "kind" in columns:
            print("?? Colonne product.kind deja presente")
            return

        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE "product" ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT \'physical\''))
        print("? Colonne product.kind ajoutee")
    except Exception as e:
        print(f"? Erreur lors de l'ajout de la colonne product.kind : {e}")


def ensure_product_video_column():
    """Ajoute la colonne product.video_file si elle n'existe pas."""
    print("?? Verification de la colonne product.video_file...")
    try:
        inspector = inspect(db.engine)
        if "product" not in inspector.get_table_names():
            print("?? Table 'product' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("product")]
        if "video_file" in columns:
            print("?? Colonne product.video_file deja presente")
            return

        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE "product" ADD COLUMN video_file VARCHAR(255)'))
        print("? Colonne product.video_file ajoutee")
    except Exception as e:
        print(f"? Erreur lors de l'ajout de la colonne product.video_file : {e}")


def ensure_category_type_column():
    """Ajoute et normalise la colonne category.category_type (products|services)."""
    print("?? Verification de la colonne category.category_type...")
    try:
        inspector = inspect(db.engine)
        if "category" not in inspector.get_table_names():
            print("?? Table 'category' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("category")]
        with db.engine.begin() as conn:
            if "category_type" not in columns:
                conn.execute(
                    text(
                        'ALTER TABLE "category" ADD COLUMN category_type VARCHAR(20) NOT NULL DEFAULT \'products\''
                    )
                )

            conn.execute(
                text(
                    "UPDATE category SET category_type = 'products' "
                    "WHERE category_type IS NULL OR TRIM(category_type) = ''"
                )
            )
            conn.execute(
                text(
                    "UPDATE category SET category_type = 'products' "
                    "WHERE LOWER(TRIM(category_type)) IN ('product', 'physical')"
                )
            )
            conn.execute(
                text(
                    "UPDATE category SET category_type = 'services' "
                    "WHERE LOWER(TRIM(category_type)) IN ('service', 'booking')"
                )
            )
            conn.execute(
                text(
                    "UPDATE category SET category_type = 'products' "
                    "WHERE LOWER(TRIM(category_type)) NOT IN ('products', 'services')"
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_category_category_type ON category(category_type)")
            )

        print("? Colonne category.category_type verifiee")
    except Exception as e:
        print(f"? Erreur lors de la verification de category.category_type : {e}")


def ensure_shop_availability_columns():
    """Ajoute les colonnes shop.is_open / closed_until / closed_note si absentes."""
    print("?? Verification des colonnes shop.is_open/closed_* ...")
    try:
        inspector = inspect(db.engine)
        if "shop" not in inspector.get_table_names():
            print("?? Table 'shop' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("shop")]
        to_add = []

        if "is_open" not in columns:
            to_add.append('ALTER TABLE "shop" ADD COLUMN is_open BOOLEAN NOT NULL DEFAULT 1')
        if "closed_until" not in columns:
            to_add.append('ALTER TABLE "shop" ADD COLUMN closed_until DATETIME')
        if "closed_note" not in columns:
            to_add.append('ALTER TABLE "shop" ADD COLUMN closed_note VARCHAR(255)')

        if not to_add:
            print("?? Colonnes shop availability deja presentes")
            return

        with db.engine.begin() as conn:
            for stmt in to_add:
                conn.execute(text(stmt))
        print(f"? Colonnes shop availability ajoutees : {len(to_add)}")
    except Exception as e:
        print(f"? Erreur lors de l'ajout des colonnes shop availability : {e}")


def ensure_shop_type_columns():
    """Ajoute et normalise les colonnes shop.primary_type / allowed_types_json."""
    print("?? Verification des colonnes shop.primary_type/allowed_types_json...")
    try:
        inspector = inspect(db.engine)
        if "shop" not in inspector.get_table_names():
            print("?? Table 'shop' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("shop")]
        to_add = []

        if "primary_type" not in columns:
            to_add.append('ALTER TABLE "shop" ADD COLUMN primary_type VARCHAR(20) NOT NULL DEFAULT \'products\'')
        if "allowed_types_json" not in columns:
            to_add.append('ALTER TABLE "shop" ADD COLUMN allowed_types_json TEXT NOT NULL DEFAULT \'["products"]\'')

        with db.engine.begin() as conn:
            for stmt in to_add:
                conn.execute(text(stmt))

            conn.execute(text("UPDATE shop SET primary_type = 'products' WHERE primary_type IS NULL OR TRIM(primary_type) = ''"))
            conn.execute(text("UPDATE shop SET allowed_types_json = '[\"products\"]' WHERE allowed_types_json IS NULL OR TRIM(allowed_types_json) = ''"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_shop_primary_type ON shop(primary_type)"))

            rows = conn.execute(text("SELECT id, primary_type, allowed_types_json FROM shop")).mappings().all()
            for row in rows:
                primary = normalize_shop_type(row.get("primary_type")) or "products"

                raw_allowed = (row.get("allowed_types_json") or "").strip()
                parsed_allowed: list[str] = []
                if raw_allowed:
                    try:
                        loaded = json.loads(raw_allowed)
                        if isinstance(loaded, list):
                            parsed_allowed = [str(item) for item in loaded]
                    except Exception:
                        parsed_allowed = [item.strip() for item in raw_allowed.split(",") if item.strip()]

                normalized_allowed = normalize_allowed_shop_types(parsed_allowed, primary_type=primary)
                conn.execute(
                    text(
                        "UPDATE shop SET primary_type = :primary, allowed_types_json = :allowed WHERE id = :shop_id"
                    ),
                    {
                        "primary": primary,
                        "allowed": json.dumps(normalized_allowed, ensure_ascii=False),
                        "shop_id": row["id"],
                    },
                )

        print("? Colonnes shop types verifiees")
    except Exception as e:
        print(f"? Erreur lors de l'ajout des colonnes shop types : {e}")


def ensure_shop_precise_location_columns():
    """Ajoute les colonnes de localisation precise boutique service si absentes."""
    print("?? Verification des colonnes shop.service_location* ...")
    try:
        inspector = inspect(db.engine)
        if "shop" not in inspector.get_table_names():
            print("?? Table 'shop' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("shop")]
        to_add = []

        if "service_latitude" not in columns:
            to_add.append('ALTER TABLE "shop" ADD COLUMN service_latitude FLOAT')
        if "service_longitude" not in columns:
            to_add.append('ALTER TABLE "shop" ADD COLUMN service_longitude FLOAT')
        if "service_location_note" not in columns:
            to_add.append('ALTER TABLE "shop" ADD COLUMN service_location_note VARCHAR(255)')

        if not to_add:
            print("?? Colonnes shop.service_location* deja presentes")
            return

        with db.engine.begin() as conn:
            for stmt in to_add:
                conn.execute(text(stmt))

        print(f"? Colonnes service localisation ajoutees : {len(to_add)}")
    except Exception as e:
        print(f"? Erreur lors de l'ajout des colonnes service localisation : {e}")


def ensure_promo_workflow_columns():
    """Ajoute les colonnes de validation des promotions."""
    print("?? Verification des colonnes promo workflow...")
    try:
        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())
        with db.engine.begin() as conn:
            if "promo" in table_names:
                promo_columns = [col["name"] for col in inspector.get_columns("promo")]
                promo_to_add = []
                if "status" not in promo_columns:
                    promo_to_add.append('ALTER TABLE "promo" ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT \'approved\'')
                if "review_note" not in promo_columns:
                    promo_to_add.append('ALTER TABLE "promo" ADD COLUMN review_note TEXT')
                if "reviewed_by_id" not in promo_columns:
                    promo_to_add.append('ALTER TABLE "promo" ADD COLUMN reviewed_by_id INTEGER')
                if "reviewed_at" not in promo_columns:
                    promo_to_add.append('ALTER TABLE "promo" ADD COLUMN reviewed_at DATETIME')
                if "created_at" not in promo_columns:
                    promo_to_add.append('ALTER TABLE "promo" ADD COLUMN created_at DATETIME')
                if "updated_at" not in promo_columns:
                    promo_to_add.append('ALTER TABLE "promo" ADD COLUMN updated_at DATETIME')
                for stmt in promo_to_add:
                    conn.execute(text(stmt))
                conn.execute(text("UPDATE promo SET status = 'approved' WHERE status IS NULL OR TRIM(status) = ''"))
                conn.execute(text("UPDATE promo SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
                promo_indexes = {idx["name"] for idx in inspector.get_indexes("promo")}
                if "ix_promo_status_end_date" not in promo_indexes:
                    conn.execute(text("CREATE INDEX ix_promo_status_end_date ON promo(status, end_date)"))

            if "shop" in table_names:
                shop_columns = [col["name"] for col in inspector.get_columns("shop")]
                if "promo_trusted" not in shop_columns:
                    conn.execute(text('ALTER TABLE "shop" ADD COLUMN promo_trusted BOOLEAN NOT NULL DEFAULT 0'))
                shop_indexes = {idx["name"] for idx in inspector.get_indexes("shop")}
                if "ix_shop_promo_trusted" not in shop_indexes:
                    conn.execute(text("CREATE INDEX ix_shop_promo_trusted ON shop(promo_trusted)"))
        print("? Colonnes promo workflow verifiees")
    except Exception as e:
        print(f"? Erreur promo workflow: {e}")


def ensure_user_vendor_history_pin_column():
    """Ajoute la colonne user.vendor_history_pin_hash si elle n'existe pas."""
    print("?? Verification de la colonne user.vendor_history_pin_hash...")
    try:
        inspector = inspect(db.engine)
        if "user" not in inspector.get_table_names():
            print("?? Table 'user' non trouvee, verification ignoree")
            return

        columns = [col["name"] for col in inspector.get_columns("user")]
        if "vendor_history_pin_hash" in columns:
            print("?? Colonne user.vendor_history_pin_hash deja presente")
            return

        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN vendor_history_pin_hash VARCHAR(256)'))
        print("? Colonne user.vendor_history_pin_hash ajoutee")
    except Exception as e:
        print(f"? Erreur lors de l'ajout de la colonne vendor_history_pin_hash : {e}")


def ensure_vendor_receipt_table():
    """Cree la table vendor_receipt si absente."""
    print("?? Verification de la table vendor_receipt...")
    try:
        from ..models.vendor_receipt import VendorReceipt
        VendorReceipt.__table__.create(db.engine, checkfirst=True)
        print("? Table vendor_receipt verifiee")
    except Exception as e:
        print(f"? Erreur vendor_receipt: {e}")


def ensure_vendor_push_subscription_table():
    """Cree la table vendor_push_subscription si absente."""
    print("?? Verification de la table vendor_push_subscription...")
    try:
        from ..models.vendor_push_subscription import VendorPushSubscription
        VendorPushSubscription.__table__.create(db.engine, checkfirst=True)
        print("? Table vendor_push_subscription verifiee")
    except Exception as e:
        print(f"? Erreur vendor_push_subscription: {e}")


def ensure_vendor_fulfillment_table():
    """Cree la table vendor_fulfillment si absente."""
    print("?? Verification de la table vendor_fulfillment...")
    try:
        from ..models.vendor_fulfillment import VendorFulfillment
        VendorFulfillment.__table__.create(db.engine, checkfirst=True)
        print("? Table vendor_fulfillment verifiee")
    except Exception as e:
        print(f"? Erreur vendor_fulfillment: {e}")


def ensure_featured_items_table():
    """Cree la table featured_item si absente."""
    print("?? Verification de la table featured_item...")
    try:
        from ..models.featured_item import FeaturedItem
        FeaturedItem.__table__.create(db.engine, checkfirst=True)
        print("? Table featured_item verifiee")
    except Exception as e:
        print(f"? Erreur featured_item: {e}")


def ensure_vendor_application_table():
    """Cree la table vendor_application si absente."""
    print("?? Verification de la table vendor_application...")
    try:
        from ..models.vendor_application import VendorApplication
        VendorApplication.__table__.create(db.engine, checkfirst=True)
        inspector = inspect(db.engine)
        if "vendor_application" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("vendor_application")]
            to_add = []
            if "password_hash" not in columns:
                to_add.append('ALTER TABLE "vendor_application" ADD COLUMN password_hash VARCHAR(256)')
            if to_add:
                with db.engine.begin() as conn:
                    for stmt in to_add:
                        conn.execute(text(stmt))
            dialect_name = (db.engine.dialect.name or "").lower()
            if dialect_name in {"sqlite", "postgresql"}:
                indexes = {idx.get("name") for idx in inspector.get_indexes("vendor_application")}
                index_statements = []
                dedupe_statements = [
                    """
                    UPDATE vendor_application
                    SET
                        status = 'rejected',
                        review_note = CASE
                            WHEN COALESCE(review_note, '') = ''
                                THEN 'Auto-rejet technique: doublon pending (phone).'
                            ELSE review_note || ' | Auto-rejet technique: doublon pending (phone).'
                        END,
                        reviewed_at = COALESCE(reviewed_at, CURRENT_TIMESTAMP)
                    WHERE id IN (
                        SELECT older.id
                        FROM vendor_application AS older
                        JOIN vendor_application AS newer
                            ON older.phone_digits = newer.phone_digits
                           AND older.status = 'pending'
                           AND newer.status = 'pending'
                           AND older.id < newer.id
                    )
                    """,
                    """
                    UPDATE vendor_application
                    SET
                        status = 'rejected',
                        review_note = CASE
                            WHEN COALESCE(review_note, '') = ''
                                THEN 'Auto-rejet technique: doublon pending (email).'
                            ELSE review_note || ' | Auto-rejet technique: doublon pending (email).'
                        END,
                        reviewed_at = COALESCE(reviewed_at, CURRENT_TIMESTAMP)
                    WHERE id IN (
                        SELECT older.id
                        FROM vendor_application AS older
                        JOIN vendor_application AS newer
                            ON older.email_normalized = newer.email_normalized
                           AND older.email_normalized IS NOT NULL
                           AND newer.email_normalized IS NOT NULL
                           AND older.status = 'pending'
                           AND newer.status = 'pending'
                           AND older.id < newer.id
                    )
                    """,
                ]
                if "uq_vendor_application_pending_phone" not in indexes:
                    index_statements.append(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_application_pending_phone "
                        "ON vendor_application (phone_digits) "
                        "WHERE status = 'pending'"
                    )
                if "uq_vendor_application_pending_email" not in indexes:
                    index_statements.append(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_application_pending_email "
                        "ON vendor_application (email_normalized) "
                        "WHERE status = 'pending' AND email_normalized IS NOT NULL"
                    )
                if index_statements:
                    with db.engine.begin() as conn:
                        for stmt in dedupe_statements:
                            conn.execute(text(stmt))
                        for stmt in index_statements:
                            conn.execute(text(stmt))
        print("? Table vendor_application verifiee")
    except Exception as e:
        print(f"? Erreur vendor_application: {e}")


def ensure_vendor_change_request_table():
    """Cree la table vendor_change_request si absente."""
    print("?? Verification de la table vendor_change_request...")
    try:
        from ..models.vendor_change_request import VendorChangeRequest

        VendorChangeRequest.__table__.create(db.engine, checkfirst=True)
        print("? Table vendor_change_request verifiee")
    except Exception as e:
        print(f"? Erreur vendor_change_request: {e}")


def ensure_rental_tables():
    """Cree les tables location si absentes."""
    print("?? Verification des tables rental_listing/rental_media/rental_archive...")
    try:
        from ..models.rental import RentalListing, RentalMedia, RentalArchive

        RentalListing.__table__.create(db.engine, checkfirst=True)
        RentalMedia.__table__.create(db.engine, checkfirst=True)
        RentalArchive.__table__.create(db.engine, checkfirst=True)

        inspector = inspect(db.engine)
        if "rental_listing" in inspector.get_table_names():
            listing_cols = [col["name"] for col in inspector.get_columns("rental_listing")]
            listing_to_add = []
            if "owner_fee_text" not in listing_cols:
                listing_to_add.append('ALTER TABLE "rental_listing" ADD COLUMN owner_fee_text VARCHAR(255)')
            if "platform_commission_mode" not in listing_cols:
                listing_to_add.append('ALTER TABLE "rental_listing" ADD COLUMN platform_commission_mode VARCHAR(30) NOT NULL DEFAULT \'success_commission\'')
            if "platform_commission_rate_bps" not in listing_cols:
                listing_to_add.append('ALTER TABLE "rental_listing" ADD COLUMN platform_commission_rate_bps INTEGER NOT NULL DEFAULT 0')
            if "platform_commission_fixed_cents" not in listing_cols:
                listing_to_add.append('ALTER TABLE "rental_listing" ADD COLUMN platform_commission_fixed_cents INTEGER')
            if listing_to_add:
                with db.engine.begin() as conn:
                    for stmt in listing_to_add:
                        conn.execute(text(stmt))

        if "rental_archive" in inspector.get_table_names():
            archive_cols = [col["name"] for col in inspector.get_columns("rental_archive")]
            archive_to_add = []
            if "owner_fee_text" not in archive_cols:
                archive_to_add.append('ALTER TABLE "rental_archive" ADD COLUMN owner_fee_text VARCHAR(255)')
            if "platform_commission_rate_bps" not in archive_cols:
                archive_to_add.append('ALTER TABLE "rental_archive" ADD COLUMN platform_commission_rate_bps INTEGER NOT NULL DEFAULT 0')
            if "platform_commission_fixed_cents" not in archive_cols:
                archive_to_add.append('ALTER TABLE "rental_archive" ADD COLUMN platform_commission_fixed_cents INTEGER NOT NULL DEFAULT 0')
            if "platform_commission_amount_cents" not in archive_cols:
                archive_to_add.append('ALTER TABLE "rental_archive" ADD COLUMN platform_commission_amount_cents INTEGER NOT NULL DEFAULT 0')
            if archive_to_add:
                with db.engine.begin() as conn:
                    for stmt in archive_to_add:
                        conn.execute(text(stmt))
        print("? Tables location verifiees")
    except Exception as e:
        print(f"? Erreur tables location: {e}")


def ensure_admin_performance_indexes():
    """Ajoute les indexes composites utilises par les vues admin volumineuses."""
    print("?? Verification des indexes admin performance...")
    index_statements = {
        "rental_listing": [
            (
                "ix_rental_listing_created_id",
                "CREATE INDEX IF NOT EXISTS ix_rental_listing_created_id "
                "ON rental_listing (created_at, id)",
            ),
            (
                "ix_rental_listing_status_created",
                "CREATE INDEX IF NOT EXISTS ix_rental_listing_status_created "
                "ON rental_listing (status, created_at)",
            ),
            (
                "ix_rental_listing_owner_created",
                "CREATE INDEX IF NOT EXISTS ix_rental_listing_owner_created "
                "ON rental_listing (owner_id, created_at)",
            ),
        ],
        "rental_archive": [
            (
                "ix_rental_archive_closed_id",
                "CREATE INDEX IF NOT EXISTS ix_rental_archive_closed_id "
                "ON rental_archive (closed_at, id)",
            ),
            (
                "ix_rental_archive_reason_closed",
                "CREATE INDEX IF NOT EXISTS ix_rental_archive_reason_closed "
                "ON rental_archive (closed_reason, closed_at)",
            ),
            (
                "ix_rental_archive_owner_closed",
                "CREATE INDEX IF NOT EXISTS ix_rental_archive_owner_closed "
                "ON rental_archive (owner_id, closed_at)",
            ),
            (
                "ix_rental_archive_owner_reason_closed",
                "CREATE INDEX IF NOT EXISTS ix_rental_archive_owner_reason_closed "
                "ON rental_archive (owner_id, closed_reason, closed_at)",
            ),
        ],
        "product": [
            (
                "ix_product_vendor_created_id",
                "CREATE INDEX IF NOT EXISTS ix_product_vendor_created_id "
                "ON product (vendor_id, created_at, id)",
            ),
            (
                "ix_product_vendor_active_created",
                "CREATE INDEX IF NOT EXISTS ix_product_vendor_active_created "
                "ON product (vendor_id, is_active, created_at)",
            ),
            (
                "ix_product_vendor_kind_created",
                "CREATE INDEX IF NOT EXISTS ix_product_vendor_kind_created "
                "ON product (vendor_id, kind, created_at)",
            ),
            (
                "ix_product_vendor_category_created",
                "CREATE INDEX IF NOT EXISTS ix_product_vendor_category_created "
                "ON product (vendor_id, category_id, created_at)",
            ),
        ],
        "product_contact_lead": [
            (
                "ix_product_contact_lead_source_created",
                "CREATE INDEX IF NOT EXISTS ix_product_contact_lead_source_created "
                "ON product_contact_lead (source, created_at)",
            ),
        ],
        "featured_item": [
            (
                "ix_featureditem_target_latest",
                "CREATE INDEX IF NOT EXISTS ix_featureditem_target_latest "
                "ON featured_item (target_type, shop_id, product_id, location_id, is_active, ends_at, created_at)",
            ),
            (
                "ix_featureditem_created_id",
                "CREATE INDEX IF NOT EXISTS ix_featureditem_created_id "
                "ON featured_item (created_at, id)",
            ),
        ],
    }
    try:
        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())
        to_create = []
        for table_name, statements in index_statements.items():
            if table_name not in table_names:
                continue
            existing_indexes = {idx.get("name") for idx in inspector.get_indexes(table_name)}
            for index_name, statement in statements:
                if index_name not in existing_indexes:
                    to_create.append(statement)
        if to_create:
            with db.engine.begin() as conn:
                for statement in to_create:
                    conn.execute(text(statement))
        print("? Indexes admin performance verifies")
    except Exception as e:
        print(f"? Erreur indexes admin performance: {e}")


def drop_shop_service_block_table():
    """Supprime la table shop_service_block si elle existe (feature retiree)."""
    print(">> Verification suppression de la table shop_service_block...")
    try:
        inspector = inspect(db.engine)
        if "shop_service_block" not in inspector.get_table_names():
            print("OK: Table shop_service_block absente (rien a faire)")
            return

        with db.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS shop_service_block"))
        print("OK: Table shop_service_block supprimee")
    except Exception as e:
        print(f"WARN: Erreur lors de la suppression de shop_service_block: {e}")

