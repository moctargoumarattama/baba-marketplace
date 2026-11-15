"""cleanup legacy vendor_application table and seller_commission_percent column

Revision ID: 20261115rm_legacy_va_sc
Revises: 20260511rm_delivery, d1e2f3a4b5c6
Create Date: 2026-11-15 02:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20261115rm_legacy_va_sc"
down_revision = ("20260511rm_delivery", "d1e2f3a4b5c6")
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "vendor_application"):
        op.drop_table("vendor_application")

    if _has_table(inspector, "platform_settings") and _has_column(
        inspector, "platform_settings", "seller_commission_percent"
    ):
        op.drop_column("platform_settings", "seller_commission_percent")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "platform_settings") and not _has_column(
        inspector, "platform_settings", "seller_commission_percent"
    ):
        op.add_column(
            "platform_settings",
            sa.Column("seller_commission_percent", sa.Float(), nullable=False, server_default="10.0"),
        )
