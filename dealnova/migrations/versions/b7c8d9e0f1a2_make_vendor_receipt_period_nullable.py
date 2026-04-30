"""Make vendor receipt period optional.

Revision ID: b7c8d9e0f1a2
Revises: 0a1b2c3d4e5f
Create Date: 2026-04-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vendor_receipt") as batch_op:
        batch_op.alter_column(
            "period_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade():
    with op.batch_alter_table("vendor_receipt") as batch_op:
        batch_op.alter_column(
            "period_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
