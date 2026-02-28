"""Unify delivery fields on Order for marketplace and special flows.

Revision ID: a1f4c9d8e7b6
Revises: c9d0e1f2a3b4
Create Date: 2026-02-23 20:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1f4c9d8e7b6"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "order", "delivery_source"):
        op.add_column(
            "order",
            sa.Column("delivery_source", sa.String(length=20), nullable=False, server_default="marketplace"),
        )
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "delivery_city"):
        op.add_column("order", sa.Column("delivery_city", sa.String(length=120), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "delivery_address"):
        op.add_column("order", sa.Column("delivery_address", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "delivery_lat"):
        op.add_column("order", sa.Column("delivery_lat", sa.Float(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "delivery_lng"):
        op.add_column("order", sa.Column("delivery_lng", sa.Float(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "delivery_maps_url"):
        op.add_column("order", sa.Column("delivery_maps_url", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "customer_name"):
        op.add_column("order", sa.Column("customer_name", sa.String(length=150), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "customer_phone"):
        op.add_column("order", sa.Column("customer_phone", sa.String(length=30), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "order", "special_item"):
        op.add_column("order", sa.Column("special_item", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_pickup_address"):
        op.add_column("order", sa.Column("special_pickup_address", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_dropoff_address"):
        op.add_column("order", sa.Column("special_dropoff_address", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_note"):
        op.add_column("order", sa.Column("special_note", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_datetime"):
        op.add_column("order", sa.Column("special_datetime", sa.String(length=80), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_is_urgent"):
        op.add_column(
            "order",
            sa.Column("special_is_urgent", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        inspector = sa.inspect(bind)

    if not _has_index(inspector, "order", "ix_order_delivery_source"):
        op.create_index("ix_order_delivery_source", "order", ["delivery_source"], unique=False)

    op.execute(
        sa.text(
            'UPDATE "order" '
            "SET delivery_source = COALESCE(NULLIF(delivery_source, ''), 'marketplace')"
        )
    )
    op.execute(
        sa.text(
            'UPDATE "order" '
            "SET delivery_city = COALESCE(delivery_city, city), "
            "delivery_address = COALESCE(delivery_address, address), "
            "customer_name = COALESCE(customer_name, full_name), "
            "customer_phone = COALESCE(customer_phone, phone)"
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "order", "ix_order_delivery_source"):
        op.drop_index("ix_order_delivery_source", table_name="order")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "order", "special_is_urgent"):
        op.drop_column("order", "special_is_urgent")
    if _has_column(inspector, "order", "special_datetime"):
        op.drop_column("order", "special_datetime")
    if _has_column(inspector, "order", "special_note"):
        op.drop_column("order", "special_note")
    if _has_column(inspector, "order", "special_dropoff_address"):
        op.drop_column("order", "special_dropoff_address")
    if _has_column(inspector, "order", "special_pickup_address"):
        op.drop_column("order", "special_pickup_address")
    if _has_column(inspector, "order", "special_item"):
        op.drop_column("order", "special_item")
    if _has_column(inspector, "order", "customer_phone"):
        op.drop_column("order", "customer_phone")
    if _has_column(inspector, "order", "customer_name"):
        op.drop_column("order", "customer_name")
    if _has_column(inspector, "order", "delivery_maps_url"):
        op.drop_column("order", "delivery_maps_url")
    if _has_column(inspector, "order", "delivery_lng"):
        op.drop_column("order", "delivery_lng")
    if _has_column(inspector, "order", "delivery_lat"):
        op.drop_column("order", "delivery_lat")
    if _has_column(inspector, "order", "delivery_address"):
        op.drop_column("order", "delivery_address")
    if _has_column(inspector, "order", "delivery_city"):
        op.drop_column("order", "delivery_city")
    if _has_column(inspector, "order", "delivery_source"):
        op.drop_column("order", "delivery_source")
