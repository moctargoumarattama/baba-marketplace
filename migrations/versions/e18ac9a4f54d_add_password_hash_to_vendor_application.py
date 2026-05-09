"""add password hash to vendor application

Revision ID: e18ac9a4f54d
Revises: d3f1c0a9b2c1
Create Date: 2026-05-07 14:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e18ac9a4f54d"
down_revision = "d3f1c0a9b2c1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vendor_application", schema=None) as batch_op:
        batch_op.add_column(sa.Column("password_hash", sa.String(length=256), nullable=True))


def downgrade():
    with op.batch_alter_table("vendor_application", schema=None) as batch_op:
        batch_op.drop_column("password_hash")
