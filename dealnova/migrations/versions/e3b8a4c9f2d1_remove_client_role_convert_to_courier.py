"""Remove client role and convert legacy roles to courier.

Revision ID: e3b8a4c9f2d1
Revises: b6f2b2c8a1e3
Create Date: 2026-02-22 16:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e3b8a4c9f2d1"
down_revision = "b6f2b2c8a1e3"
branch_labels = None
depends_on = None


def upgrade():
    # Normalize role casing/spacing first.
    op.execute(sa.text('UPDATE "user" SET role = lower(trim(role)) WHERE role IS NOT NULL'))

    # Enforce allowed roles only: admin, vendor, courier.
    # Legacy "client" and any unknown/empty role are converted to courier.
    op.execute(
        sa.text(
            """
            UPDATE "user"
            SET role = 'courier'
            WHERE role IS NULL
               OR role = ''
               OR role NOT IN ('admin', 'vendor', 'courier')
            """
        )
    )


def downgrade():
    # Non-reversible migration: we cannot distinguish original couriers
    # from users converted from "client"/invalid roles.
    pass
