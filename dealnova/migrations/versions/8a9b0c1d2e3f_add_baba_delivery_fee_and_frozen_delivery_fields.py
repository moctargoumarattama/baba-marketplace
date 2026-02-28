"""Add fixed Baba delivery fee settings and frozen delivery economics on order.

Revision ID: 8a9b0c1d2e3f
Revises: 7f4a1b2c3d4e
Create Date: 2026-02-23 14:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8a9b0c1d2e3f"
down_revision = "7f4a1b2c3d4e"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _has_foreign_key(inspector, table_name: str, fk_name: str) -> bool:
    return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not _has_column(inspector, "platform_settings", "delivery_platform_fee_fixed_cents"):
        op.add_column(
            "platform_settings",
            sa.Column("delivery_platform_fee_fixed_cents", sa.Integer(), nullable=False, server_default="0"),
        )
        inspector = sa.inspect(bind)

    if not _has_column(inspector, "order", "delivery_price_cents"):
        op.add_column("order", sa.Column("delivery_price_cents", sa.Integer(), nullable=True, server_default="0"))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "delivery_platform_fee_cents"):
        op.add_column(
            "order",
            sa.Column("delivery_platform_fee_cents", sa.Integer(), nullable=True, server_default="0"),
        )
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "delivery_courier_net_cents"):
        op.add_column(
            "order",
            sa.Column("delivery_courier_net_cents", sa.Integer(), nullable=True, server_default="0"),
        )
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "baba_fee_settled_at"):
        op.add_column("order", sa.Column("baba_fee_settled_at", sa.DateTime(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_column(inspector, "order", "baba_fee_settled_by_user_id"):
        op.add_column("order", sa.Column("baba_fee_settled_by_user_id", sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)

    if dialect != "sqlite" and not _has_foreign_key(
        inspector,
        "order",
        "fk_order_baba_fee_settled_by_user_id_user",
    ):
        op.create_foreign_key(
            "fk_order_baba_fee_settled_by_user_id_user",
            "order",
            "user",
            ["baba_fee_settled_by_user_id"],
            ["id"],
        )
        inspector = sa.inspect(bind)

    if not _has_index(inspector, "order", "ix_order_delivery_platform_fee_cents"):
        op.create_index("ix_order_delivery_platform_fee_cents", "order", ["delivery_platform_fee_cents"], unique=False)
    if not _has_index(inspector, "order", "ix_order_baba_fee_settled_at"):
        op.create_index("ix_order_baba_fee_settled_at", "order", ["baba_fee_settled_at"], unique=False)
    if not _has_index(inspector, "order", "ix_order_baba_fee_settled_by_user_id"):
        op.create_index("ix_order_baba_fee_settled_by_user_id", "order", ["baba_fee_settled_by_user_id"], unique=False)

    op.execute(
        sa.text(
            'UPDATE "order" '
            'SET delivery_price_cents = COALESCE(delivery_price_cents, shipping, 0), '
            'delivery_platform_fee_cents = COALESCE(delivery_platform_fee_cents, 0), '
            'delivery_courier_net_cents = COALESCE(delivery_courier_net_cents, shipping, 0)'
        )
    )



def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if _has_index(inspector, "order", "ix_order_baba_fee_settled_by_user_id"):
        op.drop_index("ix_order_baba_fee_settled_by_user_id", table_name="order")
    if _has_index(inspector, "order", "ix_order_baba_fee_settled_at"):
        op.drop_index("ix_order_baba_fee_settled_at", table_name="order")
    if _has_index(inspector, "order", "ix_order_delivery_platform_fee_cents"):
        op.drop_index("ix_order_delivery_platform_fee_cents", table_name="order")

    inspector = sa.inspect(bind)
    if dialect != "sqlite" and _has_foreign_key(inspector, "order", "fk_order_baba_fee_settled_by_user_id_user"):
        op.drop_constraint("fk_order_baba_fee_settled_by_user_id_user", "order", type_="foreignkey")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "order", "baba_fee_settled_by_user_id"):
        op.drop_column("order", "baba_fee_settled_by_user_id")
    if _has_column(inspector, "order", "baba_fee_settled_at"):
        op.drop_column("order", "baba_fee_settled_at")
    if _has_column(inspector, "order", "delivery_courier_net_cents"):
        op.drop_column("order", "delivery_courier_net_cents")
    if _has_column(inspector, "order", "delivery_platform_fee_cents"):
        op.drop_column("order", "delivery_platform_fee_cents")
    if _has_column(inspector, "order", "delivery_price_cents"):
        op.drop_column("order", "delivery_price_cents")

    inspector = sa.inspect(bind)
    if _has_column(inspector, "platform_settings", "delivery_platform_fee_fixed_cents"):
        op.drop_column("platform_settings", "delivery_platform_fee_fixed_cents")
