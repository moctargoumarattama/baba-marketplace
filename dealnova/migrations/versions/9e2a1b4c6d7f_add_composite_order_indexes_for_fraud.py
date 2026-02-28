"""Add composite order indexes for fraud analytics.

Revision ID: 9e2a1b4c6d7f
Revises: c4d5e6f7a8b9
Create Date: 2026-02-23 03:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9e2a1b4c6d7f"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_index(inspector, "order", "ix_order_created_at_phone_digits"):
        op.create_index(
            "ix_order_created_at_phone_digits",
            "order",
            ["created_at", "phone_digits"],
            unique=False,
        )

    if not _has_index(inspector, "order", "ix_order_created_at_order_ip"):
        op.create_index(
            "ix_order_created_at_order_ip",
            "order",
            ["created_at", "order_ip"],
            unique=False,
        )

    if not _has_index(inspector, "order", "ix_order_created_at_status"):
        op.create_index(
            "ix_order_created_at_status",
            "order",
            ["created_at", "status"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, "order", "ix_order_created_at_status"):
        op.drop_index("ix_order_created_at_status", table_name="order")

    if _has_index(inspector, "order", "ix_order_created_at_order_ip"):
        op.drop_index("ix_order_created_at_order_ip", table_name="order")

    if _has_index(inspector, "order", "ix_order_created_at_phone_digits"):
        op.drop_index("ix_order_created_at_phone_digits", table_name="order")

