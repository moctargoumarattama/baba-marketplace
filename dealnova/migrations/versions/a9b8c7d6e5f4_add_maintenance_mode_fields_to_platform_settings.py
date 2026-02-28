"""Add maintenance mode fields to platform settings.

Revision ID: a9b8c7d6e5f4
Revises: f1c2d3e4f5a6
Create Date: 2026-02-22 23:35:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a9b8c7d6e5f4"
down_revision = "f1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "platform_settings",
        sa.Column("maintenance_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("platform_settings", sa.Column("maintenance_message", sa.Text(), nullable=True))
    op.add_column("platform_settings", sa.Column("maintenance_enabled_at", sa.DateTime(), nullable=True))
    op.add_column("platform_settings", sa.Column("maintenance_starts_at", sa.DateTime(), nullable=True))
    op.add_column("platform_settings", sa.Column("maintenance_ends_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("platform_settings", "maintenance_ends_at")
    op.drop_column("platform_settings", "maintenance_starts_at")
    op.drop_column("platform_settings", "maintenance_enabled_at")
    op.drop_column("platform_settings", "maintenance_message")
    op.drop_column("platform_settings", "maintenance_enabled")
