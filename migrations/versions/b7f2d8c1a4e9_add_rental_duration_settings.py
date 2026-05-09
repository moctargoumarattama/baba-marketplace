"""add rental duration settings

Revision ID: b7f2d8c1a4e9
Revises: a91d6f0b3e2c
Create Date: 2026-05-07 22:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7f2d8c1a4e9"
down_revision = "a91d6f0b3e2c"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("platform_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "rental_monthly_duration_days",
                sa.Integer(),
                nullable=False,
                server_default="14",
            )
        )
        batch_op.add_column(
            sa.Column(
                "rental_daily_duration_days",
                sa.Integer(),
                nullable=False,
                server_default="14",
            )
        )


def downgrade():
    with op.batch_alter_table("platform_settings", schema=None) as batch_op:
        batch_op.drop_column("rental_daily_duration_days")
        batch_op.drop_column("rental_monthly_duration_days")

