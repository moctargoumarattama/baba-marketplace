"""add admin performance indexes

Revision ID: c4d8e91f2a6b
Revises: b7f2d8c1a4e9
Create Date: 2026-05-08 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "c4d8e91f2a6b"
down_revision = "b7f2d8c1a4e9"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rental_listing_created_id
        ON rental_listing (created_at, id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rental_listing_status_created
        ON rental_listing (status, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rental_listing_owner_created
        ON rental_listing (owner_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rental_archive_closed_id
        ON rental_archive (closed_at, id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rental_archive_reason_closed
        ON rental_archive (closed_reason, closed_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rental_archive_owner_closed
        ON rental_archive (owner_id, closed_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rental_archive_owner_reason_closed
        ON rental_archive (owner_id, closed_reason, closed_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_product_vendor_created_id
        ON product (vendor_id, created_at, id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_product_vendor_active_created
        ON product (vendor_id, is_active, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_product_vendor_kind_created
        ON product (vendor_id, kind, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_product_vendor_category_created
        ON product (vendor_id, category_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_product_contact_lead_source_created
        ON product_contact_lead (source, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_featureditem_target_latest
        ON featured_item (
            target_type,
            shop_id,
            product_id,
            location_id,
            is_active,
            ends_at,
            created_at
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_featureditem_created_id
        ON featured_item (created_at, id)
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_featureditem_created_id")
    op.execute("DROP INDEX IF EXISTS ix_featureditem_target_latest")
    op.execute("DROP INDEX IF EXISTS ix_product_contact_lead_source_created")
    op.execute("DROP INDEX IF EXISTS ix_product_vendor_category_created")
    op.execute("DROP INDEX IF EXISTS ix_product_vendor_kind_created")
    op.execute("DROP INDEX IF EXISTS ix_product_vendor_active_created")
    op.execute("DROP INDEX IF EXISTS ix_product_vendor_created_id")
    op.execute("DROP INDEX IF EXISTS ix_rental_archive_owner_reason_closed")
    op.execute("DROP INDEX IF EXISTS ix_rental_archive_owner_closed")
    op.execute("DROP INDEX IF EXISTS ix_rental_archive_reason_closed")
    op.execute("DROP INDEX IF EXISTS ix_rental_archive_closed_id")
    op.execute("DROP INDEX IF EXISTS ix_rental_listing_owner_created")
    op.execute("DROP INDEX IF EXISTS ix_rental_listing_status_created")
    op.execute("DROP INDEX IF EXISTS ix_rental_listing_created_id")
