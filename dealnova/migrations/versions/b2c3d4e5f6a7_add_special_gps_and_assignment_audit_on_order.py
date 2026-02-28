"""Add special GPS fields and assignment audit columns on order.

Revision ID: b2c3d4e5f6a7
Revises: a1f4c9d8e7b6
Create Date: 2026-02-23 23:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1f4c9d8e7b6"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "order", "assigned_at"):
        op.add_column("order", sa.Column("assigned_at", sa.DateTime(), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "order", "assigned_by_user_id"):
        op.add_column("order", sa.Column("assigned_by_user_id", sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "order", "special_pickup_lat"):
        op.add_column("order", sa.Column("special_pickup_lat", sa.Float(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_pickup_lng"):
        op.add_column("order", sa.Column("special_pickup_lng", sa.Float(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_pickup_maps_url"):
        op.add_column("order", sa.Column("special_pickup_maps_url", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "order", "special_dropoff_lat"):
        op.add_column("order", sa.Column("special_dropoff_lat", sa.Float(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_dropoff_lng"):
        op.add_column("order", sa.Column("special_dropoff_lng", sa.Float(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "special_dropoff_maps_url"):
        op.add_column("order", sa.Column("special_dropoff_maps_url", sa.Text(), nullable=True))
        inspector = sa.inspect(bind)

    if not _has_index(inspector, "order", "ix_order_assigned_at"):
        op.create_index("ix_order_assigned_at", "order", ["assigned_at"], unique=False)
    if not _has_index(inspector, "order", "ix_order_assigned_by_user_id"):
        op.create_index("ix_order_assigned_by_user_id", "order", ["assigned_by_user_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "order", "ix_order_assigned_by_user_id"):
        op.drop_index("ix_order_assigned_by_user_id", table_name="order")
    if _has_index(inspector, "order", "ix_order_assigned_at"):
        op.drop_index("ix_order_assigned_at", table_name="order")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "order", "special_dropoff_maps_url"):
        op.drop_column("order", "special_dropoff_maps_url")
    if _has_column(inspector, "order", "special_dropoff_lng"):
        op.drop_column("order", "special_dropoff_lng")
    if _has_column(inspector, "order", "special_dropoff_lat"):
        op.drop_column("order", "special_dropoff_lat")
    if _has_column(inspector, "order", "special_pickup_maps_url"):
        op.drop_column("order", "special_pickup_maps_url")
    if _has_column(inspector, "order", "special_pickup_lng"):
        op.drop_column("order", "special_pickup_lng")
    if _has_column(inspector, "order", "special_pickup_lat"):
        op.drop_column("order", "special_pickup_lat")
    if _has_column(inspector, "order", "assigned_by_user_id"):
        op.drop_column("order", "assigned_by_user_id")
