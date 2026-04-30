"""add product contact leads

Revision ID: 0a1b2c3d4e5f
Revises: f9a1b2c3d4e5
Create Date: 2026-04-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0a1b2c3d4e5f"
down_revision = "f9a1b2c3d4e5"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in sa.inspect(bind).get_table_names()


def upgrade():
    if _has_table("product_contact_lead"):
        return

    op.create_table(
        "product_contact_lead",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_name", sa.String(length=100), nullable=True),
        sa.Column("client_phone", sa.String(length=30), nullable=True),
        sa.Column("shop_id", sa.Integer(), nullable=True),
        sa.Column("product_summary_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("estimated_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("whatsapp_phone", sa.String(length=30), nullable=True),
        sa.Column("source", sa.String(length=40), server_default="product_whatsapp", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shop.id"], name="fk_product_contact_lead_shop_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_contact_lead_client_phone", "product_contact_lead", ["client_phone"])
    op.create_index("ix_product_contact_lead_created_at", "product_contact_lead", ["created_at"])
    op.create_index("ix_product_contact_lead_shop_id", "product_contact_lead", ["shop_id"])
    op.create_index("ix_product_contact_lead_source", "product_contact_lead", ["source"])


def downgrade():
    if not _has_table("product_contact_lead"):
        return
    op.drop_index("ix_product_contact_lead_source", table_name="product_contact_lead")
    op.drop_index("ix_product_contact_lead_shop_id", table_name="product_contact_lead")
    op.drop_index("ix_product_contact_lead_created_at", table_name="product_contact_lead")
    op.drop_index("ix_product_contact_lead_client_phone", table_name="product_contact_lead")
    op.drop_table("product_contact_lead")
