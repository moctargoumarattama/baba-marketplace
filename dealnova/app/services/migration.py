"""Legacy runtime migration helpers.

Deprecated for production. Database schema changes must run through Alembic only.
"""

from sqlalchemy import inspect, text

from ..extensions import db












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






def ensure_vendor_push_subscription_table():
    """Cree la table vendor_push_subscription si absente."""
    print("?? Verification de la table vendor_push_subscription...")
    try:
        from ..models.vendor_push_subscription import VendorPushSubscription
        VendorPushSubscription.__table__.create(db.engine, checkfirst=True)
        print("? Table vendor_push_subscription verifiee")
    except Exception as e:
        print(f"? Erreur vendor_push_subscription: {e}")




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



