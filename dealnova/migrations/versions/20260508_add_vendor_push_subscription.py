"""add vendor push subscription

Revision ID: 20260508push
Revises: f9a1b2c3d4e5
Create Date: 2026-05-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260508push"
down_revision = "f9a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "vendor_push_subscription" in inspector.get_table_names():
        return

    op.create_table(
        "vendor_push_subscription",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["vendor_id"], ["user.id"], name="fk_vendor_push_subscription_vendor_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vendor_push_subscription_vendor_id", "vendor_push_subscription", ["vendor_id"], unique=False)
    op.create_index("ix_vendor_push_subscription_is_active", "vendor_push_subscription", ["is_active"], unique=False)
    op.create_index("uq_vendor_push_subscription_endpoint", "vendor_push_subscription", ["endpoint"], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "vendor_push_subscription" not in inspector.get_table_names():
        return
    op.drop_index("uq_vendor_push_subscription_endpoint", table_name="vendor_push_subscription")
    op.drop_index("ix_vendor_push_subscription_is_active", table_name="vendor_push_subscription")
    op.drop_index("ix_vendor_push_subscription_vendor_id", table_name="vendor_push_subscription")
    op.drop_table("vendor_push_subscription")
